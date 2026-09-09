# RAG Eval Platform MVP Foundation and Admin Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the production-grade repository foundation, local development environment, project/member permission model, and responsive admin shell required before implementing the RAG evaluation business modules.

**Architecture:** Use a small monorepo with a Next.js/TypeScript web application and a FastAPI/Python API. PostgreSQL stores organization, project, membership, and audit data; Redis is reserved for the asynchronous job layer that will be added in the next plan. The API owns the public contract and emits OpenAPI; the web application consumes the generated client and renders the approved admin information architecture using shared design tokens.

**Tech Stack:** pnpm workspace, Next.js, TypeScript, Tailwind CSS, accessible headless UI primitives, Vitest, Playwright, Python 3.12+, FastAPI, Pydantic, SQLAlchemy async, Alembic, PostgreSQL, Redis, Docker Compose, pytest, Ruff, mypy, GitHub Actions.

---

## Scope and decomposition

The approved PRD contains several independently testable subsystems. This plan intentionally covers only the foundation and admin shell:

1. Repository quality gates and local infrastructure.
2. API bootstrap and database-backed organization/project/member model.
3. RBAC enforcement and audit events for administrative actions.
4. Web application shell, navigation, project context, and permission-aware routes.

The following are separate follow-up plans and must not be pulled into this one: document ingestion and parsing, candidate evaluation-set generation/review, Adapter protocol execution, experiment jobs, metrics calculation, Trace storage/diagnostics, and report export.

## File map

### Root and CI

- Create: `package.json` — workspace scripts and common quality commands.
- Create: `pnpm-workspace.yaml` — workspace package discovery.
- Create: `Makefile` — stable contributor commands that do not depend on shell aliases.
- Modify: `.gitignore` — include generated web/API artifacts and local secrets.
- Create: `.env.example` — documented non-secret local configuration.
- Create: `.github/workflows/ci.yml` — lint, type-check, unit tests, build, and integration checks.
- Modify: `README.md` — local setup, service URLs, quality commands, and project status.

### API

- Create: `apps/api/pyproject.toml` — Python dependencies and Ruff/mypy/pytest configuration.
- Create: `apps/api/src/rag_eval_api/main.py` — FastAPI application factory and lifespan.
- Create: `apps/api/src/rag_eval_api/config.py` — validated environment settings.
- Create: `apps/api/src/rag_eval_api/db.py` — async engine, session factory, and transaction helper.
- Create: `apps/api/src/rag_eval_api/models/base.py` — declarative base and common timestamp/UUID mixins.
- Create: `apps/api/src/rag_eval_api/models/organization.py` — organization entity.
- Create: `apps/api/src/rag_eval_api/models/project.py` — project entity.
- Create: `apps/api/src/rag_eval_api/models/membership.py` — membership and role enum.
- Create: `apps/api/src/rag_eval_api/models/audit_event.py` — immutable audit event entity.
- Create: `apps/api/src/rag_eval_api/models/__init__.py` — model registration for migrations.
- Create: `apps/api/alembic.ini` — migration configuration.
- Create: `apps/api/alembic/env.py` — async migration runner.
- Create: `apps/api/alembic/versions/0001_foundation.py` — initial schema migration.
- Create: `apps/api/src/rag_eval_api/auth/context.py` — request actor and project context dependencies.
- Create: `apps/api/src/rag_eval_api/auth/rbac.py` — role checks and permission constants.
- Create: `apps/api/src/rag_eval_api/schemas/common.py` — shared API response/error schemas.
- Create: `apps/api/src/rag_eval_api/schemas/projects.py` — project/member request and response models.
- Create: `apps/api/src/rag_eval_api/routes/health.py` — liveness/readiness endpoints.
- Create: `apps/api/src/rag_eval_api/routes/projects.py` — project and member endpoints.
- Create: `apps/api/src/rag_eval_api/services/audit.py` — audit event writer.
- Create: `apps/api/tests/conftest.py` — test database and authenticated actor fixtures.
- Create: `apps/api/tests/test_health.py` — health behavior.
- Create: `apps/api/tests/test_projects.py` — project and member behavior.
- Create: `apps/api/tests/test_rbac.py` — permission matrix behavior.

### Web

- Create: `apps/web/package.json` — web dependencies and scripts.
- Create: `apps/web/next.config.ts` — strict Next configuration.
- Create: `apps/web/tsconfig.json` — strict TypeScript configuration.
- Create: `apps/web/tailwind.config.ts` — design tokens and responsive breakpoints.
- Create: `apps/web/src/app/layout.tsx` — global document and providers.
- Create: `apps/web/src/app/(app)/layout.tsx` — authenticated/admin shell layout.
- Create: `apps/web/src/app/(app)/page.tsx` — Dashboard route placeholder using real shell components.
- Create: `apps/web/src/app/(app)/settings/members/page.tsx` — member management route.
- Create: `apps/web/src/components/layout/app-shell.tsx` — sidebar/topbar composition.
- Create: `apps/web/src/components/layout/sidebar-nav.tsx` — grouped navigation and active state.
- Create: `apps/web/src/components/layout/project-switcher.tsx` — current organization/project context.
- Create: `apps/web/src/components/layout/user-menu.tsx` — user actions placeholder.
- Create: `apps/web/src/components/ui/status-badge.tsx` — accessible status component.
- Create: `apps/web/src/components/ui/data-card.tsx` — KPI/card primitive.
- Create: `apps/web/src/lib/api/client.ts` — typed API client configuration.
- Create: `apps/web/src/lib/auth/permissions.ts` — frontend permission visibility map.
- Create: `apps/web/src/lib/navigation.ts` — canonical menu tree.
- Create: `apps/web/src/lib/design-tokens.ts` — token names shared with Tailwind.
- Create: `apps/web/tests/navigation.test.tsx` — menu visibility and active state tests.
- Create: `apps/web/tests/status-badge.test.tsx` — status/accessibility tests.
- Create: `apps/web/e2e/admin-shell.spec.ts` — browser smoke test.

### Local infrastructure

- Create: `docker-compose.yml` — PostgreSQL, Redis, API, and web development services.
- Create: `docker/api.Dockerfile` — reproducible API image.
- Create: `docker/web.Dockerfile` — reproducible web image.
- Create: `scripts/wait-for-services.sh` — readiness check used by local integration tests and CI.

## Implementation tasks

### Task 1: Establish workspace commands and quality gates

**Files:** `package.json`, `pnpm-workspace.yaml`, `Makefile`, `.gitignore`, `.env.example`, `README.md`

- [ ] **Step 1: Add root commands before implementation**

Add these commands to the root `Makefile` and keep them executable without global project-specific tools:

```make
install:
	corepack pnpm install

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
```

- [ ] **Step 2: Run the command discovery check**

Run: `make -n lint typecheck test build`

Expected: every command prints without a missing target or malformed recipe.

- [ ] **Step 3: Document setup and quality gates**

Update `README.md` with Node/pnpm, Python/uv, Docker prerequisites; `cp .env.example .env`; `make infra-up`; API/web URLs; and the four required quality commands. State that generated secrets and `.env` are never committed.

- [ ] **Step 4: Commit the repository command layer**

```bash
git add package.json pnpm-workspace.yaml Makefile .gitignore .env.example README.md
git commit -m "chore: establish project workspace and quality commands"
```

### Task 2: Add reproducible local infrastructure

**Files:** `docker-compose.yml`, `docker/api.Dockerfile`, `docker/web.Dockerfile`, `scripts/wait-for-services.sh`

- [ ] **Step 1: Define local services**

Use PostgreSQL with a named volume and Redis with a named volume. Expose PostgreSQL only on `127.0.0.1:5432`, Redis only on `127.0.0.1:6379`, API on `127.0.0.1:8000`, and web on `127.0.0.1:3000`. Add healthchecks for PostgreSQL (`pg_isready`) and Redis (`redis-cli ping`). Do not put credentials directly in the compose file; read them from `.env`.

- [ ] **Step 2: Add API and web image definitions**

The API image must install the locked Python dependencies and run `uvicorn rag_eval_api.main:app --host 0.0.0.0 --port 8000`. The web image must install the locked pnpm dependencies and run the development command for local work. Production image optimization belongs to a later deployment plan.

- [ ] **Step 3: Add readiness script**

`scripts/wait-for-services.sh` must poll PostgreSQL and Redis with a 30-second deadline and exit non-zero with the service name when either dependency is unavailable. It must not use an unbounded sleep loop.

- [ ] **Step 4: Verify infrastructure**

Run:

```bash
make infra-up
docker compose ps
bash scripts/wait-for-services.sh
```

Expected: PostgreSQL and Redis report healthy, the readiness script exits 0, and `docker compose down` stops services without deleting named volumes.

- [ ] **Step 5: Commit infrastructure**

```bash
git add docker-compose.yml docker scripts/wait-for-services.sh
git commit -m "chore: add local postgres and redis infrastructure"
```

### Task 3: Bootstrap the FastAPI service

**Files:** `apps/api/pyproject.toml`, `apps/api/src/rag_eval_api/{__init__.py,main.py,config.py,db.py}`, `apps/api/tests/conftest.py`, `apps/api/tests/test_health.py`

- [ ] **Step 1: Write health tests first**

Create tests that assert:

```python
def test_liveness_returns_ok(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_database_dependency(client, db_session):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["dependencies"]["database"] == "ok"
```

- [ ] **Step 2: Run the tests and verify the expected failure**

Run: `uv run --directory apps/api pytest tests/test_health.py -q`

Expected: FAIL because the application and health routes do not exist yet.

- [ ] **Step 3: Implement configuration and application factory**

Use Pydantic settings for `DATABASE_URL`, `REDIS_URL`, `APP_ENV`, `CORS_ORIGINS`, and `LOG_LEVEL`. Reject missing production secrets when `APP_ENV=production`; allow explicit local defaults only for `APP_ENV=development`. Configure structured request logging and return JSON errors from the API boundary.

- [ ] **Step 4: Implement health routes**

`GET /health/live` must not contact dependencies. `GET /health/ready` must execute a lightweight database query and Redis ping, returning HTTP 503 with dependency details when either check fails. Do not expose credentials or connection strings in errors.

- [ ] **Step 5: Run the tests and static checks**

Run: `uv run --directory apps/api pytest tests/test_health.py -q && uv run --directory apps/api ruff check . && uv run --directory apps/api mypy src`

Expected: tests pass; Ruff and mypy exit 0.

- [ ] **Step 6: Commit the API bootstrap**

```bash
git add apps/api
git commit -m "feat: bootstrap api service with health checks"
```

### Task 4: Add the foundation database schema and migrations

**Files:** `apps/api/src/rag_eval_api/models/{base.py,organization.py,project.py,membership.py,audit_event.py,__init__.py}`, `apps/api/alembic.ini`, `apps/api/alembic/env.py`, `apps/api/alembic/versions/0001_foundation.py`, `apps/api/tests/test_projects.py`

- [ ] **Step 1: Write model behavior tests**

The tests must create one organization, two projects, and memberships for all three roles, then assert:

```python
def test_project_membership_is_unique(db):
    add_membership(db, project_id=project.id, user_id=user.id, role="editor")
    add_membership(db, project_id=project.id, user_id=user.id, role="viewer")
    with pytest.raises(IntegrityError):
        db.commit()


def test_audit_event_is_immutable(db):
    event = record_audit(db, action="project.created", resource_id=project.id)
    assert event.actor_id is not None
    assert event.created_at is not None
```

- [ ] **Step 2: Implement entities and constraints**

Use UUID primary keys and UTC timestamps. Define:

- `organizations`: `id`, `name`, `slug`, `created_at`, `updated_at`;
- `projects`: `id`, `organization_id`, `name`, `slug`, `description`, `archived_at`, timestamps;
- `memberships`: `id`, `organization_id`, `project_id`, `user_id`, `role`, timestamps, unique `(project_id, user_id)`;
- `audit_events`: `id`, `organization_id`, `project_id`, `actor_id`, `action`, `resource_type`, `resource_id`, `metadata_json`, `created_at`.

Use database foreign keys and indexes for organization/project lookup, membership lookup, and audit time ordering. The `role` values are exactly `admin`, `editor`, and `viewer`.

- [ ] **Step 3: Create and apply the migration**

Run:

```bash
uv run --directory apps/api alembic upgrade head
uv run --directory apps/api alembic current
```

Expected: the database reports revision `0001_foundation` and all four tables exist.

- [ ] **Step 4: Run database tests**

Run: `uv run --directory apps/api pytest tests/test_projects.py -q`

Expected: model constraints and audit creation tests pass.

- [ ] **Step 5: Commit the schema**

```bash
git add apps/api/src/rag_eval_api/models apps/api/alembic apps/api/tests/test_projects.py
git commit -m "feat: add organization project membership schema"
```

### Task 5: Implement API project context and RBAC

**Files:** `apps/api/src/rag_eval_api/auth/{context.py,rbac.py}`, `apps/api/src/rag_eval_api/schemas/{common.py,projects.py}`, `apps/api/src/rag_eval_api/routes/projects.py`, `apps/api/src/rag_eval_api/services/audit.py`, `apps/api/tests/test_rbac.py`

- [ ] **Step 1: Write permission matrix tests**

Test every administrative route with each role. The minimum assertions are:

```python
@pytest.mark.parametrize("role,expected", [
    ("admin", 200),
    ("editor", 403),
    ("viewer", 403),
])
def test_only_admin_can_manage_members(client, actor, role, expected):
    actor.membership.role = role
    response = client.post(
        f"/api/projects/{project.id}/members",
        json={"email": "new@example.com", "role": "viewer"},
    )
    assert response.status_code == expected


def test_viewer_can_read_project(client, viewer):
    response = client.get(f"/api/projects/{project.id}")
    assert response.status_code == 200
```

- [ ] **Step 2: Implement request actor and project context**

For this foundation plan, use a deterministic development actor injected by the test fixture and a clearly isolated production authentication boundary that raises `501 Not Implemented` until authentication is added. Never trust a project ID from the URL without checking membership in that project.

- [ ] **Step 3: Implement role checks**

Define `require_project_member`, `require_project_editor`, and `require_project_admin` dependencies. Return a consistent error body:

```json
{
  "error": {
    "code": "permission_denied",
    "message": "You do not have permission to perform this action."
  }
}
```

Do not reveal whether a resource exists when the actor lacks access.

- [ ] **Step 4: Implement project and member endpoints**

Add:

- `GET /api/projects` — projects visible to the actor;
- `POST /api/projects` — admin-only organization project creation;
- `GET /api/projects/{project_id}` — project detail for members;
- `GET /api/projects/{project_id}/members` — member list for members;
- `POST /api/projects/{project_id}/members` — admin-only invite placeholder;
- `PATCH /api/projects/{project_id}/members/{membership_id}` — admin-only role change;
- `DELETE /api/projects/{project_id}/members/{membership_id}` — admin-only removal.

Each mutation writes an audit event in the same database transaction. Email invitation delivery is outside this plan; the endpoint records a pending invitation object only after validating email and role.

- [ ] **Step 5: Run API tests**

Run: `uv run --directory apps/api pytest tests/test_projects.py tests/test_rbac.py -q`

Expected: project isolation, role permissions, consistent errors, and audit events pass.

- [ ] **Step 6: Commit RBAC and routes**

```bash
git add apps/api/src/rag_eval_api/auth apps/api/src/rag_eval_api/routes apps/api/src/rag_eval_api/schemas apps/api/src/rag_eval_api/services apps/api/tests
git commit -m "feat: add project api and role based access control"
```

### Task 6: Create the web application shell and design tokens

**Files:** `apps/web/package.json`, `apps/web/next.config.ts`, `apps/web/tsconfig.json`, `apps/web/tailwind.config.ts`, `apps/web/src/app/layout.tsx`, `apps/web/src/app/(app)/layout.tsx`, `apps/web/src/lib/design-tokens.ts`, `apps/web/src/components/layout/app-shell.tsx`, `apps/web/src/components/ui/status-badge.tsx`, `apps/web/src/components/ui/data-card.tsx`, `apps/web/tests/status-badge.test.tsx`

- [ ] **Step 1: Write component tests first**

The status badge tests must assert that success, warning, and danger states expose both text and an accessible status label, not color alone:

```tsx
it("renders failure text and status semantics", () => {
  render(<StatusBadge status="failed">解析失败</StatusBadge>);
  expect(screen.getByText("解析失败")).toBeVisible();
  expect(screen.getByRole("status")).toHaveAttribute("data-status", "failed");
});
```

- [ ] **Step 2: Define tokens from the approved UI spec**

Add Light and Dark CSS variables for canvas, surface, sidebar, primary, action, text, muted, border, success, warning, and danger. Use the spec values exactly and expose them through Tailwind semantic names. Add `prefers-reduced-motion` defaults.

- [ ] **Step 3: Implement shared primitives**

`StatusBadge` must support `success`, `warning`, `danger`, `info`, and `neutral`; combine color with text and a non-emoji SVG/CSS status marker. `DataCard` must support label, value, supporting text, and optional trend without embedding business calculations.

- [ ] **Step 4: Implement the responsive shell**

The shell must render a desktop sidebar/topbar and collapse navigation into an accessible drawer below the tablet breakpoint. Main content must use responsive padding and never be hidden behind fixed elements. All buttons and navigation items must have visible focus styles.

- [ ] **Step 5: Run web tests and checks**

Run: `pnpm --dir apps/web test -- --run && pnpm --dir apps/web lint && pnpm --dir apps/web typecheck`

Expected: component tests pass and all static checks exit 0.

- [ ] **Step 6: Commit the web shell**

```bash
git add apps/web
git commit -m "feat: add responsive admin shell and design tokens"
```

### Task 7: Add canonical navigation and permission-aware project context

**Files:** `apps/web/src/lib/navigation.ts`, `apps/web/src/lib/auth/permissions.ts`, `apps/web/src/components/layout/sidebar-nav.tsx`, `apps/web/src/components/layout/project-switcher.tsx`, `apps/web/src/components/layout/user-menu.tsx`, `apps/web/src/app/(app)/page.tsx`, `apps/web/src/app/(app)/settings/members/page.tsx`, `apps/web/tests/navigation.test.tsx`

- [ ] **Step 1: Write navigation tests**

Test that:

```tsx
it("shows approved menu groups in canonical order", () => {
  render(<SidebarNav role="editor" pathname="/" />);
  expect(screen.getByText("数据资产")).toBeVisible();
  expect(screen.getByText("评测实验")).toBeVisible();
  expect(screen.getByText("分析诊断")).toBeVisible();
  expect(screen.getByText("系统管理")).toBeVisible();
});

it("hides member management from viewers", () => {
  render(<SidebarNav role="viewer" pathname="/settings/members" />);
  expect(screen.queryByText("项目与成员")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Define the canonical menu tree**

Use these exact groups and paths:

```ts
export const navigation = [
  { label: "工作台", href: "/", permission: "project.read" },
  { label: "数据资产", children: [
    { label: "文档库", href: "/documents", permission: "asset.read" },
    { label: "评测集", href: "/datasets", permission: "asset.read" },
    { label: "审核队列", href: "/review", permission: "asset.edit" },
  ]},
  { label: "评测实验", children: [
    { label: "Pipeline 接入", href: "/adapters", permission: "adapter.edit" },
    { label: "实验任务", href: "/experiments", permission: "experiment.edit" },
    { label: "运行记录", href: "/runs", permission: "experiment.read" },
  ]},
  { label: "分析诊断", children: [
    { label: "指标看板", href: "/metrics", permission: "diagnostics.read" },
    { label: "Trace 分析", href: "/traces", permission: "diagnostics.read" },
    { label: "失败案例", href: "/failures", permission: "diagnostics.read" },
  ]},
  { label: "系统管理", children: [
    { label: "模型与服务", href: "/settings/services", permission: "service.admin" },
    { label: "项目与成员", href: "/settings/members", permission: "member.admin" },
  ]},
] as const;
```

- [ ] **Step 3: Implement project context**

The project switcher must load visible projects from `GET /api/projects`, preserve the selected project ID in the URL/query or a documented client store, and show an empty state when the actor has no project. Never silently switch projects after a failed API request.

- [ ] **Step 4: Implement placeholder routes with approved page hierarchy**

Create route-level empty states for all approved paths. Each empty state must name the page, explain its future responsibility, and provide a relevant next action. Do not add business functionality to this foundation plan.

- [ ] **Step 5: Run navigation tests**

Run: `pnpm --dir apps/web test -- --run tests/navigation.test.tsx && pnpm --dir apps/web typecheck`

Expected: menu order, role filtering, active state, and route compilation pass.

- [ ] **Step 6: Commit navigation and context**

```bash
git add apps/web/src apps/web/tests
git commit -m "feat: add permission aware admin navigation"
```

### Task 8: Add API/web integration and browser smoke coverage

**Files:** `apps/web/src/lib/api/client.ts`, `apps/web/src/lib/api/generated.ts`, `apps/web/e2e/admin-shell.spec.ts`, `apps/api/tests/test_health.py`, `.github/workflows/ci.yml`, `scripts/wait-for-services.sh`

- [ ] **Step 1: Generate the typed API client**

Expose the FastAPI OpenAPI document at `/openapi.json`. Generate the web client from that document into `apps/web/src/lib/api/generated.ts`; generated files must be marked as generated and must not be hand-edited. CI must fail if generation produces a diff.

- [ ] **Step 2: Add browser smoke test**

The Playwright test must start against the local web URL and assert:

```ts
test("admin can open the project shell", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("navigation")).toContainText("工作台");
  await expect(page.getByRole("navigation")).toContainText("数据资产");
  await page.getByRole("link", { name: "项目与成员" }).click();
  await expect(page).toHaveURL(/settings\/members/);
});
```

- [ ] **Step 3: Add CI jobs**

CI must run on pull requests and pushes to `main` with separate jobs for API quality, web quality, integration tests, and Playwright smoke tests. Cache pnpm and uv dependencies. Upload Playwright traces only on failure. Do not make external provider calls in CI.

- [ ] **Step 4: Run the complete foundation verification**

Run:

```bash
make infra-up
bash scripts/wait-for-services.sh
make lint
make typecheck
make test
make build
pnpm --dir apps/web exec playwright test e2e/admin-shell.spec.ts
```

Expected: every command exits 0; the browser test reaches the member page; no secret or external model request is required.

- [ ] **Step 5: Commit integration coverage**

```bash
git add apps/web/src/lib/api apps/web/e2e .github/workflows/ci.yml scripts/wait-for-services.sh
git commit -m "test: add api web integration and admin shell smoke coverage"
```

## Self-review checklist

- [ ] PRD coverage: foundation, organization/project/member roles, admin menu, adapter placeholder, experiment placeholder, diagnostics placeholder, audit, security, responsive UI, accessibility, and CI are mapped to tasks or explicitly assigned to later plans.
- [ ] No implementation task relies on an undefined path, role, permission, API route, or test fixture.
- [ ] The canonical roles are exactly `admin`, `editor`, and `viewer` across API and web.
- [ ] The navigation paths and permission names are defined once and reused by tests.
- [ ] Async job execution and business data ingestion are explicitly outside this plan, preventing premature infrastructure coupling.
- [ ] The plan contains no unresolved planning markers or vague implementation instructions.

## Follow-up plan sequence

After this plan passes its quality gates, create separate implementation plans in this order:

1. Document ingestion, parsing, versioning, and candidate evaluation-set generation.
2. Review queue, Gold Dataset publishing, and dataset version comparison.
3. HTTP/Python Adapter contract, execution engine, retries, and Trace persistence.
4. Metrics engine, failure classification, dashboard queries, and report export.
5. Authentication, invitation delivery, production deployment, security hardening, and open-source release automation.
