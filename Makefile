.PHONY: install lint typecheck test build infra-up infra-down

install:
	corepack pnpm install --frozen-lockfile
	uv sync --directory apps/api --locked

lint:
	corepack pnpm lint && uv run --directory apps/api ruff check .

typecheck:
	corepack pnpm typecheck && uv run --directory apps/api mypy src

test:
	corepack pnpm test && uv run --directory apps/api pytest -q

build:
	corepack pnpm build

infra-up:
	docker compose up -d postgres redis

infra-down:
	docker compose down
