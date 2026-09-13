"""Create the deterministic development organization and project membership."""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from rag_eval_api.config import get_settings
from rag_eval_api.db import create_engine
from rag_eval_api.models import Membership, MembershipRole, Organization, Project

DEVELOPMENT_ORGANIZATION_ID = UUID("00000000-0000-4000-8000-000000000010")
DEVELOPMENT_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000011")
DEVELOPMENT_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000000012")


async def seed_development_data() -> None:
    settings = get_settings()
    if settings.app_env != "development":
        raise SystemExit("Refusing to seed development data unless APP_ENV=development")
    if settings.dev_actor_id is None:
        raise SystemExit("DEV_ACTOR_ID must be configured before seeding development data")

    engine = create_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            organization = await session.get(Organization, DEVELOPMENT_ORGANIZATION_ID)
            if organization is None:
                session.add(
                    Organization(
                        id=DEVELOPMENT_ORGANIZATION_ID,
                        name="RAG Eval Development",
                        slug="rag-eval-development",
                    )
                )

            project = await session.get(Project, DEVELOPMENT_PROJECT_ID)
            if project is None:
                session.add(
                    Project(
                        id=DEVELOPMENT_PROJECT_ID,
                        organization_id=DEVELOPMENT_ORGANIZATION_ID,
                        name="Demo Evaluation Project",
                        slug="demo-evaluation",
                        description="Deterministic local development project.",
                    )
                )

            membership = await session.get(Membership, DEVELOPMENT_MEMBERSHIP_ID)
            if membership is None:
                session.add(
                    Membership(
                        id=DEVELOPMENT_MEMBERSHIP_ID,
                        organization_id=DEVELOPMENT_ORGANIZATION_ID,
                        project_id=DEVELOPMENT_PROJECT_ID,
                        user_id=settings.dev_actor_id,
                        role=MembershipRole.admin,
                    )
                )

            await session.commit()
    finally:
        await engine.dispose()

    print(
        "Seeded development project "
        f"{DEVELOPMENT_PROJECT_ID} for actor {settings.dev_actor_id}."
    )


if __name__ == "__main__":
    asyncio.run(seed_development_data())
