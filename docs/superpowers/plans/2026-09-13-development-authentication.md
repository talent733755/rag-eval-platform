# Development Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local development Web application load real tenant-scoped projects through an explicit development actor while keeping production authentication fail-closed.

**Architecture:** The API will resolve `DEV_ACTOR_ID` only when `APP_ENV=development`; it will derive the actor's organization from exactly one database membership and never trust request headers or client payloads. A repeatable seed script will create one development organization, project, and admin membership. Production and development without an explicitly configured actor will continue returning the existing 501 boundary response.

**Tech Stack:** FastAPI dependency injection, Pydantic Settings, SQLAlchemy async sessions, PostgreSQL/SQLite tests, pytest, Docker Compose, Markdown documentation.

---

### Task 1: Add authentication boundary regression coverage

**Files:**
- Create: `apps/api/tests/test_authentication.py`
- Modify: `apps/api/tests/test_config.py`

- [x] **Step 1: Write failing tests.** Cover development actor resolution from a membership, missing actor configuration, ambiguous multi-organization membership, production fail-closed behavior, and empty `DEV_ACTOR_ID` normalization.

```python
async def test_development_actor_is_resolved_from_unique_membership(...):
    response = await client.get("/api/projects")
    assert response.status_code == 200

async def test_development_actor_requires_a_membership(...):
    response = await client.get("/api/projects")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "development_actor_not_provisioned"

async def test_production_auth_still_fails_closed(...):
    response = await client.get("/api/projects")
    assert response.status_code == 501

def test_empty_dev_actor_id_is_treated_as_unset():
    assert Settings.model_validate({"DEV_ACTOR_ID": ""}).dev_actor_id is None
```

- [x] **Step 2: Run the focused tests to verify they fail.**

Run: `uv run --directory apps/api pytest -q tests/test_authentication.py tests/test_config.py -k 'actor or production_auth'`

Expected: FAIL because the request dependency always raises 501 and empty actor IDs are not normalized.

### Task 2: Implement safe development actor resolution and seed data

**Files:**
- Modify: `apps/api/src/rag_eval_api/auth/context.py`
- Modify: `apps/api/src/rag_eval_api/config.py`
- Modify: `docker-compose.yml`
- Create: `scripts/seed-dev-data.py`
- Modify: `.env.example`

- [x] **Step 1: Implement the minimal boundary.** Inject the existing database session into `get_current_actor`; return `RequestActor` only for development with a configured actor and exactly one membership organization. Return a structured 503 when the actor is missing from the database or belongs to multiple organizations. Keep production and all non-development environments on the existing 501 response.

- [x] **Step 2: Add an idempotent development seed script.** Guard it with `APP_ENV=development`, use the configured `DEV_ACTOR_ID`, create fixed UUID organization/project/membership records if absent, update only those fixed development records, and never create credentials or sample business data.

- [x] **Step 3: Propagate the explicit actor into Compose.** Add `DEV_ACTOR_ID` to `.env.example` and pass it to the API container. Do not add a development actor to production configuration or accept an actor from HTTP headers.

- [x] **Step 4: Run focused tests and seed against the running local database.**

Run:

```bash
uv run --directory apps/api pytest -q tests/test_authentication.py tests/test_config.py
uv run --project apps/api python scripts/seed-dev-data.py
curl -i http://127.0.0.1:8003/api/projects
```

Expected: focused tests pass, the seed is idempotent, and `/api/projects` returns HTTP 200 with the seeded project when Compose uses `APP_ENV=development` and the configured actor.

### Task 3: Document local authentication and verify the repository

**Files:**
- Modify: `README.md`
- Modify: `docs/security/authentication.md`
- Modify: `docs/operations/runbook.md`
- Modify: `docs/HANDOFF.md`

- [x] **Step 1: Document the local startup sequence.** Explain copying `.env.example`, running migrations, running `scripts/seed-dev-data.py`, and accessing Web on port 3003/API on port 8003. State that the actor is development-only and that production still requires OIDC/JWT.

- [x] **Step 2: Run repository quality gates.**

Run: `git diff --check && make lint && make typecheck && make test && make build && DATABASE_URL=postgresql+asyncpg://rag_eval:change-me@localhost:5432/rag_eval uv run --directory apps/api alembic check`

Expected: all commands exit 0; existing production 501 regression remains green.

- [x] **Step 3: Commit in Chinese and push the branch.**

```bash
git add apps/api/src/rag_eval_api/auth/context.py apps/api/src/rag_eval_api/config.py apps/api/tests/test_authentication.py apps/api/tests/test_config.py docker-compose.yml .env.example scripts/seed-dev-data.py README.md docs/security/authentication.md docs/operations/runbook.md docs/HANDOFF.md docs/superpowers/plans/2026-09-13-development-authentication.md
git commit -m "feat: 接入开发环境身份与项目种子数据"
git push origin codex/mvp-foundation-admin-shell
```
