"""Validate, redact, bound, and persist Adapter Trace envelopes."""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.adapters.protocol import TraceEnvelope
from rag_eval_api.models import PersistedTrace
from rag_eval_api.storage.protocol import BlobStore
from rag_eval_api.traces.protocol import (
    MAX_STAGE_PAYLOAD_BYTES,
    TRACE_VERSION,
    TraceRecord,
    TraceStage,
)

MAX_TRACE_BLOB_BYTES = 10 * 1024 * 1024
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "credential",
    "password",
    "secret",
    "token",
)
_PRIVATE_CONTENT_KEY_PARTS = ("prompt", "document", "source_text", "raw_error")


class TracePersistenceError(ValueError):
    """A Trace cannot be stored without exposing unsafe or unbounded data."""


def _is_private_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS + _PRIVATE_CONTENT_KEY_PARTS)


def _redact(value: object, *, key: str = "") -> object:
    if key and _is_private_key(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(child_key): _redact(child_value, key=str(child_key))
            for child_key, child_value in value.items()
            if not _is_private_key(str(child_key))
        }
    if isinstance(value, list):
        return [_redact(item) for item in value[:100]]
    if isinstance(value, str):
        return value[:10_000]
    if isinstance(value, bool | int | float) or value is None:
        return value
    return str(value)[:1_000]


def _digest(value: object) -> tuple[bytes, str]:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return encoded, hashlib.sha256(encoded).hexdigest()


async def persist_trace(
    session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    experiment_id: UUID,
    run_id: UUID,
    run_item_id: UUID,
    trace: TraceEnvelope,
    blob_store: BlobStore | None = None,
) -> PersistedTrace:
    """Persist one canonical Trace envelope without storing private content."""

    existing = await session.scalar(
        select(PersistedTrace).where(
            PersistedTrace.run_item_id == run_item_id,
            PersistedTrace.trace_id == trace.trace_id,
            PersistedTrace.organization_id == organization_id,
            PersistedTrace.project_id == project_id,
        )
    )
    if existing is not None:
        return existing
    now = __import__("datetime").datetime.now(__import__("datetime").UTC)
    stage_records: list[dict[str, object]] = []
    stage_hashes: list[str] = []
    protocol_stages: list[TraceStage] = []
    for name, raw_payload in trace.stages.items():
        if not name.strip() or len(name) > 100:
            raise TracePersistenceError("trace stage name is invalid")
        payload = _redact(raw_payload)
        payload_bytes, payload_hash = _digest(payload)
        stage_hashes.append(payload_hash)
        inline_payload: dict[str, object] | None = (
            payload if isinstance(payload, dict) else {"value": payload}
        )
        blob_reference: dict[str, object] | None = None
        omission_reason: str | None = None
        if len(payload_bytes) > MAX_STAGE_PAYLOAD_BYTES:
            if blob_store is None or len(payload_bytes) > MAX_TRACE_BLOB_BYTES:
                inline_payload = None
                omission_reason = "payload_too_large_for_configured_blob_store"
            else:
                stored = blob_store.put(
                    BytesIO(payload_bytes),
                    expected_sha256=payload_hash,
                    max_bytes=MAX_TRACE_BLOB_BYTES,
                )
                inline_payload = None
                blob_reference = {
                    "storage_key": stored.storage_key,
                    "sha256": stored.sha256,
                    "byte_size": stored.byte_size,
                }
        protocol_stages.append(
            TraceStage(
                name=name,
                started_at=now,
                finished_at=now,
                payload_hash=payload_hash,
                payload=inline_payload,
            )
        )
        stage_record: dict[str, object] = {
            "name": name,
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "payload_hash": payload_hash,
            "payload": inline_payload,
        }
        if blob_reference is not None:
            stage_record["payload_ref"] = blob_reference
        if omission_reason is not None:
            stage_record["omission_reason"] = omission_reason
        stage_records.append(stage_record)
    record = TraceRecord(
        trace_version=TRACE_VERSION,
        trace_id=trace.trace_id,
        run_item_id=str(run_item_id),
        level="minimal" if trace.level == "minimal" else "full",
        stages=tuple(protocol_stages),
    )
    _, payload_hash = _digest({"trace_id": record.trace_id, "stages": stage_hashes})
    persisted = PersistedTrace(
        organization_id=organization_id,
        project_id=project_id,
        experiment_id=experiment_id,
        run_id=run_id,
        run_item_id=run_item_id,
        trace_id=record.trace_id,
        trace_version=record.trace_version,
        level=record.level,
        payload_hash=payload_hash,
        stages=stage_records,
    )
    session.add(persisted)
    await session.flush()
    return persisted
