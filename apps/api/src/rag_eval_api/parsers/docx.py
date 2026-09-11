"""Bounded DOCX parser with ZIP and XML safety checks."""

from __future__ import annotations

import io
import stat
import time
import xml.etree.ElementTree as ET
import zipfile

from docx import Document

from rag_eval_api.parsers.errors import (
    MalformedDocumentError,
    ParserLimitExceeded,
    ParserSecurityError,
    ParserTimeout,
)
from rag_eval_api.parsers.models import ParseResult, ParserLimits
from rag_eval_api.parsers.protocol import normalize_text
from rag_eval_api.parsers.text import _finish_chunks


class DocxParser:
    parser_version = "docx-v1"

    def parse(
        self, data: bytes, *, filename: str, declared_mime: str | None, limits: ParserLimits
    ) -> ParseResult:
        del filename, declared_mime
        self._validate_zip(data, limits)
        try:
            document = Document(io.BytesIO(data))
        except Exception as exc:
            raise MalformedDocumentError("DOCX could not be parsed safely") from exc
        blocks: list[tuple[str, dict[str, int], str | None]] = []
        for index, paragraph in enumerate(document.paragraphs):
            content = normalize_text(paragraph.text)
            if not content:
                continue
            style_name = paragraph.style.name if paragraph.style is not None else ""
            heading = content if style_name.lower().startswith("heading") else None
            blocks.append((content, {"paragraph": index}, heading))
            if len(blocks) > limits.max_paragraphs:
                raise ParserLimitExceeded("paragraph count exceeds the configured limit")
        return _finish_chunks(blocks, data=data, parser_version=self.parser_version, limits=limits)

    @staticmethod
    def _validate_zip(data: bytes, limits: ParserLimits) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = archive.infolist()
                if len(infos) > limits.max_docx_zip_entries:
                    raise ParserLimitExceeded("DOCX ZIP entry count exceeds the configured limit")
                if "[Content_Types].xml" not in archive.namelist():
                    raise MalformedDocumentError("DOCX ZIP is missing content types")
                total_uncompressed = 0
                started = time.monotonic()
                for info in infos:
                    name = info.filename.replace("\\", "/")
                    path = name.lstrip("/")
                    if (
                        name.startswith("/")
                        or path != name
                        or any(part == ".." for part in name.split("/"))
                    ):
                        raise ParserSecurityError("DOCX ZIP contains an unsafe path")
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode == stat.S_IFLNK:
                        raise ParserSecurityError("DOCX ZIP contains a symlink")
                    total_uncompressed += info.file_size
                    if total_uncompressed > limits.max_docx_uncompressed_bytes:
                        raise ParserLimitExceeded(
                            "DOCX uncompressed size exceeds the configured limit"
                        )
                    compressed = max(info.compress_size, 1)
                    if info.file_size / compressed > limits.max_docx_compression_ratio:
                        raise ParserLimitExceeded(
                            "DOCX compression ratio exceeds the configured limit"
                        )
                    if time.monotonic() - started > limits.max_pdf_wall_clock_seconds:
                        raise ParserTimeout("DOCX parsing exceeded the wall-clock limit")
                    if name.lower().endswith(".xml"):
                        with archive.open(info, "r") as xml_file:
                            xml_data = xml_file.read(limits.max_docx_uncompressed_bytes + 1)
                        try:
                            depth = 0
                            for event, _ in ET.iterparse(
                                io.BytesIO(xml_data), events=("start", "end")
                            ):
                                depth += 1 if event == "start" else -1
                                if depth > limits.max_docx_xml_depth:
                                    raise ParserLimitExceeded(
                                        "DOCX XML depth exceeds the configured limit"
                                    )
                        except ParserLimitExceeded:
                            raise
                        except (ET.ParseError, ValueError) as exc:
                            raise MalformedDocumentError("DOCX XML is malformed") from exc
        except (ParserLimitExceeded, ParserSecurityError, MalformedDocumentError, ParserTimeout):
            raise
        except (zipfile.BadZipFile, OSError, ValueError) as exc:
            raise MalformedDocumentError("DOCX ZIP is malformed") from exc
