"""Typed request actor boundary.

The development test suite overrides ``get_current_actor`` with a deterministic
actor. No request header or client payload is accepted as an identity source.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.auth.jwt import InvalidTokenError, verify_hs256_token
from rag_eval_api.db import get_db_session
from rag_eval_api.models import Membership

AUTHENTICATION_NOT_CONFIGURED = HTTPException(
    status_code=501,
    detail={
        "error": {
            "code": "not_implemented",
            "message": "Authentication is not configured.",
        }
    },
)


def development_auth_error(code: str, message: str) -> HTTPException:
    """Return a safe configuration error for an unusable development actor."""

    return HTTPException(status_code=503, detail={"error": {"code": code, "message": message}})


def authentication_error(code: str, message: str, status_code: int = 401) -> HTTPException:
    """Return an authentication error without exposing token validation details."""

    return HTTPException(
        status_code=status_code, detail={"error": {"code": code, "message": message}}
    )


@dataclass(frozen=True, slots=True)
class RequestActor:
    """Authenticated identity and tenant context for one request."""

    user_id: UUID
    organization_id: UUID


async def get_current_actor(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
) -> RequestActor:
    """Resolve the authenticated actor at the application boundary.

    Real authentication remains required outside development. Local development
    may opt into a seeded actor through ``DEV_ACTOR_ID``; the organization is
    derived from database membership so no client-supplied identity is trusted.
    """

    settings = request.app.state.settings
    if settings.auth_mode == "jwt_hs256":
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise authentication_error(
                "authentication_required", "Bearer authentication is required."
            )
        try:
            user_id, organization_id = verify_hs256_token(token.strip(), settings)
        except InvalidTokenError as exc:
            del exc
            raise authentication_error("invalid_token", "The access token is invalid.")

        membership_id = (
            await db_session.execute(
                select(Membership.id)
                .where(
                    Membership.user_id == user_id,
                    Membership.organization_id == organization_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if membership_id is None:
            raise authentication_error(
                "permission_denied",
                "You do not have permission to access this organization.",
                status_code=403,
            )
        return RequestActor(user_id=user_id, organization_id=organization_id)

    if settings.app_env != "development" or settings.dev_actor_id is None:
        raise AUTHENTICATION_NOT_CONFIGURED

    organization_ids = list(
        (
            await db_session.execute(
                select(Membership.organization_id)
                .where(Membership.user_id == settings.dev_actor_id)
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    if not organization_ids:
        raise development_auth_error(
            "development_actor_not_provisioned",
            "Development actor is not provisioned in any organization.",
        )
    if len(organization_ids) != 1:
        raise development_auth_error(
            "development_actor_ambiguous",
            "Development actor belongs to multiple organizations.",
        )
    return RequestActor(user_id=settings.dev_actor_id, organization_id=organization_ids[0])
