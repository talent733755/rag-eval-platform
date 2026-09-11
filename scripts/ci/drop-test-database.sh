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

compose=(env -i "PATH=$PATH" COMPOSE_DISABLE_ENV_FILE=1 docker compose --project-directory "$repo_root" --file "$repo_root/docker-compose.yml"
	--file "$repo_root/docker-compose.integration.yml" --env-file "$compose_env_file"
	--profile integration --project-name "$compose_project")
if ! "${compose[@]}" exec -T postgres sh -ec \
	'dropdb --if-exists --maintenance-db=postgres -U "$POSTGRES_USER" "$1"' \
	sh "$TEST_DATABASE_NAME" >/dev/null 2>&1; then
	printf 'failed to drop integration database %s\n' "$TEST_DATABASE_NAME" >&2
	exit 1
fi
