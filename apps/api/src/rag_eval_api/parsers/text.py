"""Plain text and Markdown canonical parsers."""

from __future__ import annotations

import re

from markdown_it import MarkdownIt

from rag_eval_api.parsers.errors import ParserLimitExceeded
from rag_eval_api.parsers.models import CanonicalChunk, ParseResult, ParserLimits
from rag_eval_api.parsers.protocol import content_hash, iter_utf8_lines, normalize_text


def _finish_chunks(
    blocks: list[tuple[str, dict[str, int], str | None]],
    *,
    data: bytes,
    parser_version: str,
    limits: ParserLimits,
    page_count: int = 0,
) -> ParseResult:
    chunks: list[CanonicalChunk] = []
    total_characters = 0
    paragraph_count = 0
    for content, location, heading in blocks:
        if not content:
            continue
        paragraph_count += 1
        if paragraph_count > limits.max_paragraphs:
            raise ParserLimitExceeded("paragraph count exceeds the configured limit")
        total_characters += len(content)
        if total_characters > limits.max_normalized_characters:
            raise ParserLimitExceeded("normalized characters exceed the configured limit")
        for part_index, start in enumerate(range(0, len(content), limits.max_chunk_characters)):
            part = content[start : start + limits.max_chunk_characters]
            part_location = dict(location)
            if len(content) > limits.max_chunk_characters:
                part_location["part"] = part_index
            chunks.append(
                CanonicalChunk.create(
                    ordinal=len(chunks),
                    content=part,
                    source_location=part_location,
                    heading=heading,
                )
            )
    return ParseResult(
        parser_version=parser_version,
        content_hash=content_hash(data),
        byte_size=len(data),
        page_count=page_count,
        paragraph_count=paragraph_count,
        chunks=tuple(chunks),
    )


class TextParser:
    parser_version = "txt-v1"

    def parse(
        self, data: bytes, *, filename: str, declared_mime: str | None, limits: ParserLimits
    ) -> ParseResult:
        del filename, declared_mime
        blocks: list[tuple[str, dict[str, int], str | None]] = []
        paragraph_lines: list[str] = []
        paragraph_index = 0
        for line, _line_number in iter_utf8_lines(
            data, max_decoded_characters=limits.max_normalized_characters
        ):
            normalized_line = normalize_text(line)
            if normalized_line:
                paragraph_lines.append(normalized_line)
                continue
            if paragraph_lines:
                blocks.append(("\n".join(paragraph_lines), {"paragraph": paragraph_index}, None))
                paragraph_lines = []
                paragraph_index += 1
        if paragraph_lines:
            blocks.append(("\n".join(paragraph_lines), {"paragraph": paragraph_index}, None))
        return _finish_chunks(blocks, data=data, parser_version=self.parser_version, limits=limits)


class MarkdownParser:
    parser_version = "markdown-v1"

    def parse(
        self, data: bytes, *, filename: str, declared_mime: str | None, limits: ParserLimits
    ) -> ParseResult:
        del filename, declared_mime
        blocks: list[tuple[str, dict[str, int], str | None]] = []
        heading: str | None = None
        paragraph_lines: list[str] = []
        paragraph_start = 1

        def flush() -> None:
            nonlocal paragraph_lines
            if paragraph_lines:
                value = normalize_text("\n".join(paragraph_lines))
                if value:
                    MarkdownIt("commonmark").parse(value)
                    blocks.append((value, {"line": paragraph_start}, heading))
                paragraph_lines = []

        for line, line_number in iter_utf8_lines(
            data, max_decoded_characters=limits.max_normalized_characters
        ):
            line = normalize_text(line)
            match = re.match(r"^#{1,6}\s+(.+?)\s*#*$", line)
            if match:
                flush()
                heading = normalize_text(match.group(1))
                blocks.append((heading, {"line": line_number}, heading))
            elif not line.strip():
                flush()
            else:
                if not paragraph_lines:
                    paragraph_start = line_number
                paragraph_lines.append(line)
        flush()
        return _finish_chunks(blocks, data=data, parser_version=self.parser_version, limits=limits)
