SHELL := /bin/bash

.PHONY: install lint typecheck test test-integration build infra-up infra-down

install:
	corepack pnpm install --frozen-lockfile
	uv sync --directory apps/api --locked

lint:
	corepack pnpm lint && uv run --directory apps/api ruff check . && uv run --directory apps/api ruff format --check .

typecheck:
	corepack pnpm typecheck && uv run --directory apps/api mypy src

test:
	corepack pnpm test && uv run --directory apps/api pytest -m "not integration" -q

test-integration:
	bash scripts/run-integration-tests.sh

build:
	corepack pnpm build

infra-up:
	docker compose up -d postgres redis

infra-down:
	docker compose down
