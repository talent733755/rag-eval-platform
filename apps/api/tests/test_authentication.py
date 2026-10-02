from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
import time
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rag_eval_api.config import DEFAULT_REDIS_URL, DEFAULT_SECRET_KEY, Settings
from rag_eval_api.db import get_db_session
from rag_eval_api.models import Base, Membership, MembershipRole, Organization, Project

ACTOR_ID = UUID("00000000-0000-4000-8000-000000000001")
ORGANIZATION_ID = UUID("00000000-0000-4000-8000-000000000010")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000011")
JWT_SECRET = "s" * 40


def encode_hs256_token(payload: dict[str, object], secret: str = JWT_SECRET) -> str:
    def encode(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = encode({"alg": "HS256", "typ": "JWT"})
    body = encode(payload)
    signing_input = f"{header}.{body}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def configure_jwt(application: FastAPI) -> None:
    application.state.settings.auth_mode = "jwt_hs256"
    application.state.settings.auth_jwt_secret = SecretStr(JWT_SECRET)
    application.state.settings.auth_jwt_issuer = "https://issuer.example"
    application.state.settings.auth_jwt_audience = "rag-eval-web"


@pytest_asyncio.fixture
async def authentication_environment() -> AsyncIterator[
    tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]]
]:
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

    settings = Settings(
        database_url="postgresql+asyncpg://rag_eval:change-me@localhost:5432/rag_eval",
        redis_url=DEFAULT_REDIS_URL,
        app_env="development",
        dev_actor_id=ACTOR_ID,
        cors_origins=["http://localhost:3003"],
        secret_key=DEFAULT_SECRET_KEY,
        _env_file=None,  # type: ignore[call-arg]
    )
    application = create_app(settings=settings)

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db_session] = override_db_session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            yield application, client, session_factory
    finally:
        application.dependency_overrides.clear()
        await application.state.db_engine.dispose()
        await application.state.redis_client.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_development_actor_is_resolved_from_unique_membership(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    _, client, session_factory = authentication_environment
    async with session_factory() as session:
        organization = Organization(name="Development", slug="development")
        project = Project(name="Demo project", slug="demo", organization=organization)
        membership = Membership(
            organization=organization,
            project=project,
            user_id=ACTOR_ID,
            role=MembershipRole.admin,
        )
        session.add_all([organization, project, membership])
        await session.commit()

    response = await client.get("/api/projects")

    assert response.status_code == 200
    assert response.json()[0]["slug"] == "demo"


@pytest.mark.asyncio
async def test_development_actor_requires_a_membership(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    _, client, _ = authentication_environment

    response = await client.get("/api/projects")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "development_actor_not_provisioned",
            "message": "Development actor is not provisioned in any organization.",
        }
    }


@pytest.mark.asyncio
async def test_development_actor_rejects_multiple_organizations(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    _, client, session_factory = authentication_environment
    async with session_factory() as session:
        first_organization = Organization(name="First", slug="first")
        second_organization = Organization(name="Second", slug="second")
        first_project = Project(name="First project", slug="first", organization=first_organization)
        second_project = Project(
            name="Second project", slug="second", organization=second_organization
        )
        session.add_all(
            [
                first_organization,
                second_organization,
                first_project,
                second_project,
                Membership(
                    organization=first_organization,
                    project=first_project,
                    user_id=ACTOR_ID,
                    role=MembershipRole.admin,
                ),
                Membership(
                    organization=second_organization,
                    project=second_project,
                    user_id=ACTOR_ID,
                    role=MembershipRole.admin,
                ),
            ]
        )
        await session.commit()

    response = await client.get("/api/projects")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "development_actor_ambiguous",
            "message": "Development actor belongs to multiple organizations.",
        }
    }


@pytest.mark.asyncio
async def test_jwt_resolves_actor_and_scopes_to_token_organization(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    application, client, session_factory = authentication_environment
    configure_jwt(application)
    async with session_factory() as session:
        organization = Organization(id=ORGANIZATION_ID, name="JWT Org", slug="jwt-org")
        project = Project(
            id=PROJECT_ID, name="JWT project", slug="jwt-project", organization_id=ORGANIZATION_ID
        )
        session.add_all(
            [
                organization,
                project,
                Membership(
                    organization_id=ORGANIZATION_ID,
                    project_id=project.id,
                    user_id=ACTOR_ID,
                    role=MembershipRole.admin,
                ),
            ]
        )
        await session.commit()

    token = encode_hs256_token(
        {
            "sub": str(ACTOR_ID),
            "organization_id": str(ORGANIZATION_ID),
            "iss": "https://issuer.example",
            "aud": "rag-eval-web",
            "exp": int(time.time()) + 300,
        }
    )
    response = await client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()[0]["slug"] == "jwt-project"


@pytest.mark.asyncio
async def test_jwt_rejects_invalid_signature(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    application, client, _ = authentication_environment
    configure_jwt(application)
    token = encode_hs256_token(
        {
            "sub": str(ACTOR_ID),
            "organization_id": str(ORGANIZATION_ID),
            "iss": "https://issuer.example",
            "aud": "rag-eval-web",
            "exp": int(time.time()) + 300,
        },
        secret="wrong-secret",
    )

    response = await client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


@pytest.mark.asyncio
async def test_jwt_rejects_expired_token(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    application, client, _ = authentication_environment
    configure_jwt(application)
    token = encode_hs256_token(
        {
            "sub": str(ACTOR_ID),
            "organization_id": str(ORGANIZATION_ID),
            "iss": "https://issuer.example",
            "aud": "rag-eval-web",
            "exp": int(time.time()) - 60,
        }
    )

    response = await client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


@pytest.mark.asyncio
async def test_jwt_rejects_token_for_organization_without_membership(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    application, client, _ = authentication_environment
    configure_jwt(application)
    token = encode_hs256_token(
        {
            "sub": str(ACTOR_ID),
            "organization_id": str(ORGANIZATION_ID),
            "iss": "https://issuer.example",
            "aud": "rag-eval-web",
            "exp": int(time.time()) + 300,
        }
    )

    response = await client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


@pytest.mark.asyncio
async def test_jwt_requires_authorization_header(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    application, client, _ = authentication_environment
    configure_jwt(application)

    response = await client.get("/api/projects")

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "authentication_required",
            "message": "Bearer authentication is required.",
        }
    }


@pytest.mark.asyncio
async def test_jwt_rejects_non_bearer_scheme(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    application, client, _ = authentication_environment
    configure_jwt(application)

    basic = await client.get("/api/projects", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    missing_token = await client.get("/api/projects", headers={"Authorization": "Bearer "})

    for response in (basic, missing_token):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.asyncio
async def test_cors_allows_only_configured_origin(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    _, client, _ = authentication_environment

    allowed = await client.options(
        "/api/projects",
        headers={
            "Origin": "http://localhost:3003",
            "Access-Control-Request-Method": "GET",
        },
    )
    rejected = await client.options(
        "/api/projects",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3003"
    assert "access-control-allow-origin" not in rejected.headers


def test_empty_dev_actor_id_is_treated_as_unset() -> None:
    settings = Settings.model_validate(
        {
            "APP_ENV": "development",
            "DEV_ACTOR_ID": "",
            "_env_file": None,
        }
    )

    assert settings.dev_actor_id is None


@pytest.mark.asyncio
async def test_oidc_resolves_actor_via_jwks_rs256(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    from rag_eval_api.auth.context import OIDC_VERIFIER_STATE_KEY
    from rag_eval_api.auth.oidc import OidcVerifier, jwk_from_rsa_public_key

    application, client, session_factory = authentication_environment

    issuer = "https://idp.example.test"
    audience = "rag-eval-api"
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwk_from_rsa_public_key(private.public_key(), kid="oidc-key-1")

    application.state.settings.auth_mode = "oidc"
    application.state.settings.auth_oidc_jwks_url = "https://idp.example.test/jwks.json"
    application.state.settings.auth_oidc_issuer = issuer
    application.state.settings.auth_oidc_audience = audience
    application.state.settings.auth_jwt_leeway_seconds = 30
    setattr(
        application.state,
        OIDC_VERIFIER_STATE_KEY,
        OidcVerifier(
            jwks_source=lambda: [jwk], issuer=issuer, audience=audience, leeway_seconds=30
        ),
    )

    async with session_factory() as session:
        organization = Organization(id=ORGANIZATION_ID, name="OIDC Org", slug="oidc-org")
        project = Project(
            id=PROJECT_ID, name="OIDC project", slug="oidc-project", organization_id=ORGANIZATION_ID
        )
        session.add_all(
            [
                organization,
                project,
                Membership(
                    organization_id=ORGANIZATION_ID,
                    project_id=project.id,
                    user_id=ACTOR_ID,
                    role=MembershipRole.admin,
                ),
            ]
        )
        await session.commit()

    def encode(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = encode({"alg": "RS256", "typ": "JWT", "kid": "oidc-key-1"})
    body = encode(
        {
            "sub": str(ACTOR_ID),
            "organization_id": str(ORGANIZATION_ID),
            "iss": issuer,
            "aud": audience,
            "exp": int(time.time()) + 300,
        }
    )
    signing_input = f"{header}.{body}".encode()
    signature = private.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    token = f"{header}.{body}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"

    response = await client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert any(project["slug"] == "oidc-project" for project in response.json())


@pytest.mark.asyncio
async def test_oidc_rejects_hs256_downgrade(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    from rag_eval_api.auth.context import OIDC_VERIFIER_STATE_KEY
    from rag_eval_api.auth.oidc import OidcVerifier

    application, client, _ = authentication_environment
    application.state.settings.auth_mode = "oidc"
    setattr(
        application.state,
        OIDC_VERIFIER_STATE_KEY,
        OidcVerifier(
            jwks_source=lambda: [],
            issuer="https://idp.example.test",
            audience="rag-eval-api",
            leeway_seconds=30,
        ),
    )
    token = encode_hs256_token(
        {
            "sub": str(ACTOR_ID),
            "organization_id": str(ORGANIZATION_ID),
            "iss": "https://idp.example.test",
            "aud": "rag-eval-api",
            "exp": int(time.time()) + 300,
        }
    )

    response = await client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_oidc_mode_requires_jwks_url_and_https() -> None:
    base = {
        "APP_ENV": "development",
        "AUTH_MODE": "oidc",
        "AUTH_OIDC_ISSUER": "https://idp.example.test",
        "AUTH_OIDC_AUDIENCE": "rag-eval-api",
        "_env_file": None,
    }
    with pytest.raises(ValueError, match="AUTH_OIDC_JWKS_URL"):
        Settings.model_validate(base)
    with pytest.raises(ValueError, match="https"):
        Settings.model_validate({**base, "AUTH_OIDC_JWKS_URL": "http://idp.example.test/jwks"})


def test_oidc_mode_requires_issuer_and_audience() -> None:
    base = {
        "APP_ENV": "development",
        "AUTH_MODE": "oidc",
        "AUTH_OIDC_JWKS_URL": "https://idp.example.test/jwks.json",
        "_env_file": None,
    }
    with pytest.raises(ValueError, match="AUTH_OIDC_ISSUER"):
        Settings.model_validate(base)


@pytest.mark.asyncio
async def test_permission_denied_is_audited_best_effort(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    from sqlalchemy import select

    from rag_eval_api.models import AuditEvent
    from rag_eval_api.services.audit import AUTH_FAILURE_ACTOR_ID

    application, client, session_factory = authentication_environment
    configure_jwt(application)
    application.state.db_session_factory = session_factory

    # The organization exists but the actor holds no membership in it.
    async with session_factory() as session:
        session.add(Organization(id=ORGANIZATION_ID, name="Audit Org", slug="audit-org"))
        await session.commit()

    # Token is validly signed for an organization the actor does not belong to.
    token = encode_hs256_token(
        {
            "sub": str(ACTOR_ID),
            "organization_id": str(ORGANIZATION_ID),
            "iss": "https://issuer.example",
            "aud": "rag-eval-web",
            "exp": int(time.time()) + 300,
        }
    )
    response = await client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403

    async with session_factory() as session:
        event = await session.scalar(select(AuditEvent).where(AuditEvent.action == "auth.failed"))
        assert event is not None
        assert event.actor_id == AUTH_FAILURE_ACTOR_ID
        assert event.organization_id == ORGANIZATION_ID
        assert event.metadata_json["failure_code"] == "permission_denied"
