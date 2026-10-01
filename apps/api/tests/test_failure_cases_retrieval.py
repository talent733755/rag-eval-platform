"""retrieval_miss diagnosis wired into failure case persistence."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rag_eval_api.models import Base, FailureCase
from rag_eval_api.services.failure_cases import persist_failure_case


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_retrieval_miss_recorded_for_succeeded_but_missed_item(
    session: AsyncSession,
) -> None:
    failure = await persist_failure_case(
        session,
        organization_id=uuid4(),
        project_id=uuid4(),
        experiment_id=uuid4(),
        run_id=uuid4(),
        run_item_id=uuid4(),
        attempt_number=1,
        error_code=None,
        trace_id="trace-1",
        retrieved_ids=["noise-1", "noise-2"],
        relevant_ids=["gold-1"],
    )
    await session.commit()

    assert failure is not None
    assert failure.code == "retrieval_miss"
    assert failure.retryable is False
    stored = await session.get(FailureCase, failure.id)
    assert stored is not None
    assert stored.code == "retrieval_miss"


@pytest.mark.asyncio
async def test_no_failure_case_when_retrieval_hit(session: AsyncSession) -> None:
    failure = await persist_failure_case(
        session,
        organization_id=uuid4(),
        project_id=uuid4(),
        experiment_id=uuid4(),
        run_id=uuid4(),
        run_item_id=uuid4(),
        attempt_number=1,
        error_code=None,
        trace_id="trace-1",
        retrieved_ids=["gold-1", "noise-2"],
        relevant_ids=["gold-1"],
    )
    await session.commit()

    assert failure is None


@pytest.mark.asyncio
async def test_retrieval_unavailable_does_not_flag_miss(session: AsyncSession) -> None:
    """When the trace has no structured retrieval evidence we cannot blame retrieval."""

    failure = await persist_failure_case(
        session,
        organization_id=uuid4(),
        project_id=uuid4(),
        experiment_id=uuid4(),
        run_id=uuid4(),
        run_item_id=uuid4(),
        attempt_number=1,
        error_code=None,
        trace_id="trace-1",
        retrieved_ids=[],
        relevant_ids=["gold-1"],
    )
    await session.commit()

    assert failure is None
