"""OIDC/JWKS RS256 token verification: key rotation, expiry, and failure paths."""

from __future__ import annotations

import base64
import json
import time
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from rag_eval_api.auth.jwt import InvalidTokenError
from rag_eval_api.auth.oidc import OidcVerifier, jwk_from_rsa_public_key

ISSUER = "https://idp.example.test"
AUDIENCE = "rag-eval-api"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _make_key_pair(kid: str) -> tuple[rsa.RSAPrivateKey, dict[str, str]]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwk_from_rsa_public_key(private.public_key(), kid=kid)
    return private, jwk


def _sign(private: rsa.RSAPrivateKey, header: dict, claims: dict) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
    signature = private.sign(
        signing_input.encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return f"{signing_input}.{_b64(signature)}"


def _claims(**overrides: object) -> dict[str, object]:
    now = int(time.time())
    base: dict[str, object] = {
        "sub": str(uuid4()),
        "organization_id": str(uuid4()),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": now + 600,
        "nbf": now - 10,
    }
    base.update(overrides)
    return base


class _StaticJwksSource:
    def __init__(self, *jwks: dict[str, str]):
        self._jwks = list(jwks)
        self.fetch_count = 0

    def fetch(self) -> list[dict[str, str]]:
        self.fetch_count += 1
        return list(self._jwks)


def _verifier(source: _StaticJwksSource) -> OidcVerifier:
    return OidcVerifier(jwks_source=source.fetch, issuer=ISSUER, audience=AUDIENCE)


def test_valid_rs256_token_verifies_and_returns_identity() -> None:
    private, jwk = _make_key_pair("key-1")
    source = _StaticJwksSource(jwk)
    token = _sign(private, {"alg": "RS256", "typ": "JWT", "kid": "key-1"}, _claims())
    user_id, org_id = _verifier(source).verify(token)
    assert str(user_id) and str(org_id)


def test_unknown_kid_triggers_refresh_then_verifies_after_rotation() -> None:
    old_private, old_jwk = _make_key_pair("key-old")
    new_private, new_jwk = _make_key_pair("key-new")
    source = _StaticJwksSource(old_jwk, new_jwk)
    verifier = _verifier(source)
    # Warm the cache with the old key.
    verifier.verify(_sign(old_private, {"alg": "RS256", "kid": "key-old"}, _claims()))
    assert source.fetch_count >= 1
    # Token signed by the new key triggers a JWKS refresh and then verifies.
    token = _sign(new_private, {"alg": "RS256", "kid": "key-new"}, _claims())
    user_id, _ = verifier.verify(token)
    assert str(user_id)


def test_wrong_signature_is_rejected() -> None:
    private_a, jwk_a = _make_key_pair("key-1")
    other_private, _ = _make_key_pair("key-2")
    source = _StaticJwksSource(jwk_a)
    # Signed by a different private key than the JWKS public key.
    token = _sign(other_private, {"alg": "RS256", "kid": "key-1"}, _claims())
    with pytest.raises(InvalidTokenError):
        _verifier(source).verify(token)


def test_hs256_token_is_rejected_in_oidc_mode() -> None:
    private, jwk = _make_key_pair("key-1")
    source = _StaticJwksSource(jwk)
    header = {"alg": "HS256", "typ": "JWT"}
    token = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(_claims()).encode())}.sig"
    with pytest.raises(InvalidTokenError):
        _verifier(source).verify(token)


def test_expired_and_wrong_audience_are_rejected() -> None:
    private, jwk = _make_key_pair("key-1")
    source = _StaticJwksSource(jwk)
    verifier = _verifier(source)
    expired = _sign(private, {"alg": "RS256", "kid": "key-1"}, _claims(exp=int(time.time()) - 100))
    with pytest.raises(InvalidTokenError):
        verifier.verify(expired)
    wrong_aud = _sign(private, {"alg": "RS256", "kid": "key-1"}, _claims(aud="other-api"))
    with pytest.raises(InvalidTokenError):
        verifier.verify(wrong_aud)


def test_malformed_and_oversized_tokens_are_rejected_safely() -> None:
    private, jwk = _make_key_pair("key-1")
    verifier = _verifier(_StaticJwksSource(jwk))
    with pytest.raises(InvalidTokenError):
        verifier.verify("not-a-jwt")
    with pytest.raises(InvalidTokenError):
        verifier.verify("a" * (17 * 1024))
    del private
