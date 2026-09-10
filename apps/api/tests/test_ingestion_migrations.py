from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config

from rag_eval_api.config import DEFAULT_DATABASE_URL


def test_ingestion_migration_offline_sql_creates_all_tables_and_avoids_latest_version_cycle(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    output = StringIO()
    with redirect_stdout(output):
        command.upgrade(config, "head", sql=True)
    sql = output.getvalue()

    for table in (
        "documents",
        "document_versions",
        "document_chunks",
        "candidate_datasets",
        "candidate_generation_configs",
        "candidate_dataset_items",
        "candidate_item_evidence",
        "ingestion_jobs",
        "ingestion_job_attempts",
        "ingestion_job_leases",
    ):
        assert f"CREATE TABLE {table}" in sql
    assert "ALTER TABLE documents ADD CONSTRAINT fk_documents_latest_version" in sql
    assert sql.index("CREATE TABLE documents") < sql.index(
        "ALTER TABLE documents ADD CONSTRAINT fk_documents_latest_version"
    )
    assert "uq_ingestion_jobs_project_operation_idempotency" in sql
    assert "fencing_token" in sql
    assert "CREATE TRIGGER ingestion_job_attempts_append_only" in sql
    assert "CREATE TRIGGER candidate_item_evidence_append_only" in sql
    assert "ON DELETE RESTRICT" in sql
