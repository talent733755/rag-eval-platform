"""Canonical parser output and bounded parser configuration."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ParserLimits:
    """Hard parser bounds; callers may lower them but not raise safe defaults."""

    max_input_bytes: int = 50 * 1024 * 1024
    max_pages: int = 10_000
    max_paragraphs: int = 100_000
    max_normalized_characters: int = 200_000
    max_chunk_characters: int = 2_000
    max_pdf_wall_clock_seconds: float = 10.0
    max_docx_zip_entries: int = 10_000
    max_docx_uncompressed_bytes: int = 100 * 1024 * 1024
    max_docx_compression_ratio: float = 100.0
    max_docx_xml_depth: int = 100

    def __post_init__(self) -> None:
        for name in (
            "max_input_bytes",
            "max_pages",
            "max_paragraphs",
            "max_normalized_characters",
            "max_chunk_characters",
            "max_docx_zip_entries",
            "max_docx_uncompressed_bytes",
            "max_docx_xml_depth",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        if self.max_pdf_wall_clock_seconds <= 0 or self.max_docx_compression_ratio < 1:
            raise ValueError("parser floating point limits are invalid")


@dataclass(frozen=True, slots=True)
class CanonicalChunk:
    """A deterministic, source-locatable normalized chunk."""

    ordinal: int
    content: str
    content_hash: str
    character_count: int
    token_count: int
    source_location: dict[str, int]
    heading: str | None = None

    @classmethod
    def create(
        cls,
        *,
        ordinal: int,
        content: str,
        source_location: Mapping[str, int],
        heading: str | None = None,
    ) -> CanonicalChunk:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return cls(
            ordinal=ordinal,
            content=content,
            content_hash=digest,
            character_count=len(content),
            token_count=len(re.findall(r"\S+", content)),
            source_location=dict(source_location),
            heading=heading,
        )


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Parser output consumed by the ingestion job and persistence layer."""

    parser_version: str
    content_hash: str
    byte_size: int
    page_count: int
    paragraph_count: int
    chunks: tuple[CanonicalChunk, ...] = field(default_factory=tuple)
