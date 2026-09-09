"""Typed request actor boundary.

The development test suite overrides ``get_current_actor`` with a deterministic
actor. No request header or client payload is accepted as an identity source.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request

AUTHENTICATION_NOT_CONFIGURED = HTTPException(
    status_code=501,
    detail={
        "error": {
            "code": "not_implemented",
            "message": "Authentication is not configured.",
        }
    },
)


@dataclass(frozen=True, slots=True)
class RequestActor:
    """Authenticated identity and tenant context for one request."""

    user_id: UUID
    organization_id: UUID


async def get_current_actor(request: Request) -> RequestActor:
    """Resolve the authenticated actor at the application boundary.

    Real authentication is intentionally deferred. Even in development, callers
    must explicitly override this dependency in tests; this prevents accidental
    trust of client-supplied identity fields.
    """

    del request
    raise AUTHENTICATION_NOT_CONFIGURED
