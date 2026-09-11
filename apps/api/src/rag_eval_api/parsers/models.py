"""Canonical parser output and bounded parser configuration."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class ParserLimits:
    """Hard parser bounds; callers may lower them but not raise safe defaults."""

    max_input_bytes: int = 50 * 1024 * 1024
    max_pages: int = 10_000
    max_paragraphs: int = 100_000
    max_normalized_characters: int = 200_000
    max_chunk_characters: int = 2_000
    max_pdf_wall_clock_seconds: float = 10.0
    max_pdf_objects: int = 100_000
    max_pdf_decoded_stream_bytes: int = 100 * 1024 * 1024
    max_pdf_recursion_depth: int = 100
    max_pdf_recursion_objects: int = 100_000
    max_docx_zip_entries: int = 10_000
    max_docx_uncompressed_bytes: int = 100 * 1024 * 1024
    max_docx_compression_ratio: float = 100.0
    max_docx_xml_depth: int = 100

    _SAFE_UPPER_BOUNDS: ClassVar[dict[str, int | float]] = {
        "max_input_bytes": 1024 * 1024 * 1024,
        "max_pages": 100_000,
        "max_paragraphs": 1_000_000,
        "max_normalized_characters": 10_000_000,
        "max_chunk_characters": 100_000,
        "max_pdf_wall_clock_seconds": 300.0,
        "max_pdf_objects": 1_000_000,
        "max_pdf_decoded_stream_bytes": 1024 * 1024 * 1024,
        "max_pdf_recursion_depth": 1_000,
        "max_pdf_recursion_objects": 1_000_000,
        "max_docx_zip_entries": 100_000,
        "max_docx_uncompressed_bytes": 1_000_000_000,
        "max_docx_compression_ratio": 1_000.0,
        "max_docx_xml_depth": 10_000,
    }

    @classmethod
    def safe_upper_bounds(cls) -> dict[str, int | float]:
        return dict(cls._SAFE_UPPER_BOUNDS)

    def __post_init__(self) -> None:
        for name, upper_bound in self._SAFE_UPPER_BOUNDS.items():
            value = getattr(self, name)
            if isinstance(upper_bound, int) and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                raise ValueError(f"{name} must be an integer")
            if isinstance(upper_bound, float) and not isinstance(value, int | float):
                raise ValueError(f"{name} must be numeric")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            if value < 1:
                raise ValueError(f"{name} must be positive")
            if value > upper_bound:
                raise ValueError(f"{name} exceeds the safe upper bound")


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
