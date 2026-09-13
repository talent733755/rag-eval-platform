#!/usr/bin/env bash

set -Eeuo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'check-worker-ready.sh requires python3' >&2
  exit 2
fi

readonly default_path="/run/rag-eval/worker-ready"
readonly default_max_age_seconds=120
ready_path="${WORKER_READINESS_FILE:-$default_path}"
max_age_seconds="${WORKER_READINESS_MAX_AGE_SECONDS:-$default_max_age_seconds}"

while (($# > 0)); do
  case "$1" in
    --path)
      [[ $# -ge 2 ]] || { printf '%s\n' '--path requires a value' >&2; exit 2; }
      ready_path="$2"
      shift 2
      ;;
    --max-age-seconds)
      [[ $# -ge 2 ]] || { printf '%s\n' '--max-age-seconds requires a value' >&2; exit 2; }
      max_age_seconds="$2"
      shift 2
      ;;
    *)
      printf 'unknown option: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

[[ "$ready_path" = /* ]] || { printf '%s\n' 'readiness path must be absolute' >&2; exit 2; }
[[ "$max_age_seconds" =~ ^[0-9]+$ ]] || {
  printf '%s\n' 'max age must be a non-negative integer' >&2
  exit 2
}

python3 - "$ready_path" "$max_age_seconds" <<'PY'
import os
import sys
import time

path = sys.argv[1]
max_age = int(sys.argv[2])
try:
    stat = os.stat(path)
except FileNotFoundError:
    raise SystemExit(1)
if not os.path.isfile(path):
    raise SystemExit(1)
age = time.time() - stat.st_mtime
raise SystemExit(0 if 0 <= age <= max_age else 1)
PY
