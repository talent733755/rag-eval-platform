"""Audit event recording service."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_eval_api.models import AuditEvent, Organization

LOGGER = logging.getLogger(__name__)

# Sentinel actor for events where no authenticated identity could be established
# (e.g. an invalid or rejected token). It is not a real user.
AUTH_FAILURE_ACTOR_ID = UUID("00000000-0000-0000-0000-000000000000")


def record_audit_event(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID | None,
    actor_id: UUID,
    action: str,
    resource_type: str,
    resource_id: str,
    metadata: Mapping[str, object],
) -> AuditEvent:
    """Stage one structured audit event in the caller's current transaction."""

    event = AuditEvent(
        organization_id=organization_id,
        project_id=project_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_json=dict(metadata),
    )
    db_session.add(event)
    return event


async def record_auth_failure(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    organization_id: UUID,
    failure_code: str,
    endpoint: str,
) -> None:
    """Best-effort record of an authentication failure.

    The rejected principal may not be resolvable to a user, so the event is recorded
    with the organization boundary and a sentinel actor. It is committed in an
    independent session and NEVER blocks the request — an audit persistence failure
    is logged and swallowed rather than surfacing as a 5xx or suppressing the 401/403.
    """

    try:
        async with session_factory() as session:
            organization_exists = await session.scalar(
                select(Organization.id).where(Organization.id == organization_id).limit(1)
            )
            if organization_exists is None:
                # Never write an audit record against a tenant that does not exist.
                return
            record_audit_event(
                session,
                organization_id=organization_id,
                project_id=None,
                actor_id=AUTH_FAILURE_ACTOR_ID,
                action="auth.failed",
                resource_type="authentication",
                resource_id=endpoint[:255],
                metadata={"failure_code": failure_code},
            )
            await session.commit()
    except Exception:
        LOGGER.exception(
            "auth failure audit could not be persisted",
            extra={"event": "auth.audit_failed", "failure_code": failure_code},
        )
