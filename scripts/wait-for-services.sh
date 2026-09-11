#!/usr/bin/env bash

set -Eeuo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  printf 'wait-for-services.sh requires python3 for a monotonic wall-clock deadline\n' >&2
  exit 2
fi

readonly script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd -P)"
readonly compose_file="${repo_root}/docker-compose.yml"
readonly probe_timeout_ms=2000
readonly cleanup_reserve_ms=250

compose_env_file=""
compose_project_name=""
while (($# > 0)); do
  case "$1" in
    --compose-env-file)
      [[ $# -ge 2 ]] || { printf '%s\n' '--compose-env-file requires a path' >&2; exit 2; }
      compose_env_file="$2"
      shift 2
      ;;
    --project-name)
      [[ $# -ge 2 ]] || { printf '%s\n' '--project-name requires a value' >&2; exit 2; }
      compose_project_name="$2"
      shift 2
      ;;
    *)
      printf 'unknown option: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

compose_args=(--project-directory "$repo_root" --file "$compose_file")
[[ -n "$compose_env_file" ]] && compose_args+=(--env-file "$compose_env_file")
[[ -n "$compose_project_name" ]] && compose_args+=(--project-name "$compose_project_name")

clock_ms() {
  python3 -c 'import time; print(time.monotonic_ns() // 1_000_000)'
}

readonly start_ms="$(clock_ms)"
readonly deadline_ms=$((start_ms + 30000))
postgres_ready=false
redis_ready=false

before_deadline() {
  (( $(clock_ms) < deadline_ms - cleanup_reserve_ms ))
}

kill_process_tree() {
  local parent_pid="$1"
  local child_pid

  if command -v pgrep >/dev/null 2>&1; then
    while read -r child_pid; do
      [[ -n "$child_pid" ]] || continue
      kill_process_tree "$child_pid"
    done < <(pgrep -P "$parent_pid" 2>/dev/null || true)
  fi

  kill -KILL "$parent_pid" 2>/dev/null || true
}

stop_probe() {
  local probe_pid="$1"

  kill_process_tree "$probe_pid"
  wait "$probe_pid" 2>/dev/null || true
}

run_probe() {
  local now_ms remaining_ms timeout_ms probe_deadline_ms probe_pid

  now_ms="$(clock_ms)"
  remaining_ms=$((deadline_ms - now_ms - cleanup_reserve_ms))
  (( remaining_ms > 0 )) || return 124

  timeout_ms="$probe_timeout_ms"
  (( remaining_ms < timeout_ms )) && timeout_ms="$remaining_ms"
  probe_deadline_ms=$((now_ms + timeout_ms))

  "$@" &
  probe_pid=$!

  while kill -0 "$probe_pid" 2>/dev/null; do
    now_ms="$(clock_ms)"
    if (( now_ms >= probe_deadline_ms || now_ms >= deadline_ms - cleanup_reserve_ms )); then
      stop_probe "$probe_pid"
      return 124
    fi
    sleep 0.1
  done

  if wait "$probe_pid"; then
    return 0
  fi
  return 1
}

postgres_probe() {
  exec docker compose "${compose_args[@]}" exec -T postgres sh -c \
    'pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"' \
    >/dev/null 2>&1
}

postgres_is_ready() {
  run_probe postgres_probe
}

redis_probe() {
  exec docker compose "${compose_args[@]}" exec -T redis sh -c \
    'test "$(redis-cli ping)" = PONG' \
    >/dev/null 2>&1
}

redis_is_ready() {
  run_probe redis_probe
}

while before_deadline; do
  if [[ "$postgres_ready" != true ]] && postgres_is_ready; then
    postgres_ready=true
  fi

  if [[ "$redis_ready" != true ]] && redis_is_ready; then
    redis_ready=true
  fi

  if [[ "$postgres_ready" == true && "$redis_ready" == true ]]; then
    exit 0
  fi

  if before_deadline; then
    sleep 0.1
  fi
done

unavailable=()
[[ "$postgres_ready" == true ]] || unavailable+=(postgres)
[[ "$redis_ready" == true ]] || unavailable+=(redis)

printf 'Unavailable service(s) after 30 seconds: %s\n' "${unavailable[*]}" >&2
exit 1
