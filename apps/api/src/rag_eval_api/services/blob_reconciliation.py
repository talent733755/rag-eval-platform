"""Crash-safe reconciliation for blobs not referenced by committed versions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.models import DocumentVersion
from rag_eval_api.storage.errors import BlobNotFound, BlobStoreError
from rag_eval_api.storage.protocol import BlobStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BlobReconciliationResult:
    """Bounded outcome counters for one reconciliation pass."""

    scanned: int
    referenced: int
    skipped_recent: int
    deleted: int
    already_missing: int
    delete_failed: int


def _require_utc(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


async def reconcile_orphaned_blobs(
    db_session: AsyncSession,
    blob_store: BlobStore,
    *,
    grace_period: timedelta,
    now: datetime | None = None,
) -> BlobReconciliationResult:
    """Delete old, unreferenced published blobs without touching live data.

    The database is read first as the source of truth. The grace period protects
    a blob published by a request whose process crashed before its transaction
    committed. A deletion failure is counted and logged so a later pass can
    retry it; it is never converted into a successful cleanup.
    """

    if grace_period.total_seconds() < 0:
        raise ValueError("grace_period must not be negative")
    reconciliation_time = _require_utc(now or datetime.now(UTC), name="now")
    cutoff = reconciliation_time - grace_period
    referenced_keys = set((await db_session.scalars(select(DocumentVersion.storage_key))).all())
    scanned = skipped_recent = deleted = already_missing = delete_failed = 0

    for blob in blob_store.iter_objects():
        scanned += 1
        if blob.storage_key in referenced_keys:
            continue
        modified_at = _require_utc(blob.modified_at, name="blob.modified_at")
        if modified_at >= cutoff:
            skipped_recent += 1
            continue
        try:
            blob_store.delete(blob.storage_key)
        except BlobNotFound:
            already_missing += 1
        except BlobStoreError:
            delete_failed += 1
            LOGGER.warning(
                "blob orphan cleanup failed",
                extra={
                    "event": "blob.orphan_cleanup_failed",
                    "storage_key": blob.storage_key,
                },
            )
        else:
            deleted += 1

    return BlobReconciliationResult(
        scanned=scanned,
        referenced=len(referenced_keys),
        skipped_recent=skipped_recent,
        deleted=deleted,
        already_missing=already_missing,
        delete_failed=delete_failed,
    )
