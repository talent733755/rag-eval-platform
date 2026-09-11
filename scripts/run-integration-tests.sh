#!/usr/bin/env bash

set -Eeuo pipefail

readonly script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd -P)"
readonly compose_file="${repo_root}/docker-compose.yml"
readonly integration_compose_file="${repo_root}/docker-compose.integration.yml"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' 'Docker Compose is required for integration tests; refusing to skip' >&2
  exit 2
fi

compose_env_file="$(mktemp "${repo_root}/.ci-integration-env.XXXXXX")"
compose_project="rag-eval-integration-${USER:-local}-$$"
database_name="rag_eval_test_$$_${RANDOM}"
database_created=false

base_env_file="${repo_root}/.env.example"
[[ -f "${repo_root}/.env" ]] && base_env_file="${repo_root}/.env"
compose=(docker compose --file "$compose_file" --file "$integration_compose_file" \
  --env-file "$compose_env_file" --profile integration --project-name "$compose_project")

cleanup() {
  local status=$?
  set +e
  if [[ "$database_created" == true ]]; then
    docker compose --file "$compose_file" --file "$integration_compose_file" \
      --env-file "$compose_env_file" --profile integration \
      --project-name "$compose_project" exec -T \
      -e "INTEGRATION_DB_NAME=$database_name" postgres sh -ec \
      'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c \
       "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '\''$INTEGRATION_DB_NAME'\'';" >/dev/null
       psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c \
       "DROP DATABASE IF EXISTS \"$INTEGRATION_DB_NAME\";" >/dev/null' >/dev/null 2>&1
  fi
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1
  rm -f -- "$compose_env_file"
  exit "$status"
}
trap cleanup EXIT INT TERM

cp "$base_env_file" "$compose_env_file"
cat >>"$compose_env_file" <<EOF
APP_ENV=development
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000
SECRET_KEY=integration-test-secret
BLOB_ROOT=/var/lib/rag-eval/blobs
POSTGRES_DB=postgres
POSTGRES_USER=rag_eval_test
POSTGRES_PASSWORD=integration-test-password
COMPOSE_DATABASE_URL=postgresql+asyncpg://rag_eval_test:integration-test-password@postgres:5432/$database_name
COMPOSE_REDIS_URL=redis://redis:6379/0
EOF

"${compose[@]}" config >/dev/null
"${compose[@]}" up -d postgres redis
bash "$repo_root/scripts/wait-for-services.sh" \
  --compose-env-file "$compose_env_file" --project-name "$compose_project" \
  --compose-file "$integration_compose_file" --profile integration

"${compose[@]}" exec -T -e "INTEGRATION_DB_NAME=$database_name" postgres sh -ec \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c \
   "CREATE DATABASE \"$INTEGRATION_DB_NAME\";"' >/dev/null
database_created=true

export APP_ENV=development
export SECRET_KEY=integration-test-secret
export BLOB_ROOT=/var/lib/rag-eval/blobs
export DATABASE_URL=postgresql+asyncpg://rag_eval_test:integration-test-password@127.0.0.1:5432/$database_name
export REDIS_URL=redis://127.0.0.1:6379/0
export TEST_DATABASE_URL="$DATABASE_URL"

uv run --directory "$repo_root/apps/api" alembic upgrade head
uv run --directory "$repo_root/apps/api" alembic check
uv run --directory "$repo_root/apps/api" pytest -m integration -q
