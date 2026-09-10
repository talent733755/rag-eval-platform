"""Bounded PDF text extraction."""

from __future__ import annotations

import io
import time

from pypdf import PdfReader

from rag_eval_api.parsers.errors import MalformedDocumentError, ParserLimitExceeded
from rag_eval_api.parsers.models import ParseResult, ParserLimits
from rag_eval_api.parsers.protocol import normalize_text
from rag_eval_api.parsers.text import _finish_chunks


class PdfParser:
    parser_version = "pdf-v1"

    def parse(self, data: bytes, *, filename: str, declared_mime: str | None, limits: ParserLimits) -> ParseResult:
        del filename, declared_mime
        started = time.monotonic()
        try:
            reader = PdfReader(io.BytesIO(data), strict=True)
            page_count = len(reader.pages)
            if page_count > limits.max_pages:
                raise ParserLimitExceeded("PDF page count exceeds the configured limit")
            blocks: list[tuple[str, dict[str, int], str | None]] = []
            for page_number, page in enumerate(reader.pages, start=1):
                if time.monotonic() - started > limits.max_pdf_wall_clock_seconds:
                    raise ParserLimitExceeded("PDF parsing exceeded the wall-clock limit")
                text = normalize_text(page.extract_text() or "")
                if text:
                    blocks.append((text, {"page": page_number}, None))
            return _finish_chunks(
                blocks,
                data=data,
                parser_version=self.parser_version,
                limits=limits,
                page_count=page_count,
            )
        except ParserLimitExceeded:
            raise
        except Exception as exc:
            raise MalformedDocumentError("PDF could not be parsed safely") from exc
