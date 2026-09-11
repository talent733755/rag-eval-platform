from __future__ import annotations

import base64
import io
import os
import pickle
import sys
import time
import zipfile
from pathlib import Path

import pytest
from docx import Document as DocxDocument

from rag_eval_api.parsers.docx import DocxParser
from rag_eval_api.parsers.errors import (
    MalformedDocumentError,
    ParserLimitExceeded,
    ParserSecurityError,
    UnsupportedDocumentError,
)
from rag_eval_api.parsers.models import ParserLimits
from rag_eval_api.parsers.pdf import PdfParser
from rag_eval_api.parsers.registry import ParserRegistry
from rag_eval_api.parsers.runner import (
    ParserRunner,
    ParserSandboxUnavailable,
    ParserTimeout,
    sandbox_command_available,
)


def _docx_bytes() -> bytes:
    document = DocxDocument()
    document.add_heading("Safety", level=1)
    document.add_paragraph("Keep the source location stable.")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _pdf_bytes() -> bytes:
    stream = b"BT /F1 12 Tf (Hello PDF) Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(output)


def test_registry_parses_txt_markdown_and_docx_with_deterministic_locations() -> None:
    registry = ParserRegistry()

    text = registry.parse(
        io.BytesIO(b"Heading\n\nFirst paragraph.\n\nSecond paragraph."),
        filename="guide.txt",
        declared_mime="text/plain",
    )
    markdown = registry.parse(
        io.BytesIO(b"# Heading\n\nFirst paragraph."),
        filename="guide.md",
        declared_mime="text/markdown",
    )
    docx = registry.parse(
        io.BytesIO(_docx_bytes()),
        filename="guide.docx",
        declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert [chunk.content for chunk in text.chunks] == [
        "Heading",
        "First paragraph.",
        "Second paragraph.",
    ]
    assert text.chunks[0].source_location == {"paragraph": 0}
    assert markdown.chunks[0].heading == "Heading"
    assert markdown.chunks[0].source_location["line"] == 1
    assert docx.chunks[0].heading == "Safety"
    assert docx.chunks[1].source_location == {"paragraph": 1}
    assert (
        text.content_hash
        == registry.parse(
            io.BytesIO(b"Heading\n\nFirst paragraph.\n\nSecond paragraph."),
            filename="guide.txt",
            declared_mime="text/plain",
        ).content_hash
    )


def test_registry_parses_pdf_and_reports_page_locations() -> None:
    pdf = _pdf_bytes()
    result = ParserRegistry().parse(
        io.BytesIO(pdf), filename="guide.pdf", declared_mime="application/pdf"
    )

    assert result.page_count == 1
    assert result.chunks[0].source_location == {"page": 1}
    assert "Hello PDF" in result.chunks[0].content


@pytest.mark.parametrize(
    ("filename", "mime", "payload"),
    [
        ("guide.pdf", "text/plain", b"%PDF-1.4"),
        ("guide.exe", "application/octet-stream", b"MZ not supported"),
        ("guide.docx", "application/zip", b"not a zip"),
    ],
)
def test_registry_classifies_unsupported_and_malformed_inputs(
    filename: str, mime: str, payload: bytes
) -> None:
    with pytest.raises((UnsupportedDocumentError, MalformedDocumentError)):
        ParserRegistry().parse(io.BytesIO(payload), filename=filename, declared_mime=mime)


def test_registry_rejects_limits_and_zip_traversal(tmp_path: Path) -> None:
    with pytest.raises(ParserLimitExceeded, match="characters"):
        ParserRegistry().parse(
            io.BytesIO(b"one\n\ntwo"),
            filename="guide.txt",
            declared_mime="text/plain",
            limits=ParserLimits(max_normalized_characters=5),
        )

    malicious = io.BytesIO()
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("../evil.txt", "bad")
    with pytest.raises(MalformedDocumentError, match="ZIP"):
        ParserRegistry().parse(
            io.BytesIO(malicious.getvalue()),
            filename="guide.docx",
            declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    symlinked = io.BytesIO()
    info = zipfile.ZipInfo("word/link.xml")
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    with zipfile.ZipFile(symlinked, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(info, "../secret")
    with pytest.raises(ParserSecurityError, match="symlink"):
        ParserRegistry().parse(
            io.BytesIO(symlinked.getvalue()),
            filename="guide.docx",
            declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


def test_registry_treats_filename_as_metadata_only() -> None:
    result = ParserRegistry().parse(
        io.BytesIO(b"safe content"),
        filename="../../private/secrets.txt",
        declared_mime="text/plain",
    )

    assert result.chunks[0].content == "safe content"


def test_registry_accepts_empty_text_but_rejects_empty_or_truncated_pdf() -> None:
    empty = ParserRegistry().parse(
        io.BytesIO(b""), filename="empty.txt", declared_mime="text/plain"
    )
    assert empty.chunks == ()

    with pytest.raises(UnsupportedDocumentError):
        ParserRegistry().parse(
            io.BytesIO(b""), filename="empty.pdf", declared_mime="application/pdf"
        )


@pytest.mark.parametrize("length", [150_000, 200_000])
def test_text_parser_accepts_long_single_lines_up_to_character_limit(length: int) -> None:
    result = ParserRegistry(isolated=False).parse(
        io.BytesIO(b"x" * length),
        filename="long.txt",
        declared_mime="text/plain",
        limits=ParserLimits(max_normalized_characters=200_000),
    )

    assert sum(chunk.character_count for chunk in result.chunks) == length


def test_text_parser_rejects_single_line_over_character_limit() -> None:
    with pytest.raises(ParserLimitExceeded, match="characters"):
        ParserRegistry(isolated=False).parse(
            io.BytesIO(b"x" * 200_001),
            filename="long.txt",
            declared_mime="text/plain",
            limits=ParserLimits(max_normalized_characters=200_000),
        )


def test_text_parser_handles_multibyte_utf8_split_at_decode_chunk_boundary() -> None:
    content = ("界" * 65_535) + "🙂" + ("界" * 10)
    result = ParserRegistry(isolated=False).parse(
        io.BytesIO(content.encode("utf-8")),
        filename="multibyte.txt",
        declared_mime="text/plain",
        limits=ParserLimits(max_normalized_characters=65_546),
    )

    assert "🙂" in "".join(chunk.content for chunk in result.chunks)
    assert sum(chunk.character_count for chunk in result.chunks) == len(content)
    with pytest.raises(MalformedDocumentError):
        ParserRegistry().parse(
            io.BytesIO(b"%PDF-1.7"), filename="truncated.pdf", declared_mime="application/pdf"
        )


def test_docx_compression_ratio_is_bounded_before_document_parsing() -> None:
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types />", compress_type=zipfile.ZIP_STORED)
        archive.writestr("word/document.xml", b"A" * 50_000)

    with pytest.raises(ParserLimitExceeded, match="compression ratio"):
        ParserRegistry().parse(
            io.BytesIO(bomb.getvalue()),
            filename="bomb.docx",
            declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            limits=ParserLimits(max_docx_compression_ratio=2),
        )


def test_docx_xml_depth_is_bounded_before_document_parsing() -> None:
    deep_xml = ("<a>" * 5) + ("</a>" * 5)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", deep_xml)

    with pytest.raises(ParserLimitExceeded, match="XML depth"):
        ParserRegistry().parse(
            io.BytesIO(payload.getvalue()),
            filename="deep.docx",
            declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            limits=ParserLimits(max_docx_xml_depth=3),
        )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("max_pdf_objects", "object"),
        ("max_pdf_decoded_stream_bytes", "decoded"),
        ("max_pdf_recursion_depth", "recursion"),
    ],
)
def test_pdf_resource_limits_are_enforced_in_isolated_runner(field: str, message: str) -> None:
    with pytest.raises(ParserLimitExceeded, match=message):
        ParserRegistry().parse(
            io.BytesIO(_pdf_bytes()),
            filename="bounded.pdf",
            declared_mime="application/pdf",
            limits=ParserLimits(**{field: 1}),
        )


@pytest.mark.parametrize(
    "field",
    [
        "max_input_bytes",
        "max_pages",
        "max_paragraphs",
        "max_normalized_characters",
        "max_chunk_characters",
        "max_pdf_objects",
        "max_pdf_decoded_stream_bytes",
        "max_pdf_recursion_depth",
        "max_docx_zip_entries",
        "max_docx_uncompressed_bytes",
        "max_docx_compression_ratio",
        "max_docx_xml_depth",
    ],
)
def test_parser_limits_reject_values_above_safe_upper_bounds(field: str) -> None:
    upper_bound = ParserLimits.safe_upper_bounds()[field]
    with pytest.raises(ValueError, match="safe upper bound"):
        ParserLimits(**{field: upper_bound + 1})


def test_parser_runner_enforces_hard_timeout_before_starting_work() -> None:
    with pytest.raises(ParserTimeout):
        ParserRegistry().parse(
            io.BytesIO(_pdf_bytes()),
            filename="guide.pdf",
            declared_mime="application/pdf",
            timeout_seconds=0,
        )


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o700)


def test_parser_runner_terminates_sleeping_sandbox_process_without_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "rag_eval_api.parsers.runner.sandbox_command_available",
        lambda _executable, _args: True,
    )
    pid_file = tmp_path / "sleep.pid"
    wrapper = tmp_path / "bwrap"
    wrapper.write_text(
        "#!" + sys.executable + "\n"
        "import pathlib, subprocess\n"
        f"pid_file = pathlib.Path({str(pid_file)!r})\n"
        "child = subprocess.Popen(['sleep', '30'])\n"
        "pid_file.write_text(str(child.pid))\n"
        "child.wait()\n"
    )
    wrapper.chmod(0o700)
    runner = ParserRunner(
        sandbox_executable=str(wrapper),
        sandbox_args=("--die-with-parent", "--unshare-net"),
    )

    with pytest.raises(ParserTimeout):
        runner.parse_bytes(
            _pdf_bytes(),
            suffix=".pdf",
            filename="timeout.pdf",
            declared_mime="application/pdf",
            limits=ParserLimits(),
            timeout_seconds=2.0,
        )

    deadline = time.monotonic() + 2
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pid_file.exists()
    child_pid = int(pid_file.read_text())
    for _ in range(40):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("timed-out parser descendant was left running")


@pytest.mark.parametrize("exit_code", [0, 17])
def test_parser_runner_maps_eof_or_crashed_child_to_sandbox_error(
    tmp_path: Path, exit_code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "rag_eval_api.parsers.runner.sandbox_command_available",
        lambda _executable, _args: True,
    )
    wrapper = tmp_path / "bwrap"
    _write_executable(wrapper, f"#!/bin/sh\nexit {exit_code}\n")

    with pytest.raises(ParserSandboxUnavailable):
        ParserRunner(
            sandbox_executable=str(wrapper),
            sandbox_args=("--die-with-parent", "--unshare-net"),
        ).parse_bytes(
            _pdf_bytes(),
            suffix=".pdf",
            filename="crashed.pdf",
            declared_mime="application/pdf",
            limits=ParserLimits(),
        )


def test_parser_runner_requires_os_sandbox_for_strict_mode() -> None:
    with pytest.raises(ParserSandboxUnavailable):
        ParserRunner(require_resource_limits=True).parse_bytes(
            _pdf_bytes(),
            suffix=".pdf",
            filename="strict.pdf",
            declared_mime="application/pdf",
            limits=ParserLimits(),
        )


def test_parser_runner_rejects_pickle_payload_without_executing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "rag_eval_api.parsers.runner.sandbox_command_available",
        lambda _executable, _args: True,
    )
    marker = tmp_path / "executed"

    class MaliciousPayload:
        def __reduce__(self) -> tuple[object, tuple[str]]:
            return (os.system, (f"touch {marker}",))

    encoded = base64.b64encode(pickle.dumps(MaliciousPayload())).decode("ascii")
    wrapper = tmp_path / "bwrap"
    wrapper.write_text(
        "#!" + sys.executable + "\n"
        "import base64, sys\n"
        f"sys.stdout.buffer.write(base64.b64decode({encoded!r}))\n"
    )
    wrapper.chmod(0o700)

    with pytest.raises(ParserSandboxUnavailable):
        ParserRunner(
            sandbox_executable=str(wrapper),
            sandbox_args=("--die-with-parent", "--unshare-net"),
        ).parse_bytes(
            _pdf_bytes(),
            suffix=".pdf",
            filename="malicious.pdf",
            declared_mime="application/pdf",
            limits=ParserLimits(),
        )
    assert not marker.exists()


def test_parser_runner_rejects_sandbox_commands_without_required_flags(tmp_path: Path) -> None:
    bwrap = tmp_path / "bwrap"
    bwrap.write_text("#!/bin/sh\nexit 0\n")
    bwrap.chmod(0o700)
    assert not sandbox_command_available(str(bwrap), ("--die-with-parent",))
    assert not sandbox_command_available(str(bwrap), ("--die-with-parent", "--unshare-net"))
    env = tmp_path / "env"
    env.write_text("#!/bin/sh\nexit 0\n")
    env.chmod(0o700)
    assert not sandbox_command_available(str(env), ("--unshare-net", "--die-with-parent"))


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_parser_runner_caps_child_output_and_kills_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stream: str
) -> None:
    monkeypatch.setattr(
        "rag_eval_api.parsers.runner.sandbox_command_available",
        lambda _executable, _args: True,
    )
    wrapper = tmp_path / "bwrap"
    wrapper.write_text(
        "#!" + sys.executable + "\n"
        "import sys\n"
        f"sys.{stream}.write('x' * (2 * 1024 * 1024))\n"
        f"sys.{stream}.flush()\n"
    )
    wrapper.chmod(0o700)

    with pytest.raises(ParserSandboxUnavailable, match="output"):
        ParserRunner(
            sandbox_executable=str(wrapper),
            sandbox_args=("--die-with-parent", "--unshare-net"),
        ).parse_bytes(
            _pdf_bytes(),
            suffix=".pdf",
            filename="output-limit.pdf",
            declared_mime="application/pdf",
            limits=ParserLimits(),
        )


def test_pdf_and_docx_parser_timeout_is_not_downgraded_to_parse_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_clock = iter((0.0, 2.0))
    monkeypatch.setattr("rag_eval_api.parsers.pdf.time.monotonic", lambda: next(pdf_clock))
    with pytest.raises(ParserTimeout) as pdf_error:
        PdfParser().parse(
            _pdf_bytes(),
            filename="timeout.pdf",
            declared_mime="application/pdf",
            limits=ParserLimits(max_pdf_wall_clock_seconds=1),
        )
    assert pdf_error.value.code == "parse_timeout"

    docx_clock = iter((0.0, 2.0))
    monkeypatch.setattr("rag_eval_api.parsers.docx.time.monotonic", lambda: next(docx_clock))
    with pytest.raises(ParserTimeout) as docx_error:
        DocxParser().parse(
            _docx_bytes(),
            filename="timeout.docx",
            declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            limits=ParserLimits(max_pdf_wall_clock_seconds=1),
        )
    assert docx_error.value.code == "parse_timeout"
