"""OIDC RS256 token verification backed by JWKS with key rotation.

This is the asymmetric counterpart to :mod:`rag_eval_api.auth.jwt` (HS256). It verifies
OIDC access/ID tokens signed with RS256 against a JWKS document, supporting key
rotation via the token's `kid`. The claim contract (`sub`, `organization_id`, `iss`,
`aud`, `exp`, `nbf`) matches the HS256 verifier so both modes produce the same identity
tuple and downstream RBAC is unchanged.

Red lines:

* **Algorithm allowlist.** Only `RS256` is accepted; `HS256`/`none`/other algs are
  rejected so a token can never downgrade to a symmetric or unsigned form.
* **Bounded input.** Oversized tokens are rejected before parsing, and JWKS parsing is
  defensive (duplicate keys, malformed entries are rejected).
* **Fail closed.** Any signature, key, or claim problem raises
  :class:`InvalidTokenError`; verification never returns an identity it could not
  cryptographically confirm.
* **Rotation without a restart.** An unknown `kid` triggers a single JWKS refresh and
  retry; keys are cached by `kid` for the lifetime of the verifier.
"""

from __future__ import annotations

import base64
import binascii
import math
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from rag_eval_api.auth.jwt import (
    MAX_JWT_BYTES,
    InvalidTokenError,
    _parse_object,
    _verify_audience,
)

# JWKS fetch is caller-supplied (sync HTTP) so the verifier has no network dependency.
JwksFetcher = Callable[[], list[dict[str, Any]]]

_ALLOWED_ALG = "RS256"


def _decode_segment(segment: str) -> bytes:
    if not segment or any(not (character.isalnum() or character in "-_") for character in segment):
        raise InvalidTokenError("invalid JWT segment")
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (ValueError, binascii.Error) as exc:
        raise InvalidTokenError("invalid JWT encoding") from exc


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def jwk_from_rsa_public_key(public_key: rsa.RSAPublicKey, *, kid: str) -> dict[str, Any]:
    """Serialize an RSA public key into a JWKS entry (used by tests and tooling)."""

    numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64url_uint(numbers.n),
        "e": _b64url_uint(numbers.e),
    }


def _rsa_key_from_jwk(jwk: Mapping[str, Any]) -> rsa.RSAPublicKey:
    if jwk.get("kty") != "RSA":
        raise InvalidTokenError("JWKS key type is not supported")
    n_b64 = jwk.get("n")
    e_b64 = jwk.get("e")
    if not isinstance(n_b64, str) or not isinstance(e_b64, str):
        raise InvalidTokenError("JWKS key is malformed")
    try:
        n = int.from_bytes(base64.urlsafe_b64decode(n_b64 + "=" * (-len(n_b64) % 4)), "big")
        e = int.from_bytes(base64.urlsafe_b64decode(e_b64 + "=" * (-len(e_b64) % 4)), "big")
        return rsa.RSAPublicNumbers(e, n).public_key()
    except (ValueError, binascii.Error) as exc:
        raise InvalidTokenError("JWKS key is malformed") from exc


class OidcVerifier:
    """Verify RS256 OIDC tokens against a rotating JWKS key set."""

    def __init__(
        self,
        *,
        jwks_source: JwksFetcher,
        issuer: str,
        audience: str,
        leeway_seconds: int = 30,
    ) -> None:
        if not issuer.strip() or not audience.strip():
            raise ValueError("issuer and audience are required")
        self._jwks_source = jwks_source
        self._issuer = issuer
        self._audience = audience
        self._leeway = leeway_seconds
        self._keys: dict[str, rsa.RSAPublicKey] = {}
        self._lock = threading.Lock()

    def _refresh_keys(self) -> None:
        entries = self._jwks_source()
        keys: dict[str, rsa.RSAPublicKey] = {}
        for entry in entries:
            kid = entry.get("kid")
            if not isinstance(kid, str) or not kid:
                raise InvalidTokenError("JWKS entry is missing a key id")
            if kid in keys:
                raise InvalidTokenError("JWKS contains duplicate key ids")
            keys[kid] = _rsa_key_from_jwk(entry)
        if not keys:
            raise InvalidTokenError("JWKS document has no keys")
        self._keys = keys

    def _key_for_kid(self, kid: str | None) -> rsa.RSAPublicKey:
        with self._lock:
            if not self._keys:
                self._refresh_keys()
            if kid is not None and kid in self._keys:
                return self._keys[kid]
            # Unknown kid: refresh once in case the provider rotated keys.
            self._refresh_keys()
            if kid is not None and kid in self._keys:
                return self._keys[kid]
        raise InvalidTokenError("JWT key id is not recognized")

    def verify(self, token: str) -> tuple[UUID, UUID]:
        """Verify a token and return its user and selected organization."""

        if len(token.encode("utf-8")) > MAX_JWT_BYTES:
            raise InvalidTokenError("JWT is too large")
        segments = token.split(".")
        if len(segments) != 3:
            raise InvalidTokenError("JWT must have three segments")
        header_segment, payload_segment, signature_segment = segments
        header = _parse_object(_decode_segment(header_segment))
        if header.get("alg") != _ALLOWED_ALG:
            raise InvalidTokenError("JWT algorithm is not allowed")
        if header.get("typ") not in {None, "JWT", "at+jwt"}:
            raise InvalidTokenError("JWT type is not allowed")
        kid = header.get("kid")
        if kid is not None and not isinstance(kid, str):
            raise InvalidTokenError("JWT key id is invalid")

        public_key = self._key_for_kid(kid)
        signing_input = f"{header_segment}.{payload_segment}".encode()
        signature = _decode_segment(signature_segment)
        try:
            public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature as exc:
            raise InvalidTokenError("JWT signature is invalid") from exc

        claims = _parse_object(_decode_segment(payload_segment))
        return self._identity_from_claims(claims)

    def _identity_from_claims(self, claims: Mapping[str, object]) -> tuple[UUID, UUID]:
        try:
            user_id = UUID(_required_string(claims, "sub"))
            organization_id = UUID(_required_string(claims, "organization_id"))
        except (ValueError, AttributeError) as exc:
            raise InvalidTokenError("JWT identity claims are invalid") from exc
        if _required_string(claims, "iss") != self._issuer:
            raise InvalidTokenError("JWT issuer does not match")
        _verify_audience(claims, self._audience)
        now = time.time()
        if _numeric_claim(claims, "exp") <= now - self._leeway:
            raise InvalidTokenError("JWT has expired")
        if "nbf" in claims and _numeric_claim(claims, "nbf") > now + self._leeway:
            raise InvalidTokenError("JWT is not active")
        return user_id, organization_id


def _required_string(claims: Mapping[str, object], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidTokenError(f"JWT claim {name} is required")
    return value


def _numeric_claim(claims: Mapping[str, object], name: str) -> float:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidTokenError(f"JWT claim {name} is invalid")
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise InvalidTokenError(f"JWT claim {name} is invalid")
    return numeric_value
