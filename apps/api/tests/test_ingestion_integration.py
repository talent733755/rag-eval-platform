import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
def integration_database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_ingestion_tables_are_available(integration_database_url: str) -> None:
    engine = create_async_engine(integration_database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name IN "
                    "('documents', 'ingestion_jobs', 'ingestion_job_leases')"
                )
            )
            assert result.scalar_one() == 3
    finally:
        await engine.dispose()
