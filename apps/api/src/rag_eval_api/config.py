"""Application configuration and environment validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

APP_ENV_DEVELOPMENT: Literal["development"] = "development"
DEFAULT_DATABASE_URL = "postgresql+asyncpg://rag_eval:change-me@localhost:5432/rag_eval"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_SECRET_KEY = "development-only-secret"
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

    @model_validator(mode="after")
    def validate_environment(self) -> Settings:
        secret = self.secret_key.get_secret_value().strip()
        if self.app_env != APP_ENV_DEVELOPMENT:
            if not secret or secret == DEFAULT_SECRET_KEY or len(secret) < 32:
                raise ValueError(
                    "SECRET_KEY must be a non-default value of at least 32 characters "
                    "outside development"
                )
            if self.database_url == DEFAULT_DATABASE_URL or self.redis_url == DEFAULT_REDIS_URL:
                raise ValueError("local database and Redis defaults are only allowed in development")
        return self


def get_settings() -> Settings:
    """Create settings for the application process."""

    return Settings()
