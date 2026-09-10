"""Allowlisted parser registry and input signature validation."""

from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath
from typing import BinaryIO

from rag_eval_api.parsers.docx import DocxParser
from rag_eval_api.parsers.errors import (
    MalformedDocumentError,
    ParserError,
    UnsupportedDocumentError,
)
from rag_eval_api.parsers.models import ParseResult, ParserLimits
from rag_eval_api.parsers.pdf import PdfParser
from rag_eval_api.parsers.protocol import DocumentParser, read_bounded, source_name
from rag_eval_api.parsers.text import MarkdownParser, TextParser

_MIME_BY_EXTENSION = {
    ".pdf": frozenset({"application/pdf"}),
    ".docx": frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
    ".md": frozenset({"text/markdown", "text/plain", "text/x-markdown"}),
    ".markdown": frozenset({"text/markdown", "text/plain", "text/x-markdown"}),
    ".txt": frozenset({"text/plain"}),
}


class ParserRegistry:
    """Dispatch only to built-in parsers after extension, MIME and signature checks."""

    def __init__(self) -> None:
        self._parsers: dict[str, DocumentParser] = {
            ".pdf": PdfParser(),
            ".docx": DocxParser(),
            ".md": MarkdownParser(),
            ".markdown": MarkdownParser(),
            ".txt": TextParser(),
        }

    def parse(
        self,
        source: BinaryIO,
        *,
        filename: str,
        declared_mime: str | None = None,
        limits: ParserLimits | None = None,
    ) -> ParseResult:
        effective_limits = limits or ParserLimits()
        safe_filename = source_name(filename)
        suffix = PurePosixPath(safe_filename).suffix.lower()
        parser = self._parsers.get(suffix)
        if parser is None:
            raise UnsupportedDocumentError("file extension is not allowlisted")
        normalized_mime = (
            (declared_mime or mimetypes.guess_type(safe_filename)[0] or "")
            .split(";", 1)[0]
            .strip()
            .lower()
        )
        allowed_mimes = _MIME_BY_EXTENSION[suffix]
        if normalized_mime and normalized_mime not in allowed_mimes:
            raise UnsupportedDocumentError("declared MIME does not match the file extension")
        data = read_bounded(source, max_bytes=effective_limits.max_input_bytes)
        self._validate_signature(suffix, data)
        try:
            return parser.parse(
                data,
                filename=safe_filename,
                declared_mime=normalized_mime or None,
                limits=effective_limits,
            )
        except ParserError:
            raise
        except Exception as exc:
            raise MalformedDocumentError("document could not be parsed safely") from exc

    @staticmethod
    def _validate_signature(suffix: str, data: bytes) -> None:
        if suffix == ".pdf" and not data.startswith(b"%PDF-"):
            raise UnsupportedDocumentError("PDF signature does not match extension")
        if suffix == ".docx":
            if not data.startswith(b"PK"):
                raise UnsupportedDocumentError("DOCX ZIP signature does not match extension")
        elif suffix in {".txt", ".md", ".markdown"}:
            if b"\x00" in data:
                raise UnsupportedDocumentError("text input contains binary data")
