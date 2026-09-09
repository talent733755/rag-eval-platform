"""Audit event recording service."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.models import AuditEvent


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
