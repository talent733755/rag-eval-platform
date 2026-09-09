"""FastAPI application entry point and dependency health endpoints."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware

from rag_eval_api.config import Settings, get_settings
from rag_eval_api.db import (
    close_resources,
    configure_database,
    configure_redis,
    get_db_session,
    get_redis_client,
)

LOGGER_NAME = "rag_eval_api.request"
logger = logging.getLogger(LOGGER_NAME)


class JsonLogFormatter(logging.Formatter):
    """Render request records as compact JSON without including exception text."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "event": record.getMessage(),
                "logger": record.name,
                "level": record.levelname,
            },
            separators=(",", ":"),
        )


def configure_logging(settings: Settings) -> None:
    logger.setLevel(settings.log_level.upper())
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    logger.propagate = False


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    yield
    await close_resources(application)


def _error_payload(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def create_app(settings: Settings | None = None) -> FastAPI:
    configured_settings = settings or get_settings()
    configure_logging(configured_settings)
    application = FastAPI(
        title="RAG Eval Platform API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = configured_settings
    configure_database(application, configured_settings)
    configure_redis(application, configured_settings)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=configured_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def request_logging(request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            json.dumps(
                {
                    "event": "request.completed",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
                separators=(",", ":"),
            )
        )
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=422,
            content=_error_payload("validation_error", "Request validation failed"),
        )

    @application.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=500,
            content=_error_payload("internal_server_error", "Internal server error"),
        )

    @application.get("/health/live", response_model=None)
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready", response_model=None)
    async def readiness(
        db_session: AsyncSession = Depends(get_db_session),
        redis_client: Redis = Depends(get_redis_client),
    ) -> Response:
        database_status = "ok"
        redis_status = "ok"
        try:
            await db_session.execute(text("SELECT 1"))
        except Exception:
            database_status = "error"
        try:
            await redis_client.ping()
        except Exception:
            redis_status = "error"

        dependencies = {"database": database_status, "redis": redis_status}
        if database_status != "ok" or redis_status != "ok":
            return JSONResponse(
                status_code=503,
                content={"status": "error", "dependencies": dependencies},
            )
        return JSONResponse(status_code=200, content={"status": "ok", "dependencies": dependencies})

    return application


app = create_app()
