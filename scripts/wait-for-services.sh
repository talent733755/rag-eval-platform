#!/usr/bin/env bash

set -Eeuo pipefail

readonly deadline=$((SECONDS + 30))
postgres_ready=false
redis_ready=false

postgres_is_ready() {
  docker compose exec -T postgres sh -c \
    'pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"' \
    >/dev/null 2>&1
}

redis_is_ready() {
  docker compose exec -T redis redis-cli ping 2>/dev/null | grep -qx 'PONG'
}

while (( SECONDS < deadline )); do
  if [[ "$postgres_ready" != true ]] && postgres_is_ready; then
    postgres_ready=true
  fi

  if [[ "$redis_ready" != true ]] && redis_is_ready; then
    redis_ready=true
  fi

  if [[ "$postgres_ready" == true && "$redis_ready" == true ]]; then
    exit 0
  fi

  remaining=$((deadline - SECONDS))
  if (( remaining > 0 )); then
    sleep 1
  fi
done

unavailable=()
[[ "$postgres_ready" == true ]] || unavailable+=(postgres)
[[ "$redis_ready" == true ]] || unavailable+=(redis)

printf 'Unavailable service(s) after 30 seconds: %s\n' "${unavailable[*]}" >&2
exit 1
