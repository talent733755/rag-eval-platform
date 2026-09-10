#!/usr/bin/env bash

set -Eeuo pipefail

readonly script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd -P)"
readonly output_file="${repo_root}/apps/web/src/lib/api/generated.ts"
readonly temp_dir="$(mktemp -d)"

cleanup() {
  rm -rf "${temp_dir}"
}
trap cleanup EXIT

uv run --directory "${repo_root}/apps/api" python -c '
import json

from rag_eval_api.main import create_app

print(json.dumps(create_app().openapi(), indent=2, sort_keys=True))
' >"${temp_dir}/openapi.json"

corepack pnpm --dir "${repo_root}/apps/web" exec openapi-typescript \
  "${temp_dir}/openapi.json" \
  -o "${output_file}"
