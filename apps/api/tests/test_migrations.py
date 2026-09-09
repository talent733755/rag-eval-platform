from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from rag_eval_api.config import DEFAULT_DATABASE_URL


def _offline_migration_sql(revision: str, *, downgrade: bool = False) -> str:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    output = StringIO()
    with redirect_stdout(output):
        if downgrade:
            command.downgrade(config, revision, sql=True)
        else:
            command.upgrade(config, revision, sql=True)
    return output.getvalue()


def test_foundation_offline_sql_covers_audit_and_updated_at_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    upgrade_sql = _offline_migration_sql("head")
    downgrade_sql = _offline_migration_sql("0001_foundation:base", downgrade=True)

    assert "public.audit_events" not in upgrade_sql + downgrade_sql
    assert "CREATE TRIGGER audit_events_append_only" in upgrade_sql
    assert "BEFORE UPDATE OR DELETE ON audit_events" in upgrade_sql
    assert "CREATE TRIGGER audit_events_truncate_guard" in upgrade_sql
    assert "BEFORE TRUNCATE ON audit_events" in upgrade_sql
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_events FROM PUBLIC" in upgrade_sql
    assert "CREATE OR REPLACE FUNCTION public.rag_eval_prevent_audit_event_mutation()" in upgrade_sql
    for table in ("organizations", "projects", "memberships"):
        assert f"CREATE TRIGGER {table}_set_updated_at" in upgrade_sql
        assert f"BEFORE UPDATE ON {table}" in upgrade_sql
    assert "CREATE OR REPLACE FUNCTION public.rag_eval_set_updated_at()" in upgrade_sql
    assert "DROP TRIGGER IF EXISTS audit_events_truncate_guard ON audit_events" in downgrade_sql
    assert "DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events" in downgrade_sql
    assert "DROP FUNCTION IF EXISTS public.rag_eval_prevent_audit_event_mutation()" in downgrade_sql
    assert "DROP FUNCTION IF EXISTS public.rag_eval_set_updated_at()" in downgrade_sql
