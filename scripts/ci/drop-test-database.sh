#!/usr/bin/env bash

set -Eeuo pipefail

if (($# != 3)); then
	printf 'usage: %s TEST_ENV_FILE COMPOSE_ENV_FILE COMPOSE_PROJECT\n' "$0" >&2
	exit 2
fi

readonly test_env_file="$1"
readonly compose_env_file="$2"
readonly compose_project="$3"
readonly repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"

[[ -f "$test_env_file" && -f "$compose_env_file" ]] || exit 0
# shellcheck disable=SC1090
source "$test_env_file"
[[ "${TEST_DATABASE_NAME:-}" =~ ^[a-zA-Z][a-zA-Z0-9_]{0,62}$ ]] || exit 0

compose=(docker compose --project-directory "$repo_root" --file "$repo_root/docker-compose.yml"
	--file "$repo_root/docker-compose.integration.yml" --env-file "$compose_env_file"
	--profile integration --project-name "$compose_project")
"${compose[@]}" exec -T postgres sh -ec \
	'psql -v ON_ERROR_STOP=1 -v dbname="$1" -U "$POSTGRES_USER" -d postgres -c \
	"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :'"'"'dbname'"'"';" \
	psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c \
	"DROP DATABASE IF EXISTS \"$1\";"' sh "$TEST_DATABASE_NAME" >/dev/null 2>&1 || true
