"""Typed public value objects used by the document ingestion contract."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class DocumentContentIdentity(BaseModel):
    """The project-scoped content identity used for duplicate detection."""

    sha256: Sha256Hex
    byte_size: int = Field(gt=0)
