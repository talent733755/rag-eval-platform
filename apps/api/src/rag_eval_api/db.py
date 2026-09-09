"""Async PostgreSQL and Redis resource setup."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.applications import Starlette

from rag_eval_api.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the async SQLAlchemy engine without opening a network connection."""

    return create_async_engine(settings.database_url, pool_pre_ping=True)


def configure_database(app: Starlette, settings: Settings) -> None:
    """Attach an engine and typed session factory to application state."""

    engine = create_engine(settings)
    app.state.db_engine = engine
    app.state.db_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


def _get_session_factory(app: Starlette) -> async_sessionmaker[AsyncSession]:
    factory = getattr(app.state, "db_session_factory", None)
    if factory is None:
        raise RuntimeError("database session factory is not configured")
    return cast(async_sessionmaker[AsyncSession], factory)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped SQLAlchemy session."""

    session_factory = _get_session_factory(request.app)
    async with session_factory() as session:
        yield session


def configure_redis(app: Starlette, settings: Settings) -> None:
    """Attach a lazy async Redis client to application state."""

    app.state.redis_client = Redis.from_url(settings.redis_url, decode_responses=True)


def get_redis_client(request: Request) -> Redis:
    """Return the application-scoped async Redis client."""

    client = getattr(request.app.state, "redis_client", None)
    if client is None:
        raise RuntimeError("Redis client is not configured")
    return cast(Redis, client)


async def close_resources(app: Starlette) -> None:
    """Release network resources during application shutdown."""

    engine = getattr(app.state, "db_engine", None)
    if engine is not None:
        await cast(AsyncEngine, engine).dispose()

    redis_client = getattr(app.state, "redis_client", None)
    if redis_client is not None:
        await cast(Redis, redis_client).aclose()
