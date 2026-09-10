"""Bounded PDF text extraction."""

from __future__ import annotations

import io
import time

from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject

from rag_eval_api.parsers.errors import MalformedDocumentError, ParserLimitExceeded, ParserTimeout
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
            _validate_object_graph(reader, limits)
            page_count = len(reader.pages)
            if page_count > limits.max_pages:
                raise ParserLimitExceeded("PDF page count exceeds the configured limit")
            blocks: list[tuple[str, dict[str, int], str | None]] = []
            decoded_stream_bytes = 0
            for page_number, page in enumerate(reader.pages, start=1):
                if time.monotonic() - started > limits.max_pdf_wall_clock_seconds:
                    raise ParserTimeout("PDF parsing exceeded the wall-clock limit")
                contents = page.get_contents()
                if contents is not None:
                    decoded_stream_bytes += len(contents.get_data())
                    if decoded_stream_bytes > limits.max_pdf_decoded_stream_bytes:
                        raise ParserLimitExceeded(
                            "PDF decoded stream bytes exceed the configured limit"
                        )
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


def _validate_object_graph(reader: PdfReader, limits: ParserLimits) -> None:
    """Bound indirect-object traversal before page text extraction."""

    seen: set[tuple[int, int]] = set()
    stream_bytes = 0

    def visit(value: object, depth: int) -> None:
        nonlocal stream_bytes
        if depth > limits.max_pdf_recursion_depth:
            raise ParserLimitExceeded("PDF object recursion depth exceeds the configured limit")
        if isinstance(value, IndirectObject):
            identity = (value.idnum, value.generation)
            if identity in seen:
                return
            seen.add(identity)
            if len(seen) > limits.max_pdf_recursion_objects:
                raise ParserLimitExceeded("PDF object count exceeds the configured limit")
            visit(value.get_object(), depth + 1)
            return
        if isinstance(value, StreamObject):
            decoded = value.get_data()
            stream_bytes += len(decoded)
            if stream_bytes > limits.max_pdf_decoded_stream_bytes:
                raise ParserLimitExceeded("PDF decoded stream bytes exceed the configured limit")
        if isinstance(value, DictionaryObject):
            for child in value.values():
                visit(child, depth + 1)
        elif isinstance(value, ArrayObject):
            for child in value:
                visit(child, depth + 1)

    visit(reader.trailer, 0)
    if len(seen) > limits.max_pdf_objects:
        raise ParserLimitExceeded("PDF object count exceeds the configured limit")
