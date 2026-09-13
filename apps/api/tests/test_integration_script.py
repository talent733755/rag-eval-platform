from pathlib import Path


def test_integration_worker_uses_the_isolated_test_database() -> None:
    root = Path(__file__).parents[3]
    script = root / "scripts" / "run-integration-tests.sh"
    source = script.read_text(encoding="utf-8")

    assert (
        'compose_database_url="postgresql+asyncpg://$postgres_user:$postgres_password@postgres:5432/$TEST_DATABASE_NAME"'
        in source
    )


def test_integration_services_use_dynamic_host_ports() -> None:
    root = Path(__file__).parents[3]
    compose = (root / "docker-compose.integration.yml").read_text(encoding="utf-8")
    create_database = (root / "scripts" / "ci" / "create-test-database.sh").read_text(
        encoding="utf-8"
    )
    run_script = (root / "scripts" / "run-integration-tests.sh").read_text(encoding="utf-8")

    assert '"127.0.0.1::5432"' in compose
    assert '"127.0.0.1::6379"' in compose
    assert 'compose[@]}" port postgres 5432' in create_database
    assert 'compose[@]}" port redis 6379' in run_script
    assert 'postgres_user="$(compose_env_value POSTGRES_USER)"' in run_script
    assert 'postgres_password="$(compose_env_value POSTGRES_PASSWORD)"' in run_script
    assert run_script.index('"${compose[@]}" stop worker') < run_script.index(
        "drop-test-database.sh"
    )
