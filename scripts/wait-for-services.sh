#!/usr/bin/env bash

set -Eeuo pipefail

readonly deadline=$((SECONDS + 30))
readonly probe_timeout_seconds=2
postgres_ready=false
redis_ready=false

run_probe() {
  local requested_timeout_seconds="$1"
  shift

  local remaining_seconds=$((deadline - SECONDS))
  (( remaining_seconds > 0 )) || return 124

  local timeout_seconds="$requested_timeout_seconds"
  (( remaining_seconds < timeout_seconds )) && timeout_seconds="$remaining_seconds"

  "$@" &
  local probe_pid=$!
  local watchdog_ticks=$((timeout_seconds * 10))

  for ((tick = 0; tick < watchdog_ticks; tick++)); do
    if ! kill -0 "$probe_pid" 2>/dev/null; then
      if wait "$probe_pid"; then
        return 0
      fi
      return 1
    fi
    sleep 0.1
  done

  if kill -0 "$probe_pid" 2>/dev/null; then
    kill "$probe_pid" 2>/dev/null || true
    sleep 0.1
    kill -KILL "$probe_pid" 2>/dev/null || true
    wait "$probe_pid" 2>/dev/null || true
    return 124
  fi

  if wait "$probe_pid"; then
    return 0
  fi
  return 1
}

postgres_probe() {
  docker compose exec -T postgres sh -c \
    'pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"' \
    >/dev/null 2>&1
}

postgres_is_ready() {
  run_probe "$probe_timeout_seconds" postgres_probe
}

redis_probe() {
  docker compose exec -T redis redis-cli ping 2>/dev/null | grep -qx 'PONG'
}

redis_is_ready() {
  run_probe "$probe_timeout_seconds" redis_probe
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
