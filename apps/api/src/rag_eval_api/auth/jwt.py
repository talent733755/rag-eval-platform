"""Dependency-free HS256 JWT verification for the replaceable auth boundary."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import time
from collections.abc import Mapping
from uuid import UUID

from rag_eval_api.config import Settings

MAX_JWT_BYTES = 16 * 1024


class InvalidTokenError(ValueError):
    """Raised when a JWT fails structural, cryptographic, or claim validation."""


def _decode_segment(segment: str) -> bytes:
    if not segment or any(not (character.isalnum() or character in "-_") for character in segment):
        raise InvalidTokenError("invalid JWT segment")
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (ValueError, binascii.Error) as exc:
        raise InvalidTokenError("invalid JWT encoding") from exc


def _parse_object(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, InvalidTokenError) as exc:
        raise InvalidTokenError("invalid JWT JSON") from exc
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise InvalidTokenError("JWT object is invalid")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidTokenError("duplicate JWT claim")
        result[key] = value
    return result


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


def _verify_audience(claims: Mapping[str, object], expected: str) -> None:
    value = claims.get("aud")
    if isinstance(value, str):
        audiences = {value}
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        audiences = set(value)
    else:
        raise InvalidTokenError("JWT audience is invalid")
    if expected not in audiences:
        raise InvalidTokenError("JWT audience does not match")


def verify_hs256_token(token: str, settings: Settings) -> tuple[UUID, UUID]:
    """Verify a bounded HS256 token and return its user and selected organization."""

    if len(token.encode("utf-8")) > MAX_JWT_BYTES:
        raise InvalidTokenError("JWT is too large")
    segments = token.split(".")
    if len(segments) != 3:
        raise InvalidTokenError("JWT must have three segments")
    header_segment, payload_segment, signature_segment = segments
    header = _parse_object(_decode_segment(header_segment))
    if header.get("alg") != "HS256":
        raise InvalidTokenError("JWT algorithm is not allowed")
    if header.get("typ") not in {None, "JWT"}:
        raise InvalidTokenError("JWT type is not allowed")

    secret = settings.auth_jwt_secret
    issuer = settings.auth_jwt_issuer
    audience = settings.auth_jwt_audience
    if secret is None or issuer is None or audience is None:
        raise InvalidTokenError("JWT authentication is not configured")

    try:
        signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    except UnicodeEncodeError as exc:
        raise InvalidTokenError("JWT encoding is invalid") from exc
    expected_signature = hmac.new(
        secret.get_secret_value().encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    actual_signature = _decode_segment(signature_segment)
    if not hmac.compare_digest(actual_signature, expected_signature):
        raise InvalidTokenError("JWT signature is invalid")

    claims = _parse_object(_decode_segment(payload_segment))
    try:
        user_id = UUID(_required_string(claims, "sub"))
        organization_id = UUID(_required_string(claims, "organization_id"))
    except (ValueError, AttributeError) as exc:
        raise InvalidTokenError("JWT identity claims are invalid") from exc
    if _required_string(claims, "iss") != issuer:
        raise InvalidTokenError("JWT issuer does not match")
    _verify_audience(claims, audience)

    now = time.time()
    leeway = settings.auth_jwt_leeway_seconds
    if _numeric_claim(claims, "exp") <= now - leeway:
        raise InvalidTokenError("JWT has expired")
    if "nbf" in claims and _numeric_claim(claims, "nbf") > now + leeway:
        raise InvalidTokenError("JWT is not active")
    return user_id, organization_id
