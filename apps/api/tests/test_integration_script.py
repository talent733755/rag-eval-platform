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


def test_development_access_ports_are_consistent() -> None:
    root = Path(__file__).parents[3]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (root / ".env.example").read_text(encoding="utf-8")
    api_client = (root / "apps" / "web" / "src" / "lib" / "api" / "client.ts").read_text(
        encoding="utf-8"
    )
    project_switcher = (
        root / "apps" / "web" / "src" / "components" / "layout" / "project-switcher.tsx"
    ).read_text(encoding="utf-8")
    playwright = (root / "apps" / "web" / "playwright.config.ts").read_text(encoding="utf-8")

    assert '"127.0.0.1:8003:8000"' in compose
    assert '"127.0.0.1:3003:3000"' in compose
    assert "CORS_ORIGINS=http://localhost:3003" in env_example
    assert "NEXT_PUBLIC_API_BASE_URL=http://localhost:8003" in env_example
    assert '"http://localhost:8003"' in api_client
    assert '"http://localhost:8003"' in project_switcher
    assert "http://127.0.0.1:3003" in playwright
    assert "--port 3003" in playwright
