"""Application configuration and environment validation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from rag_eval_api.parsers.models import ParserLimits

APP_ENV_DEVELOPMENT: Literal["development"] = "development"
DEFAULT_DATABASE_URL = "postgresql+asyncpg://rag_eval:change-me@localhost:5432/rag_eval"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_SECRET_KEY = "development-only-secret"
DEFAULT_BLOB_ROOT = "/var/lib/rag-eval/blobs"
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_PARSE_PAGES = 10_000
DEFAULT_MAX_NORMALIZED_CHARACTERS = 200_000
LOGGER_NAME = "rag_eval_api.request"
SUPPORTED_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"})


def repository_env_file() -> Path:
    """Return the root ``.env`` path when running from the source checkout."""

    current_file = Path(__file__).resolve()
    for parent in current_file.parents:
        if (parent / "apps" / "api" / "pyproject.toml").is_file():
            return parent / ".env"
    return Path(".env")


class Settings(BaseSettings):
    """Validated settings loaded from environment variables and optional ``.env``."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=repository_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: Annotated[
        str,
        Field(validation_alias=AliasChoices("DATABASE_URL", "database_url")),
    ] = DEFAULT_DATABASE_URL
    redis_url: Annotated[
        str,
        Field(validation_alias=AliasChoices("REDIS_URL", "redis_url")),
    ] = DEFAULT_REDIS_URL
    app_env: Annotated[
        Literal["development", "staging", "production"],
        Field(validation_alias=AliasChoices("APP_ENV", "app_env")),
    ] = APP_ENV_DEVELOPMENT
    cors_origins: Annotated[
        list[str],
        NoDecode,
        Field(validation_alias=AliasChoices("CORS_ORIGINS", "cors_origins")),
    ] = ["http://localhost:3000"]
    log_level: Annotated[
        str,
        Field(validation_alias=AliasChoices("LOG_LEVEL", "log_level")),
    ] = "INFO"
    secret_key: Annotated[
        SecretStr,
        Field(validation_alias=AliasChoices("SECRET_KEY", "secret_key")),
    ] = SecretStr(DEFAULT_SECRET_KEY)
    blob_root: Annotated[
        str,
        Field(validation_alias=AliasChoices("BLOB_ROOT", "blob_root")),
    ] = DEFAULT_BLOB_ROOT
    max_upload_bytes: Annotated[
        int,
        Field(
            ge=1,
            le=500 * 1024 * 1024,
            validation_alias=AliasChoices("MAX_UPLOAD_BYTES", "max_upload_bytes"),
        ),
    ] = DEFAULT_MAX_UPLOAD_BYTES
    max_parse_pages: Annotated[
        int,
        Field(
            ge=1, le=100_000, validation_alias=AliasChoices("MAX_PARSE_PAGES", "max_parse_pages")
        ),
    ] = DEFAULT_MAX_PARSE_PAGES
    max_normalized_characters: Annotated[
        int,
        Field(
            ge=1,
            le=10_000_000,
            validation_alias=AliasChoices("MAX_NORMALIZED_CHARACTERS", "max_normalized_characters"),
        ),
    ] = DEFAULT_MAX_NORMALIZED_CHARACTERS
    max_parse_paragraphs: Annotated[
        int,
        Field(
            ge=1,
            le=1_000_000,
            validation_alias=AliasChoices("MAX_PARSE_PARAGRAPHS", "max_parse_paragraphs"),
        ),
    ] = 100_000
    max_chunk_characters: Annotated[
        int,
        Field(
            ge=1,
            le=100_000,
            validation_alias=AliasChoices("MAX_CHUNK_CHARACTERS", "max_chunk_characters"),
        ),
    ] = 2_000
    max_pdf_objects: Annotated[
        int,
        Field(
            ge=1, le=1_000_000, validation_alias=AliasChoices("MAX_PDF_OBJECTS", "max_pdf_objects")
        ),
    ] = 100_000
    max_pdf_decoded_stream_bytes: Annotated[
        int,
        Field(
            ge=1,
            le=1_000 * 1024 * 1024,
            validation_alias=AliasChoices(
                "MAX_PDF_DECODED_STREAM_BYTES", "max_pdf_decoded_stream_bytes"
            ),
        ),
    ] = 100 * 1024 * 1024
    max_pdf_recursion_depth: Annotated[
        int,
        Field(
            ge=1,
            le=1_000,
            validation_alias=AliasChoices("MAX_PDF_RECURSION_DEPTH", "max_pdf_recursion_depth"),
        ),
    ] = 100
    max_pdf_recursion_objects: Annotated[
        int,
        Field(
            ge=1,
            le=1_000_000,
            validation_alias=AliasChoices("MAX_PDF_RECURSION_OBJECTS", "max_pdf_recursion_objects"),
        ),
    ] = 100_000
    parser_require_resource_limits: Annotated[
        bool,
        Field(
            validation_alias=AliasChoices(
                "PARSER_REQUIRE_RESOURCE_LIMITS", "parser_require_resource_limits"
            )
        ),
    ] = False
    parser_sandbox_executable: Annotated[
        str | None,
        Field(
            validation_alias=AliasChoices("PARSER_SANDBOX_EXECUTABLE", "parser_sandbox_executable")
        ),
    ] = None
    parser_sandbox_args: Annotated[
        list[str],
        NoDecode,
        Field(validation_alias=AliasChoices("PARSER_SANDBOX_ARGS", "parser_sandbox_args")),
    ] = []
    max_parser_wall_clock_seconds: Annotated[
        int,
        Field(
            ge=1,
            le=300,
            validation_alias=AliasChoices(
                "MAX_PARSER_WALL_CLOCK_SECONDS", "max_parser_wall_clock_seconds"
            ),
        ),
    ] = 10
    max_docx_zip_entries: Annotated[
        int,
        Field(
            ge=1,
            le=100_000,
            validation_alias=AliasChoices("MAX_DOCX_ZIP_ENTRIES", "max_docx_zip_entries"),
        ),
    ] = 10_000
    max_docx_uncompressed_bytes: Annotated[
        int,
        Field(
            ge=1,
            le=1_000_000_000,
            validation_alias=AliasChoices(
                "MAX_DOCX_UNCOMPRESSED_BYTES", "max_docx_uncompressed_bytes"
            ),
        ),
    ] = 100 * 1024 * 1024
    max_docx_compression_ratio: Annotated[
        float,
        Field(
            ge=1,
            le=1_000,
            validation_alias=AliasChoices(
                "MAX_DOCX_COMPRESSION_RATIO", "max_docx_compression_ratio"
            ),
        ),
    ] = 100.0
    max_docx_xml_depth: Annotated[
        int,
        Field(
            ge=1,
            le=10_000,
            validation_alias=AliasChoices("MAX_DOCX_XML_DEPTH", "max_docx_xml_depth"),
        ),
    ] = 100
    worker_batch_size: Annotated[
        int,
        Field(
            ge=1, le=100, validation_alias=AliasChoices("WORKER_BATCH_SIZE", "worker_batch_size")
        ),
    ] = 10
    worker_lease_ttl_seconds: Annotated[
        int,
        Field(
            ge=10,
            le=3600,
            validation_alias=AliasChoices("WORKER_LEASE_TTL_SECONDS", "worker_lease_ttl_seconds"),
        ),
    ] = 60
    worker_heartbeat_interval_seconds: Annotated[
        int,
        Field(
            ge=1,
            le=120,
            validation_alias=AliasChoices(
                "WORKER_HEARTBEAT_INTERVAL_SECONDS", "worker_heartbeat_interval_seconds"
            ),
        ),
    ] = 20
    provider_base_url: Annotated[
        str | None,
        Field(validation_alias=AliasChoices("PROVIDER_BASE_URL", "provider_base_url")),
    ] = None
    provider_api_key: Annotated[
        SecretStr | None,
        Field(validation_alias=AliasChoices("PROVIDER_API_KEY", "provider_api_key")),
    ] = None
    provider_timeout_seconds: Annotated[
        int,
        Field(
            ge=1,
            le=300,
            validation_alias=AliasChoices("PROVIDER_TIMEOUT_SECONDS", "provider_timeout_seconds"),
        ),
    ] = 30
    provider_allowed_hosts: Annotated[
        list[str],
        NoDecode,
        Field(validation_alias=AliasChoices("PROVIDER_ALLOWED_HOSTS", "provider_allowed_hosts")),
    ] = []
    provider_allowed_ports: Annotated[
        list[int],
        NoDecode,
        Field(validation_alias=AliasChoices("PROVIDER_ALLOWED_PORTS", "provider_allowed_ports")),
    ] = []
    dev_actor_id: Annotated[
        UUID | None,
        Field(validation_alias=AliasChoices("DEV_ACTOR_ID", "dev_actor_id")),
    ] = None

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "postgresql+asyncpg" or not parsed.netloc:
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg scheme")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"redis", "rediss"} or not parsed.netloc:
            raise ValueError("REDIS_URL must use the redis or rediss scheme")
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("LOG_LEVEL must be a supported logging level")
        normalized = value.strip().upper()
        normalized = {"WARN": "WARNING", "FATAL": "CRITICAL"}.get(normalized, normalized)
        if normalized not in SUPPORTED_LOG_LEVELS:
            raise ValueError("LOG_LEVEL must be a supported logging level")
        return normalized

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> list[str]:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if not isinstance(parsed, list):
                    raise ValueError("CORS_ORIGINS JSON value must be a list")
                value = parsed
            else:
                value = stripped.split(",")
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return [item.strip() for item in value if item.strip()]
        raise ValueError("CORS_ORIGINS must be a comma-separated string or list")

    @field_validator("provider_allowed_hosts", mode="before")
    @classmethod
    def parse_provider_allowed_hosts(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return [item.strip().lower() for item in value if item.strip()]
        raise ValueError("PROVIDER_ALLOWED_HOSTS must be a comma-separated string or list")

    @field_validator("provider_allowed_ports", mode="before")
    @classmethod
    def parse_provider_allowed_ports(cls, value: object) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list):
            try:
                ports = [int(item) for item in value]
            except (TypeError, ValueError) as exc:
                raise ValueError("PROVIDER_ALLOWED_PORTS must contain integers") from exc
            if all(1 <= port <= 65535 for port in ports):
                return ports
        raise ValueError("PROVIDER_ALLOWED_PORTS must contain valid TCP ports")

    @field_validator("parser_sandbox_args", mode="before")
    @classmethod
    def parse_parser_sandbox_args(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                value = parsed
            else:
                value = stripped.split()
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return value
        raise ValueError("PARSER_SANDBOX_ARGS must be a JSON array or space-separated string")

    @field_validator("provider_base_url", mode="before")
    @classmethod
    def validate_provider_url(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError(
                "PROVIDER_BASE_URL must be an absolute HTTP(S) URL without credentials"
            )
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "PROVIDER_BASE_URL must be an absolute HTTP(S) URL without credentials"
            )
        return value.rstrip("/")

    @field_validator("provider_api_key", mode="before")
    @classmethod
    def normalize_provider_api_key(cls, value: object) -> object:
        return None if value is None or value == "" else value

    @model_validator(mode="after")
    def validate_environment(self) -> Settings:
        secret = self.secret_key.get_secret_value().strip()
        blob_raw = os.fspath(self.blob_root)
        blob_path = Path(os.path.normpath(os.sep + blob_raw.lstrip(os.sep)))
        resolved_blob_path = Path(os.path.realpath(blob_path))
        temporary_roots = (
            Path("/tmp"),
            Path("/var/tmp"),
            Path("/private/tmp"),
            Path("/private/var/tmp"),
        )

        def is_under(path: Path, root: Path) -> bool:
            try:
                return os.path.commonpath((path, root)) == str(root)
            except ValueError:
                return False

        if (
            not os.path.isabs(blob_raw)
            or resolved_blob_path == Path("/")
            or any(is_under(resolved_blob_path, root) for root in temporary_roots)
        ):
            raise ValueError("BLOB_ROOT must be an absolute private non-temporary path")
        self.blob_root = str(blob_path)
        if self.worker_heartbeat_interval_seconds >= self.worker_lease_ttl_seconds:
            raise ValueError("WORKER_HEARTBEAT_INTERVAL_SECONDS must be less than lease TTL")
        if "*" in self.provider_allowed_hosts:
            raise ValueError("PROVIDER_ALLOWED_HOSTS cannot contain wildcard entries")
        if self.provider_base_url is not None:
            parsed_provider_url = urlsplit(self.provider_base_url)
            if self.app_env != APP_ENV_DEVELOPMENT and parsed_provider_url.scheme != "https":
                raise ValueError("PROVIDER_BASE_URL must use HTTPS outside development")
            if not self.provider_allowed_hosts or not self.provider_allowed_ports:
                raise ValueError(
                    "provider host and port allowlists are required when provider is enabled"
                )
            provider_hostname = parsed_provider_url.hostname
            if provider_hostname is None:
                raise ValueError("PROVIDER_BASE_URL must include a hostname")
            if provider_hostname.lower() not in self.provider_allowed_hosts:
                raise ValueError("PROVIDER_BASE_URL hostname must be in PROVIDER_ALLOWED_HOSTS")
            try:
                provider_port = parsed_provider_url.port
            except ValueError as exc:
                raise ValueError("PROVIDER_BASE_URL has an invalid port") from exc
            effective_port = provider_port or (443 if parsed_provider_url.scheme == "https" else 80)
            if effective_port not in self.provider_allowed_ports:
                raise ValueError("PROVIDER_BASE_URL port must be in PROVIDER_ALLOWED_PORTS")
        if self.provider_base_url is not None and self.provider_api_key is None:
            raise ValueError("PROVIDER_API_KEY is required when provider is enabled")
        if self.dev_actor_id is not None and self.app_env != APP_ENV_DEVELOPMENT:
            raise ValueError("DEV_ACTOR_ID is only allowed in development")
        if self.app_env != APP_ENV_DEVELOPMENT:
            if not secret or secret == DEFAULT_SECRET_KEY or len(secret) < 32:
                raise ValueError(
                    "SECRET_KEY must be a non-default value of at least 32 characters "
                    "outside development"
                )
            if self.database_url == DEFAULT_DATABASE_URL or self.redis_url == DEFAULT_REDIS_URL:
                raise ValueError(
                    "local database and Redis defaults are only allowed in development"
                )
        from rag_eval_api.parsers.runner import (
            restricted_sandbox_available,
            sandbox_command_available,
        )

        strict_parser_sandbox = self.app_env == "production" or self.parser_require_resource_limits
        if strict_parser_sandbox and (
            not sandbox_command_available(self.parser_sandbox_executable, self.parser_sandbox_args)
            or not restricted_sandbox_available()
        ):
            raise ValueError(
                "production requires an explicit parser sandbox executable with CPU and memory limits"
            )
        return self

    def parser_limits(self) -> ParserLimits:
        """Return parser bounds without coupling parser modules to settings loading."""

        return ParserLimits(
            max_input_bytes=self.max_upload_bytes,
            max_pages=self.max_parse_pages,
            max_paragraphs=self.max_parse_paragraphs,
            max_normalized_characters=self.max_normalized_characters,
            max_chunk_characters=self.max_chunk_characters,
            max_pdf_wall_clock_seconds=float(self.max_parser_wall_clock_seconds),
            max_pdf_objects=self.max_pdf_objects,
            max_pdf_decoded_stream_bytes=self.max_pdf_decoded_stream_bytes,
            max_pdf_recursion_depth=self.max_pdf_recursion_depth,
            max_pdf_recursion_objects=self.max_pdf_recursion_objects,
            max_docx_zip_entries=self.max_docx_zip_entries,
            max_docx_uncompressed_bytes=self.max_docx_uncompressed_bytes,
            max_docx_compression_ratio=self.max_docx_compression_ratio,
            max_docx_xml_depth=self.max_docx_xml_depth,
        )


def get_settings() -> Settings:
    """Create settings for the application process."""

    return Settings()
