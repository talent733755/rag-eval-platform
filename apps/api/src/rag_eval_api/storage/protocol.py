"""Storage backend protocol used by ingestion services."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from io import BufferedReader
from typing import BinaryIO, Protocol


@dataclass(frozen=True, slots=True)
class StoredBlob:
    """Metadata returned after an atomic blob commit."""

    storage_key: str
    byte_size: int
    sha256: str


class BlobStore(Protocol):
    """Minimal backend contract; implementations must never expose a root path."""

    def put(
        self,
        source: BinaryIO,
        *,
        expected_sha256: str | None = None,
        max_bytes: int | None = None,
    ) -> StoredBlob: ...

    def open(self, storage_key: str) -> AbstractContextManager[BufferedReader]: ...

    def exists(self, storage_key: str) -> bool: ...

    def delete(self, storage_key: str) -> None: ...
