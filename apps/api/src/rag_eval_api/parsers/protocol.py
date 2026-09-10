"""Public parser protocol and shared normalization helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Protocol

from rag_eval_api.parsers.models import ParseResult, ParserLimits


class DocumentParser(Protocol):
    """Format parser contract; implementations never perform network I/O."""

    parser_version: str

    def parse(
        self,
        data: bytes,
        *,
        filename: str,
        declared_mime: str | None,
        limits: ParserLimits,
    ) -> ParseResult: ...


def read_bounded(source: BinaryIO, *, max_bytes: int) -> bytes:
    """Read a source without allowing an unbounded in-memory upload."""

    chunks: list[bytes] = []
    total = 0
    while chunk := source.read(min(1024 * 1024, max_bytes + 1 - total)):
        if not isinstance(chunk, bytes):
            raise TypeError("parser source must return bytes")
        total += len(chunk)
        if total > max_bytes:
            from rag_eval_api.parsers.errors import ParserLimitExceeded

            raise ParserLimitExceeded("input bytes exceed the configured limit")
        chunks.append(chunk)
    return b"".join(chunks)


def normalize_text(value: str) -> str:
    """Normalize Unicode and horizontal whitespace without changing word order."""

    value = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(lines).strip()


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_name(filename: str) -> str:
    """Return only a normalized extension; never use the filename as a path."""

    return Path(filename.replace("\\", "/")).name


def as_bytes_io(data: bytes) -> BytesIO:
    return BytesIO(data)
