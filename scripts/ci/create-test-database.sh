#!/usr/bin/env bash

set -Eeuo pipefail

if (($# != 2)); then
	printf 'usage: %s TEST_ENV_FILE COMPOSE_ENV_FILE\n' "$0" >&2
	exit 2
fi

readonly test_env_file="$1"
readonly compose_env_file="$2"
readonly repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"

env_value() {
	awk -F= -v key="$1" '$1 == key { value = substr($0, index($0, "=") + 1) } END { print value }' "$compose_env_file"
}

readonly compose_project="$(env_value COMPOSE_PROJECT_NAME)"
run_id="${GITHUB_RUN_ID:-local-$(date +%s)-$$}"
run_id="$(printf '%s' "$run_id" | tr -c '[:alnum:]' '_' | tr '[:upper:]' '[:lower:]')"
readonly database_name="rag_eval_test_${run_id:0:45}"

[[ "$compose_project" =~ ^[a-z0-9][a-z0-9_-]{0,62}$ ]] || {
	printf 'Compose project name is not safe\n' >&2
	exit 2
}
[[ "$database_name" =~ ^[a-zA-Z][a-zA-Z0-9_]{0,62}$ ]] || {
	printf 'database name is not a safe PostgreSQL identifier\n' >&2
	exit 2
}

compose=(env -i "PATH=$PATH" COMPOSE_DISABLE_ENV_FILE=1 docker compose --project-directory "$repo_root" --file "$repo_root/docker-compose.yml"
	--file "$repo_root/docker-compose.integration.yml" --env-file "$compose_env_file"
	--profile integration --project-name "$compose_project")

postgres_user="$(env_value POSTGRES_USER)"
postgres_password="$(env_value POSTGRES_PASSWORD)"
[[ -n "$postgres_user" && -n "$postgres_password" ]] || {
	printf 'Compose environment must define PostgreSQL credentials\n' >&2
	exit 2
}

postgres_host_port="$("${compose[@]}" port postgres 5432 | awk -F: 'NF { print $NF; exit }')"
[[ "$postgres_host_port" =~ ^[0-9]+$ ]] || {
	printf 'Compose did not expose a valid PostgreSQL host port\n' >&2
	exit 2
}

"${compose[@]}" exec -T postgres sh -ec \
	'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c \
	"CREATE DATABASE \"$1\";"' sh "$database_name" >/dev/null

database_url="postgresql+asyncpg://$postgres_user:$postgres_password@127.0.0.1:$postgres_host_port/$database_name"
umask 077
{
	printf 'DATABASE_URL=%s\n' "$database_url"
	printf 'TEST_DATABASE_NAME=%s\n' "$database_name"
	printf 'TEST_DATABASE_HOST=127.0.0.1\n'
	printf 'TEST_DATABASE_PORT=%s\n' "$postgres_host_port"
} >"$test_env_file"
