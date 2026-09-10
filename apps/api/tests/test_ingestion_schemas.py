import pytest
from pydantic import ValidationError

from rag_eval_api.schemas.ingestion import DocumentContentIdentity


def test_sha256_identity_requires_lowercase_64_hex() -> None:
    identity = DocumentContentIdentity(sha256="a" * 64, byte_size=1)
    assert identity.sha256 == "a" * 64

    with pytest.raises(ValidationError):
        DocumentContentIdentity(sha256="A" * 64, byte_size=1)
    with pytest.raises(ValidationError):
        DocumentContentIdentity(sha256="a" * 63, byte_size=1)
