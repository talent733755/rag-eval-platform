from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from rag_eval_api.config import DEFAULT_REDIS_URL, DEFAULT_SECRET_KEY, Settings
from rag_eval_api.db import get_db_session
from rag_eval_api.models import AuditEvent, Base, Membership, MembershipRole, Organization, Project

ACTOR_ID = UUID("00000000-0000-0000-0000-000000000101")
ADMIN_ID = UUID("00000000-0000-0000-0000-000000000102")
EDITOR_ID = UUID("00000000-0000-0000-0000-000000000103")
VIEWER_ID = UUID("00000000-0000-0000-0000-000000000104")
OTHER_ORG_ADMIN_ID = UUID("00000000-0000-0000-0000-000000000105")

PERMISSION_DENIED_BODY = {
    "error": {
        "code": "permission_denied",
        "message": "You do not have permission to perform this action.",
    }
}
CONFLICT_BODY = {
    "error": {
        "code": "conflict",
        "message": "Project conflicts with existing data.",
    }
}


@dataclass
class Seed:
    organization_id: UUID
    other_organization_id: UUID
    project_id: UUID
    other_project_id: UUID
    admin_membership_id: UUID
    editor_membership_id: UUID
    viewer_membership_id: UUID


@pytest_asyncio.fixture
async def api_environment() -> AsyncIterator[
    tuple[FastAPI, httpx.AsyncClient, Seed, Callable[[UUID], None], async_sessionmaker[AsyncSession]]
]:
    from rag_eval_api.auth.context import RequestActor, get_current_actor
    from rag_eval_api.main import create_app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(
        dbapi_connection: sqlite3.Connection,
        connection_record: object,
    ) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as seed_session:
        organization = Organization(name="Acme", slug="acme")
        other_organization = Organization(name="Other", slug="other")
        project = Project(name="Main", slug="main", organization=organization)
        second_admin_project = Project(
            name="Second admin project",
            slug="second-admin-project",
            organization=organization,
        )
        other_project = Project(name="Other project", slug="other-project", organization=other_organization)
        admin_membership = Membership(
            organization=organization,
            project=project,
            user_id=ADMIN_ID,
            role=MembershipRole.admin,
        )
        editor_membership = Membership(
            organization=organization,
            project=project,
            user_id=EDITOR_ID,
            role=MembershipRole.editor,
        )
        viewer_membership = Membership(
            organization=organization,
            project=project,
            user_id=VIEWER_ID,
            role=MembershipRole.viewer,
        )
        second_admin_membership = Membership(
            organization=organization,
            project=second_admin_project,
            user_id=ADMIN_ID,
            role=MembershipRole.admin,
        )
        seed_session.add_all(
            [
                organization,
                other_organization,
                project,
                second_admin_project,
                other_project,
                admin_membership,
                editor_membership,
                viewer_membership,
                second_admin_membership,
                Membership(
                    organization=other_organization,
                    project=other_project,
                    user_id=OTHER_ORG_ADMIN_ID,
                    role=MembershipRole.admin,
                ),
            ]
        )
        await seed_session.commit()
        seed = Seed(
            organization_id=organization.id,
            other_organization_id=other_organization.id,
            project_id=project.id,
            other_project_id=other_project.id,
            admin_membership_id=admin_membership.id,
            editor_membership_id=editor_membership.id,
            viewer_membership_id=viewer_membership.id,
        )

    settings = Settings(
        database_url="postgresql+asyncpg://rag_eval:change-me@localhost:5432/rag_eval",
        redis_url=DEFAULT_REDIS_URL,
        app_env="development",
        cors_origins=["http://localhost:3000"],
        log_level="INFO",
        secret_key=SecretStr(DEFAULT_SECRET_KEY),
        _env_file=None,  # type: ignore[call-arg]
    )
    application = create_app(settings=settings)
    current_actor = RequestActor(user_id=VIEWER_ID, organization_id=seed.organization_id)
    application.dependency_overrides[get_current_actor] = lambda: current_actor

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db_session] = override_db_session

    def set_actor(user_id: UUID) -> None:
        nonlocal current_actor
        organization_id = (
            seed.other_organization_id if user_id == OTHER_ORG_ADMIN_ID else seed.organization_id
        )
        current_actor = RequestActor(user_id=user_id, organization_id=organization_id)

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            yield application, client, seed, set_actor, session_factory
    finally:
        application.dependency_overrides.clear()
        await application.state.db_engine.dispose()
        await application.state.redis_client.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_visible_projects_are_isolated_and_viewers_can_read_members(
    api_environment: tuple[FastAPI, httpx.AsyncClient, Seed, Callable[[UUID], None], async_sessionmaker[AsyncSession]],
) -> None:
    _, client, seed, set_actor, _ = api_environment
    set_actor(VIEWER_ID)

    response = await client.get("/api/projects")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(seed.project_id)]

    response = await client.get(f"/api/projects/{seed.project_id}")
    assert response.status_code == 200
    assert response.json()["slug"] == "main"

    response = await client.get(f"/api/projects/{seed.project_id}/members")
    assert response.status_code == 200
    assert {item["role"] for item in response.json()} == {"admin", "editor", "viewer"}

    response = await client.get(f"/api/projects/{seed.other_project_id}")
    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "permission_denied",
            "message": "You do not have permission to perform this action.",
        }
    }


@pytest.mark.asyncio
async def test_nonmember_gets_same_permission_error_for_existing_and_missing_project(
    api_environment: tuple[FastAPI, httpx.AsyncClient, Seed, Callable[[UUID], None], async_sessionmaker[AsyncSession]],
) -> None:
    _, client, seed, set_actor, _ = api_environment
    set_actor(ACTOR_ID)

    existing = await client.get(f"/api/projects/{seed.project_id}")
    missing = await client.get(f"/api/projects/{uuid4()}")

    assert existing.status_code == missing.status_code == 403
    assert existing.json() == missing.json()


@pytest.mark.asyncio
async def test_project_creation_is_admin_only_and_audited(
    api_environment: tuple[FastAPI, httpx.AsyncClient, Seed, Callable[[UUID], None], async_sessionmaker[AsyncSession]],
) -> None:
    _, client, seed, set_actor, session_factory = api_environment
    set_actor(EDITOR_ID)
    denied = await client.post(
        "/api/projects",
        json={"name": "Denied", "slug": "denied", "description": None},
    )
    assert denied.status_code == 403
    assert denied.json() == PERMISSION_DENIED_BODY

    set_actor(VIEWER_ID)
    viewer_denied = await client.post(
        "/api/projects",
        json={"name": "Viewer denied", "slug": "viewer-denied", "description": None},
    )
    assert viewer_denied.status_code == 403
    assert viewer_denied.json() == PERMISSION_DENIED_BODY

    set_actor(ADMIN_ID)
    created = await client.post(
        "/api/projects",
        json={"name": "New project", "slug": "new-project", "description": "A test"},
    )
    assert created.status_code == 201
    project_id = UUID(created.json()["id"])

    async with session_factory() as session:
        audit = (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.project_id == project_id,
                    AuditEvent.action == "project.created",
                )
            )
        ).scalar_one()
        membership = (
            await session.execute(
                select(Membership).where(
                    Membership.project_id == project_id,
                    Membership.user_id == ADMIN_ID,
                )
            )
        ).scalar_one()
        assert audit.actor_id == ADMIN_ID
        assert audit.organization_id == seed.organization_id
        assert membership.role is MembershipRole.admin


@pytest.mark.asyncio
async def test_organization_admin_with_multiple_project_admin_memberships_can_create(
    api_environment: tuple[
        FastAPI,
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
    ],
) -> None:
    _, client, _, set_actor, _ = api_environment
    set_actor(ADMIN_ID)

    response = await client.post(
        "/api/projects",
        json={"name": "Multiple admin memberships", "slug": "multiple-admin-memberships"},
    )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_final_project_admin_cannot_demote_or_delete_self(
    api_environment: tuple[
        FastAPI,
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
    ],
) -> None:
    _, client, seed, set_actor, session_factory = api_environment
    set_actor(ADMIN_ID)

    demotion = await client.patch(
        f"/api/projects/{seed.project_id}/members/{seed.admin_membership_id}",
        json={"role": "viewer"},
    )
    deletion = await client.delete(
        f"/api/projects/{seed.project_id}/members/{seed.admin_membership_id}"
    )

    assert demotion.status_code == deletion.status_code == 409
    assert demotion.json() == deletion.json() == {
        "error": {
            "code": "conflict",
            "message": "A project must retain at least one administrator.",
        }
    }
    async with session_factory() as session:
        membership = await session.get(Membership, seed.admin_membership_id)
        assert membership is not None
        assert membership.role is MembershipRole.admin
        assert (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.project_id == seed.project_id,
                    AuditEvent.action.in_(["project.member.role_changed", "project.member.removed"]),
                )
            )
        ).scalars().all() == []


@pytest.mark.asyncio
async def test_admin_from_another_organization_cannot_access_project(
    api_environment: tuple[
        FastAPI,
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
    ],
) -> None:
    _, client, seed, set_actor, _ = api_environment
    set_actor(OTHER_ORG_ADMIN_ID)

    visible = await client.get("/api/projects")
    detail = await client.get(f"/api/projects/{seed.project_id}")
    invite = await client.post(
        f"/api/projects/{seed.project_id}/members",
        json={"email": "cross-org@example.com", "role": "viewer"},
    )
    update = await client.patch(
        f"/api/projects/{seed.project_id}/members/{seed.viewer_membership_id}",
        json={"role": "editor"},
    )
    remove = await client.delete(
        f"/api/projects/{seed.project_id}/members/{seed.viewer_membership_id}"
    )

    assert [item["id"] for item in visible.json()] == [str(seed.other_project_id)]
    assert detail.status_code == 403
    assert invite.status_code == update.status_code == remove.status_code == 403
    assert detail.json() == invite.json() == update.json() == remove.json() == PERMISSION_DENIED_BODY


@pytest.mark.asyncio
async def test_duplicate_project_slug_returns_conflict_without_partial_mutation(
    api_environment: tuple[
        FastAPI,
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
    ],
) -> None:
    _, client, seed, set_actor, session_factory = api_environment
    set_actor(ADMIN_ID)

    response = await client.post(
        "/api/projects",
        json={"name": "Duplicate", "slug": "main", "description": None},
    )

    assert response.status_code == 409
    assert response.json() == CONFLICT_BODY
    async with session_factory() as session:
        projects = (
            await session.execute(
                select(Project).where(
                    Project.organization_id == seed.organization_id,
                    Project.slug == "main",
                )
            )
        ).scalars().all()
        assert len(projects) == 1
        assert (
            await session.execute(
                select(AuditEvent).where(AuditEvent.action == "project.created")
            )
        ).scalars().all() == []


@pytest.mark.asyncio
async def test_audit_integrity_failure_rolls_back_project_creation(
    api_environment: tuple[
        FastAPI,
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rag_eval_api.routes.projects as project_routes

    _, client, seed, set_actor, session_factory = api_environment
    original_record_audit_event = project_routes.record_audit_event

    def record_invalid_audit_event(
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        project_id: UUID | None,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: str,
        metadata: Mapping[str, object],
    ) -> AuditEvent:
        del project_id
        return original_record_audit_event(
            db_session,
            organization_id=organization_id,
            project_id=uuid4(),
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata,
        )

    monkeypatch.setattr(project_routes, "record_audit_event", record_invalid_audit_event)
    set_actor(ADMIN_ID)

    response = await client.post(
        "/api/projects",
        json={"name": "Rolled back", "slug": "rolled-back", "description": None},
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_server_error", "message": "Internal server error"}
    }
    async with session_factory() as session:
        assert (
            await session.execute(select(Project).where(Project.slug == "rolled-back"))
        ).scalar_one_or_none() is None
        assert (
            await session.execute(
                select(Membership).where(Membership.project_id == seed.project_id)
            )
        ).scalars().all()


@pytest.mark.asyncio
async def test_member_management_requires_admin_and_writes_audit_events(
    api_environment: tuple[
        FastAPI,
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
    ],
) -> None:
    application, client, seed, set_actor, session_factory = api_environment
    set_actor(EDITOR_ID)
    denied = await client.post(
        f"/api/projects/{seed.project_id}/members",
        json={"email": "new@example.com", "role": "viewer"},
    )
    assert denied.status_code == 403

    set_actor(ADMIN_ID)
    invited = await client.post(
        f"/api/projects/{seed.project_id}/members",
        json={"email": "new@example.com", "role": "viewer"},
    )
    assert invited.status_code == 202
    assert invited.json()["status"] == "pending"

    changed = await client.patch(
        f"/api/projects/{seed.project_id}/members/{seed.viewer_membership_id}",
        json={"role": "editor"},
    )
    assert changed.status_code == 200
    assert changed.json()["role"] == "editor"

    removed = await client.delete(
        f"/api/projects/{seed.project_id}/members/{seed.editor_membership_id}"
    )
    assert removed.status_code == 204

    async with session_factory() as session:
        actions = {
            row.action
            for row in (
                await session.execute(
                    select(AuditEvent).where(AuditEvent.project_id == seed.project_id)
                )
            ).scalars()
        }
    assert {
        "project.member.invited",
        "project.member.role_changed",
        "project.member.removed",
    }.issubset(actions)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("actor_id", "expected_status"),
    [(ADMIN_ID, 202), (EDITOR_ID, 403), (VIEWER_ID, 403)],
    ids=["admin", "editor", "viewer"],
)
async def test_invite_member_role_matrix(
    api_environment: tuple[
        FastAPI,
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
    ],
    actor_id: UUID,
    expected_status: int,
) -> None:
    _, client, seed, set_actor, _ = api_environment
    set_actor(actor_id)

    response = await client.post(
        f"/api/projects/{seed.project_id}/members",
        json={"email": "matrix@example.com", "role": "viewer"},
    )

    assert response.status_code == expected_status
    if expected_status == 403:
        assert response.json() == PERMISSION_DENIED_BODY
    else:
        assert response.json()["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("actor_id", "expected_status"),
    [(ADMIN_ID, 200), (EDITOR_ID, 403), (VIEWER_ID, 403)],
    ids=["admin", "editor", "viewer"],
)
async def test_update_member_role_matrix(
    api_environment: tuple[
        FastAPI,
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
    ],
    actor_id: UUID,
    expected_status: int,
) -> None:
    _, client, seed, set_actor, _ = api_environment
    set_actor(actor_id)

    response = await client.patch(
        f"/api/projects/{seed.project_id}/members/{seed.viewer_membership_id}",
        json={"role": "editor"},
    )

    assert response.status_code == expected_status
    if expected_status == 403:
        assert response.json() == PERMISSION_DENIED_BODY
    else:
        assert response.json()["role"] == "editor"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("actor_id", "expected_status"),
    [(ADMIN_ID, 204), (EDITOR_ID, 403), (VIEWER_ID, 403)],
    ids=["admin", "editor", "viewer"],
)
async def test_remove_member_role_matrix(
    api_environment: tuple[
        FastAPI,
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
    ],
    actor_id: UUID,
    expected_status: int,
) -> None:
    _, client, seed, set_actor, _ = api_environment
    set_actor(actor_id)

    response = await client.delete(
        f"/api/projects/{seed.project_id}/members/{seed.editor_membership_id}"
    )

    assert response.status_code == expected_status
    if expected_status == 403:
        assert response.json() == PERMISSION_DENIED_BODY


@pytest.mark.asyncio
async def test_member_mutation_validation_returns_consistent_422_error(
    api_environment: tuple[FastAPI, httpx.AsyncClient, Seed, Callable[[UUID], None], async_sessionmaker[AsyncSession]],
) -> None:
    _, client, seed, set_actor, _ = api_environment
    set_actor(ADMIN_ID)

    invalid_email = await client.post(
        f"/api/projects/{seed.project_id}/members",
        json={"email": "a@.b", "role": "viewer"},
    )
    invalid_role = await client.post(
        f"/api/projects/{seed.project_id}/members",
        json={"email": "new@example.com", "role": "owner"},
    )

    expected = {"error": {"code": "validation_error", "message": "Request validation failed"}}
    assert invalid_email.status_code == invalid_role.status_code == 422
    assert invalid_email.json() == invalid_role.json() == expected


@pytest.mark.asyncio
async def test_missing_route_returns_consistent_404_error(
    api_environment: tuple[
        FastAPI,
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
    ],
) -> None:
    _, client, _, _, _ = api_environment

    response = await client.get("/api/unknown")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Resource not found."}
    }


@pytest.mark.asyncio
async def test_production_auth_boundary_returns_501_without_actor_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rag_eval_api.main import create_app

    # This test exercises the auth boundary, not the host's sandbox capability.
    monkeypatch.setattr(
        "rag_eval_api.parsers.runner.restricted_sandbox_available", lambda: True
    )
    settings = Settings(
        database_url="postgresql+asyncpg://rag_eval:real-password@db.example/rag_eval",
        redis_url="redis://redis.example:6379/0",
        app_env="production",
        cors_origins=[],
        log_level="INFO",
        secret_key=SecretStr("a" * 32),
        parser_require_resource_limits=True,
        _env_file=None,  # type: ignore[call-arg]
    )
    application = create_app(settings=settings)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/projects")
    finally:
        await application.state.db_engine.dispose()
        await application.state.redis_client.aclose()

    assert response.status_code == 501
    assert response.json() == {
        "error": {"code": "not_implemented", "message": "Authentication is not configured."}
    }
