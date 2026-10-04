"""FastAPI application entry point and dependency health endpoints."""

from __future__ import annotations

import asyncio
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
from starlette.exceptions import HTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware

from rag_eval_api.config import LOGGER_NAME, Settings, get_settings
from rag_eval_api.db import (
    close_resources,
    configure_database,
    configure_redis,
    get_db_session,
    get_redis_client,
)
from rag_eval_api.log_sanitize import redact_text as _redact_text_impl
from rag_eval_api.log_sanitize import sanitize_exception
from rag_eval_api.middleware import RequestBodyLimitMiddleware
from rag_eval_api.routes.adapters import router as adapters_router
from rag_eval_api.routes.candidate_datasets import router as candidate_datasets_router
from rag_eval_api.routes.candidates import router as candidates_router
from rag_eval_api.routes.documents import job_router as ingestion_jobs_router
from rag_eval_api.routes.documents import router as documents_router
from rag_eval_api.routes.experiments import router as experiments_router
from rag_eval_api.routes.metrics import router as metrics_router
from rag_eval_api.routes.model_providers import router as model_providers_router
from rag_eval_api.routes.projects import router as projects_router
from rag_eval_api.routes.regression_cases import router as regression_cases_router
from rag_eval_api.routes.traces import router as traces_router
from rag_eval_api.storage.local import LocalBlobStore
from rag_eval_api.storage.protocol import BlobStore

HEALTH_CHECK_TIMEOUT_SECONDS = 2.0
logger = logging.getLogger(LOGGER_NAME)

# Unified structured log fields for API, Worker, Provider and Adapter events.
# Any field outside this allowlist is dropped; secrets are always redacted.
STRUCTURED_LOG_FIELDS = (
    "method",
    "path",
    "status_code",
    "duration_ms",
    "exception_type",
    "exception_message",
    "error_code",
    "error_message",
    "resource",
    "project_id",
    "organization_id",
    "document_id",
    "document_version_id",
    "job_id",
    "job_kind",
    "run_id",
    "run_item_id",
    "attempt_id",
    "attempt_number",
    "lease_id",
    "fencing_token",
    "trace_id",
    "storage_key",
    "storage_key_present",
    "blob_size",
    "orphan_blobs_scanned",
    "orphan_blobs_deleted",
    "recovered_jobs",
    "failed_count",
    "cleanup_failed",
)

# Free-form fields that may carry untrusted text and must be redacted.
_REDACTED_TEXT_FIELDS = {"error_message"}


class JsonLogFormatter(logging.Formatter):
    """Render structured records as compact JSON with secret redaction."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "event": getattr(record, "event", record.getMessage()),
            "logger": record.name,
            "level": record.levelname,
        }
        for field in STRUCTURED_LOG_FIELDS:
            value = getattr(record, field, None)
            if value is None:
                continue
            if field in _REDACTED_TEXT_FIELDS:
                value = _redact_text(str(value))
            payload[field] = value
        return json.dumps(payload, separators=(",", ":"))


def _redact_text(text: str) -> str:
    return _redact_text_impl(text)


def configure_logging(settings: Settings) -> None:
    logger.setLevel(settings.log_level.upper())
    package_logger = logging.getLogger("rag_eval_api")
    package_logger.setLevel(settings.log_level.upper())
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    if not package_logger.handlers:
        package_handler = logging.StreamHandler()
        package_handler.setFormatter(JsonLogFormatter())
        package_logger.addHandler(package_handler)
    logger.propagate = False


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    try:
        if not hasattr(application.state, "blob_store"):
            settings = application.state.settings
            application.state.blob_store = LocalBlobStore(
                settings.blob_root,
                max_bytes=settings.max_upload_bytes,
            )
            application.state.blob_store_owned = True
        yield
    finally:
        await close_resources(application)


def _error_payload(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def create_app(settings: Settings | None = None, blob_store: BlobStore | None = None) -> FastAPI:
    configured_settings = settings or get_settings()
    configure_logging(configured_settings)
    application = FastAPI(
        title="RAG Eval Platform API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = configured_settings
    if configured_settings.auth_mode == "oidc":
        from rag_eval_api.auth.context import OIDC_VERIFIER_STATE_KEY
        from rag_eval_api.auth.jwks import HttpJwksFetcher
        from rag_eval_api.auth.oidc import OidcVerifier

        assert configured_settings.auth_oidc_jwks_url is not None
        assert configured_settings.auth_oidc_issuer is not None
        assert configured_settings.auth_oidc_audience is not None
        jwks_fetcher = HttpJwksFetcher(
            configured_settings.auth_oidc_jwks_url,
            cache_seconds=configured_settings.auth_oidc_jwks_cache_seconds,
        )
        setattr(
            application.state,
            OIDC_VERIFIER_STATE_KEY,
            OidcVerifier(
                jwks_source=jwks_fetcher.fetch,
                issuer=configured_settings.auth_oidc_issuer,
                audience=configured_settings.auth_oidc_audience,
                leeway_seconds=configured_settings.auth_jwt_leeway_seconds,
            ),
        )
    if blob_store is not None:
        application.state.blob_store = blob_store
        application.state.blob_store_owned = False
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
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            logger.error(
                "request.failed",
                extra={
                    "event": "request.failed",
                    "method": request.method,
                    "path": request.url.path,
                    "exception_type": type(exc).__name__,
                    "exception_message": sanitize_exception(exc),
                },
            )
            raise
        finally:
            logger.info(
                "request.completed",
                extra={
                    "event": "request.completed",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code if response is not None else 500,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )

    # Keep this outermost so a receive-time limit violation cannot be converted
    # into a multipart parser error by an inner middleware.
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=configured_settings.max_request_body_bytes,
    )

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

    @application.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        del request
        if exc.status_code == 403:
            return JSONResponse(
                status_code=403,
                content=_error_payload(
                    "permission_denied", "You do not have permission to perform this action."
                ),
            )
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        error_codes = {
            404: "not_found",
            405: "method_not_allowed",
            409: "conflict",
            501: "not_implemented",
        }
        messages = {
            404: "Resource not found.",
            405: "Method not allowed.",
            409: "Request conflicts with existing data.",
            501: "Not implemented.",
        }
        code = error_codes.get(exc.status_code, "http_error")
        message = messages.get(exc.status_code, str(exc.detail))
        return JSONResponse(status_code=exc.status_code, content=_error_payload(code, message))

    @application.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "request.unhandled",
            extra={
                "event": "request.unhandled",
                "method": request.method,
                "path": request.url.path,
                "exception_type": type(exc).__name__,
                "exception_message": sanitize_exception(exc),
            },
        )
        return JSONResponse(
            status_code=500,
            content=_error_payload("internal_server_error", "Internal server error"),
        )

    application.include_router(projects_router)
    application.include_router(documents_router)
    application.include_router(ingestion_jobs_router)
    application.include_router(candidates_router)
    application.include_router(candidate_datasets_router)
    application.include_router(adapters_router)
    application.include_router(model_providers_router)
    application.include_router(experiments_router)
    application.include_router(metrics_router)
    application.include_router(traces_router)
    application.include_router(regression_cases_router)

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
            await asyncio.wait_for(
                db_session.execute(text("SELECT 1")),
                timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
            )
        except Exception:
            database_status = "error"
        try:
            await asyncio.wait_for(redis_client.ping(), timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
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
