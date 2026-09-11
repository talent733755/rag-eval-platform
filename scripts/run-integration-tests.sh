#!/usr/bin/env bash

set -Eeuo pipefail

readonly repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Compose otherwise auto-loads the repository's .env in addition to the
# per-run file below. That can silently replace the isolated test credentials.
export COMPOSE_DISABLE_ENV_FILE=1
runtime_dir="$(mktemp -d "${TMPDIR:-/tmp}/rag-eval-integration.XXXXXX")"
compose_env_file="$runtime_dir/compose.env"
test_env_file="$runtime_dir/test.env"
run_id="${GITHUB_RUN_ID:-local-$(date +%s)-$$}"
run_id="$(printf '%s' "$run_id" | tr -c '[:alnum:]' '-' | tr '[:upper:]' '[:lower:]')"
compose_project="rag-eval-integration-$run_id"

cleanup() {
  local status=$?
  set +e
  if [[ -f "$test_env_file" ]]; then
    if ! bash "$repo_root/scripts/ci/drop-test-database.sh" \
      "$test_env_file" "$compose_env_file" "$compose_project"; then
      printf '%s\n' 'WARNING: integration test database cleanup failed' >&2
    fi
  fi
  if ! "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1; then
    printf '%s\n' 'WARNING: integration Compose cleanup failed' >&2
  fi
  rm -rf -- "$runtime_dir"
  exit "$status"
}
trap cleanup EXIT INT TERM

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' 'Docker Compose is required for integration tests; refusing to skip' >&2
  exit 2
fi

cp "$repo_root/.env.example" "$compose_env_file"
cat >>"$compose_env_file" <<EOF
APP_ENV=development
LOG_LEVEL=INFO
SECRET_KEY=integration-test-secret
BLOB_ROOT=/var/lib/rag-eval/blobs
POSTGRES_DB=postgres
POSTGRES_USER=rag_eval_test
POSTGRES_PASSWORD=integration-test-password
COMPOSE_DATABASE_URL=postgresql+asyncpg://rag_eval_test:integration-test-password@postgres:5432/rag_eval
COMPOSE_REDIS_URL=redis://redis:6379/0
COMPOSE_PROJECT_NAME=$compose_project
EOF

compose=(env -i "PATH=$PATH" COMPOSE_DISABLE_ENV_FILE=1 docker compose --project-directory "$repo_root" --file "$repo_root/docker-compose.yml"
  --file "$repo_root/docker-compose.integration.yml" --env-file "$compose_env_file"
  --profile integration --project-name "$compose_project")
"${compose[@]}" config >/dev/null
"${compose[@]}" up -d postgres redis
bash "$repo_root/scripts/wait-for-services.sh" --compose-env-file "$compose_env_file" \
  --project-name "$compose_project" --compose-file "$repo_root/docker-compose.integration.yml" \
  --profile integration
bash "$repo_root/scripts/ci/create-test-database.sh" "$test_env_file" "$compose_env_file"
# shellcheck disable=SC1090
source "$test_env_file"
export APP_ENV=development DEV_ACTOR_ID=00000000-0000-4000-8000-000000000001
export SECRET_KEY=integration-test-secret BLOB_ROOT=/var/lib/rag-eval/blobs
export DATABASE_URL REDIS_URL=redis://127.0.0.1:6379/0 TEST_DATABASE_URL="$DATABASE_URL"
uv lock --directory "$repo_root/apps/api" --check
uv sync --directory "$repo_root/apps/api" --locked
uv run --directory "$repo_root/apps/api" alembic upgrade head
uv run --directory "$repo_root/apps/api" alembic check
uv run --directory "$repo_root/apps/api" pytest -m integration -q
