"""Async PostgreSQL and Redis resource setup."""

from __future__ import annotations

import logging
import re
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

from rag_eval_api.config import LOGGER_NAME, Settings

DATABASE_CONNECT_TIMEOUT_SECONDS = 5.0
DATABASE_POOL_TIMEOUT_SECONDS = 5.0
REDIS_SOCKET_TIMEOUT_SECONDS = 5.0
logger = logging.getLogger(LOGGER_NAME)


def _sanitize_exception(exc: Exception) -> str:
    message = re.sub(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s]+", "[redacted-url]", str(exc))
    message = re.sub(
        r"(?i)\b(password|passwd|secret|token|api[_-]?key)\s*=\s*[^\s]+",
        r"\1=[redacted]",
        message,
    )
    return message[:200]


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the async SQLAlchemy engine without opening a network connection."""

    return create_async_engine(
        settings.database_url,
        connect_args={"timeout": DATABASE_CONNECT_TIMEOUT_SECONDS},
        pool_pre_ping=True,
        pool_timeout=DATABASE_POOL_TIMEOUT_SECONDS,
    )


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

    app.state.redis_client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
    )


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
        try:
            await cast(AsyncEngine, engine).dispose()
        except Exception as exc:
            logger.error(
                "resource.cleanup.failed",
                extra={
                    "event": "resource.cleanup.failed",
                    "resource": "database",
                    "exception_type": type(exc).__name__,
                    "exception_message": _sanitize_exception(exc),
                },
            )

    redis_client = getattr(app.state, "redis_client", None)
    if redis_client is not None:
        try:
            await cast(Redis, redis_client).aclose()
        except Exception as exc:
            logger.error(
                "resource.cleanup.failed",
                extra={
                    "event": "resource.cleanup.failed",
                    "resource": "redis",
                    "exception_type": type(exc).__name__,
                    "exception_message": _sanitize_exception(exc),
                },
            )
