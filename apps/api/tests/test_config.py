import pytest
from pydantic import SecretStr

from rag_eval_api.config import Settings


def test_document_ingestion_defaults_are_safe_and_provider_is_opt_in() -> None:
    settings = Settings(_env_file=None)
    assert settings.blob_root == "/var/lib/rag-eval/blobs"
    assert settings.max_upload_bytes == 50 * 1024 * 1024
    assert settings.provider_base_url is None
    assert settings.provider_api_key is None
    assert settings.worker_lease_ttl_seconds == 60
    assert settings.parser_limits().max_docx_compression_ratio == 100


def test_production_rejects_local_blob_root_and_unconfigured_provider_allowlist() -> None:
    with pytest.raises(ValueError, match="BLOB_ROOT"):
        Settings(
            _env_file=None,
            app_env="production",
            secret_key=SecretStr("x" * 40),
            database_url="postgresql+asyncpg://app:secret@db:5432/rag_eval",
            redis_url="redis://redis:6379/0",
            blob_root="/tmp/rag-eval-blobs",
        )


def test_provider_credentials_are_not_part_of_safe_configuration_dump() -> None:
    settings = Settings(_env_file=None, provider_api_key=SecretStr("super-secret"))
    rendered = repr(settings) + str(settings.model_dump())
    assert "super-secret" not in rendered


def test_provider_url_requires_allowlisted_hostname_and_port() -> None:
    base = {
        "_env_file": None,
        "provider_api_key": SecretStr("super-secret"),
        "provider_allowed_hosts": ["api.example.com"],
        "provider_allowed_ports": [443],
    }
    assert Settings(**base, provider_base_url="https://api.example.com/v1").provider_base_url

    with pytest.raises(ValueError, match="hostname"):
        Settings(**base, provider_base_url="https://other.example.com/v1")
    with pytest.raises(ValueError, match="port"):
        Settings(**base, provider_base_url="https://api.example.com:8443/v1")


@pytest.mark.parametrize(
    "url",
    ["https://user:password@api.example.com/v1", "https://user@api.example.com/v1"],
)
def test_provider_url_rejects_embedded_credentials(url: str) -> None:
    with pytest.raises(ValueError, match="credentials"):
        Settings(
            _env_file=None,
            provider_base_url=url,
            provider_api_key=SecretStr("super-secret"),
            provider_allowed_hosts=["api.example.com"],
            provider_allowed_ports=[443],
        )
