from __future__ import annotations

from collections.abc import Iterator
from io import BufferedReader, BytesIO
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rag_eval_api.adapters.protocol import TraceEnvelope
from rag_eval_api.models import Base, FailureCase, PersistedTrace
from rag_eval_api.services.failure_cases import persist_failure_case
from rag_eval_api.services.trace_persistence import persist_trace
from rag_eval_api.storage.protocol import BlobObject, StoredBlob


class MemoryBlobStore:
    def __init__(self) -> None:
        self.payloads: dict[str, bytes] = {}

    def put(
        self, source: BytesIO, *, expected_sha256: str | None = None, max_bytes: int | None = None
    ) -> StoredBlob:
        payload = source.read()
        assert max_bytes is None or len(payload) <= max_bytes
        key = f"trace/{len(self.payloads)}"
        self.payloads[key] = payload
        return StoredBlob(storage_key=key, byte_size=len(payload), sha256=expected_sha256 or "")

    def open(self, storage_key: str) -> object:
        return BufferedReader(BytesIO(self.payloads[storage_key]))

    def exists(self, storage_key: str) -> bool:
        return storage_key in self.payloads

    def delete(self, storage_key: str) -> None:
        del self.payloads[storage_key]

    def iter_objects(self) -> Iterator[BlobObject]:
        return iter(())


@pytest_asyncio.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_trace_persistence_redacts_and_references_large_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = [uuid4() for _ in range(4)]
    store = MemoryBlobStore()
    trace = TraceEnvelope(
        trace_id="trace-large",
        level="full",
        stages={"retrieve": {"ids": ["x" * 1_000 for _ in range(100)], "api_key": "secret"}},
    )

    async with session_factory() as session:
        async with session.begin():
            persisted = await persist_trace(
                session,
                organization_id=ids[0],
                project_id=ids[1],
                experiment_id=ids[2],
                run_id=ids[3],
                run_item_id=uuid4(),
                trace=trace,
                blob_store=store,
            )
        assert persisted.trace_version == "trace-v1"
        assert persisted.stages[0]["payload"] is None
        assert persisted.stages[0]["payload_ref"]
        assert "api_key" not in str(persisted.stages)
        assert len(store.payloads) == 1


@pytest.mark.asyncio
async def test_failure_persistence_only_exposes_stable_safe_diagnosis(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = [uuid4() for _ in range(5)]
    async with session_factory() as session:
        async with session.begin():
            failure = await persist_failure_case(
                session,
                organization_id=ids[0],
                project_id=ids[1],
                experiment_id=ids[2],
                run_id=ids[3],
                run_item_id=ids[4],
                attempt_number=1,
                error_code="adapter_timeout",
                trace_id=None,
            )
        assert failure is not None
        assert failure.code == "timeout"
        assert failure.retryable is True
        assert "adapter_timeout" in str(failure.details)
        assert isinstance(failure, FailureCase)
        assert not isinstance(failure, PersistedTrace)
