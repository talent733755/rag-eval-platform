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
    assert (
        "CREATE OR REPLACE FUNCTION public.rag_eval_prevent_audit_event_mutation()" in upgrade_sql
    )
    for table in ("organizations", "projects", "memberships"):
        assert f"CREATE TRIGGER {table}_set_updated_at" in upgrade_sql
        assert f"BEFORE UPDATE ON {table}" in upgrade_sql
    assert "CREATE OR REPLACE FUNCTION public.rag_eval_set_updated_at()" in upgrade_sql
    assert "DROP TRIGGER IF EXISTS audit_events_truncate_guard ON audit_events" in downgrade_sql
    assert "DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events" in downgrade_sql
    assert "DROP FUNCTION IF EXISTS public.rag_eval_prevent_audit_event_mutation()" in downgrade_sql
    assert "DROP FUNCTION IF EXISTS public.rag_eval_set_updated_at()" in downgrade_sql


def test_metrics_migration_creates_versioned_append_only_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    upgrade_sql = _offline_migration_sql("head")
    downgrade_sql = _offline_migration_sql("head:0011_experiment_run_leases", downgrade=True)

    assert "CREATE TABLE metric_definitions" in upgrade_sql
    assert "uq_metric_definitions_key_version" in upgrade_sql
    assert "CREATE TABLE metric_results" in upgrade_sql
    assert "uq_metric_results_run_scope_definition" in upgrade_sql
    assert "metric_result_scope_shape" in upgrade_sql
    assert "CREATE TRIGGER metric_definitions_append_only" in upgrade_sql
    assert "CREATE TRIGGER metric_results_append_only" in upgrade_sql
    assert "REVOKE UPDATE, DELETE ON TABLE metric_results FROM PUBLIC" in upgrade_sql
    assert "DROP TABLE metric_results" in downgrade_sql
    assert "DROP TABLE metric_definitions" in downgrade_sql
    assert "DROP TRIGGER IF EXISTS metric_results_append_only ON metric_results" in downgrade_sql


def test_trace_migration_creates_safe_append_only_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    upgrade_sql = _offline_migration_sql("head")
    downgrade_sql = _offline_migration_sql("head:0012_metrics", downgrade=True)

    assert "CREATE TABLE traces" in upgrade_sql
    assert "CREATE TABLE failure_cases" in upgrade_sql
    assert "CREATE TRIGGER traces_append_only" in upgrade_sql
    assert "CREATE TRIGGER failure_cases_append_only" in upgrade_sql
    assert "REVOKE UPDATE, DELETE ON TABLE traces FROM PUBLIC" in upgrade_sql
    assert "DROP TABLE failure_cases" in downgrade_sql
    assert "DROP TABLE traces" in downgrade_sql


def test_regression_case_migration_preserves_lineage_and_idempotency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    upgrade_sql = _offline_migration_sql("head")
    downgrade_sql = _offline_migration_sql("head:0013_traces_failures", downgrade=True)

    assert "CREATE TABLE regression_cases" in upgrade_sql
    assert "fk_regression_cases_failure_tenant" in upgrade_sql
    assert "fk_regression_cases_candidate_tenant" in upgrade_sql
    assert "fk_regression_cases_dataset_version_tenant" in upgrade_sql
    assert "uq_regression_cases_idempotency" in upgrade_sql
    assert "CREATE TRIGGER regression_cases_append_only" in upgrade_sql
    assert "DROP TABLE regression_cases" in downgrade_sql
