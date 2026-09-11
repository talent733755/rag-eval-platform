"""Process-isolated parser runner with an explicit OS sandbox boundary."""

from __future__ import annotations

import base64
import binascii
import dataclasses
import json
import math
import os
import shutil
import signal
import socket
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rag_eval_api.parsers.docx import DocxParser
from rag_eval_api.parsers.errors import (
    MalformedDocumentError,
    ParserError,
    ParserLimitExceeded,
    ParserSandboxUnavailable,
    ParserSecurityError,
    ParserTimeout,
    UnsupportedDocumentError,
)
from rag_eval_api.parsers.models import CanonicalChunk, ParseResult, ParserLimits
from rag_eval_api.parsers.pdf import PdfParser
from rag_eval_api.parsers.protocol import DocumentParser

_ErrorCode = Literal[
    "unsupported_type",
    "parse_failed",
    "parse_timeout",
    "size_exceeded",
    "security_violation",
    "parser_sandbox_unavailable",
]
_ERROR_CODES = frozenset(
    {
        "unsupported_type",
        "parse_failed",
        "parse_timeout",
        "size_exceeded",
        "security_violation",
        "parser_sandbox_unavailable",
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _LimitsEnvelope(_StrictModel):
    max_input_bytes: int
    max_pages: int
    max_paragraphs: int
    max_normalized_characters: int
    max_chunk_characters: int
    max_pdf_wall_clock_seconds: float
    max_pdf_objects: int
    max_pdf_decoded_stream_bytes: int
    max_pdf_recursion_depth: int
    max_pdf_recursion_objects: int
    max_docx_zip_entries: int
    max_docx_uncompressed_bytes: int
    max_docx_compression_ratio: float
    max_docx_xml_depth: int


class _RequestEnvelope(_StrictModel):
    data_b64: str
    suffix: Literal[".pdf", ".docx"]
    filename: str
    declared_mime: str | None
    limits: _LimitsEnvelope
    timeout_seconds: float
    sandbox_enabled: bool


class _ChunkEnvelope(_StrictModel):
    ordinal: int = Field(ge=0)
    content: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    character_count: int = Field(ge=0)
    token_count: int = Field(ge=0)
    source_location: dict[str, int]
    heading: str | None


class _ResultEnvelope(_StrictModel):
    parser_version: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)
    page_count: int = Field(ge=0)
    paragraph_count: int = Field(ge=0)
    chunks: list[_ChunkEnvelope]


class _OkEnvelope(_StrictModel):
    kind: Literal["ok"]
    result: _ResultEnvelope


class _ErrorEnvelope(_StrictModel):
    kind: Literal["error"]
    code: Literal[
        "unsupported_type",
        "parse_failed",
        "parse_timeout",
        "size_exceeded",
        "security_violation",
        "parser_sandbox_unavailable",
    ]
    message: str = Field(max_length=512)


def restricted_sandbox_available() -> bool:
    """Whether this runtime can enforce CPU and address-space limits."""

    try:
        import resource

        return (
            os.name == "posix"
            and os.geteuid() != 0
            and sys.platform.startswith("linux")
            and hasattr(resource, "RLIMIT_CPU")
            and hasattr(resource, "RLIMIT_AS")
        )
    except (ImportError, AttributeError):
        return False


def sandbox_command_available(executable: str | None, args: Sequence[str]) -> bool:
    """Check a supported no-network, parent-death-aware OS sandbox profile."""

    if not executable or not executable.strip():
        return False
    resolved = shutil.which(executable)
    if resolved is None or not os.access(resolved, os.X_OK):
        return False
    command_name = Path(resolved).name
    supplied = set(args)
    required_flags = {
        "bwrap": {"--unshare-net", "--die-with-parent"},
        "unshare": {"--net", "--fork", "--kill-child"},
    }.get(command_name)
    return required_flags is not None and required_flags <= supplied


class ParserRunner:
    """Run hostile PDF/DOCX parsing in a disposable child process.

    Without ``sandbox_executable`` this is a development fallback only. It
    applies process-local limits where possible and monkey-patches Python
    sockets, but that is not OS-level network isolation. Strict deployments
    must provide a supported ``bwrap`` or ``unshare`` profile with required
    flags and resource-limit support.
    """

    def __init__(
        self,
        *,
        default_timeout_seconds: float = 10.0,
        require_resource_limits: bool = False,
        sandbox_executable: str | None = None,
        sandbox_args: Sequence[str] = (),
    ) -> None:
        if default_timeout_seconds <= 0 or not math.isfinite(default_timeout_seconds):
            raise ValueError("default_timeout_seconds must be finite and positive")
        if sandbox_executable is not None and not sandbox_executable.strip():
            raise ValueError("sandbox_executable must not be empty")
        self.default_timeout_seconds = default_timeout_seconds
        self.require_resource_limits = require_resource_limits
        self.sandbox_executable = sandbox_executable
        self.sandbox_args = tuple(sandbox_args)

    @property
    def uses_os_sandbox(self) -> bool:
        """Whether parsing is configured to run under an external command."""

        return self.sandbox_executable is not None

    def parse_bytes(
        self,
        data: bytes,
        *,
        suffix: str,
        filename: str,
        declared_mime: str | None,
        limits: ParserLimits,
        timeout_seconds: float | None = None,
    ) -> ParseResult:
        timeout = self.default_timeout_seconds if timeout_seconds is None else timeout_seconds
        if timeout <= 0 or not math.isfinite(timeout):
            raise ParserTimeout("parser exceeded its hard timeout")
        if self.sandbox_executable is not None and not sandbox_command_available(
            self.sandbox_executable, self.sandbox_args
        ):
            raise ParserSandboxUnavailable("configured parser sandbox profile is unsupported")
        if self.require_resource_limits:
            if not sandbox_command_available(self.sandbox_executable, self.sandbox_args):
                raise ParserSandboxUnavailable(
                    "a supported OS parser sandbox executable is required"
                )
            if not restricted_sandbox_available():
                raise ParserSandboxUnavailable("CPU and memory resource limits are required")

        request = _RequestEnvelope(
            data_b64=base64.b64encode(data).decode("ascii"),
            suffix=cast(Literal[".pdf", ".docx"], suffix),
            filename=filename,
            declared_mime=declared_mime,
            limits=_LimitsEnvelope(**dataclasses.asdict(limits)),
            timeout_seconds=float(timeout),
            sandbox_enabled=self.uses_os_sandbox,
        )
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                self._command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            output, _ = process.communicate(
                _json_bytes(request.model_dump(mode="json")), timeout=timeout
            )
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                self._terminate(process)
            raise ParserTimeout("parser exceeded its hard timeout") from exc
        except (OSError, ValueError) as exc:
            if process is not None:
                self._terminate(process)
            raise ParserSandboxUnavailable("parser sandbox could not be started") from exc
        finally:
            if process is not None and process.poll() is None:
                self._terminate(process)

        if process.returncode != 0:
            self._terminate(process, force_group=True)
            raise ParserSandboxUnavailable("parser sandbox exited unexpectedly")
        try:
            return _parse_result_or_error(output)
        except ParserError:
            self._terminate(process, force_group=True)
            raise

    def _command(self) -> list[str]:
        child = [sys.executable, "-m", "rag_eval_api.parsers.runner", "--child"]
        if self.sandbox_executable is None:
            return child
        return [self.sandbox_executable, *self.sandbox_args, *child]

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes], *, force_group: bool = False) -> None:
        if os.name == "posix":
            if process.poll() is None or force_group:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        elif process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait(timeout=0.5)


def _child_result(request: _RequestEnvelope) -> _OkEnvelope | _ErrorEnvelope:
    try:
        data = base64.b64decode(request.data_b64, validate=True)
        limits = ParserLimits(**request.limits.model_dump())
        _configure_child_sandbox(
            limits, request.timeout_seconds, sandbox_enabled=request.sandbox_enabled
        )
        parser_class = {".pdf": PdfParser, ".docx": DocxParser}[request.suffix]
        parser: DocumentParser = cast(DocumentParser, parser_class())
        result = parser.parse(
            data,
            filename=request.filename,
            declared_mime=request.declared_mime,
            limits=limits,
        )
        return _OkEnvelope(kind="ok", result=_result_envelope(result))
    except ParserError as exc:
        code = "security_violation" if isinstance(exc, ParserSecurityError) else exc.code
        return _error_envelope(code, str(exc))
    except (binascii.Error, ValueError, TypeError):
        return _error_envelope("parser_sandbox_unavailable", "parser request was invalid")
    except BaseException:
        return _error_envelope("parse_failed", "document could not be parsed safely")


def _configure_child_sandbox(
    limits: ParserLimits, timeout_seconds: float, *, sandbox_enabled: bool
) -> None:
    try:
        import resource
    except ImportError:
        if not sandbox_enabled:
            _disable_network_fallback()
            return
        raise ParserSandboxUnavailable("process resource limits are unavailable")

    cpu_seconds = max(1, math.ceil(timeout_seconds) + 1)
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        if restricted_sandbox_available():
            memory_bytes = min(
                max(1024 * 1024 * 1024, limits.max_input_bytes * 8),
                2 * 1024 * 1024 * 1024,
            )
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    except (OSError, ValueError) as exc:
        if sandbox_enabled:
            raise ParserSandboxUnavailable("process resource limits could not be applied") from exc
    if not sandbox_enabled:
        _disable_network_fallback()


def _disable_network_fallback() -> None:
    """Development-only defense; never treated as OS network isolation."""

    class DeniedSocket:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("network access is disabled in parser fallback")

    setattr(socket, "socket", DeniedSocket)
    setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("network access is disabled in parser fallback")
        ),
    )


def _child_main() -> None:
    try:
        request = _RequestEnvelope.model_validate(_strict_json_loads(sys.stdin.buffer.read()))
        envelope = _child_result(request)
    except BaseException:
        envelope = _error_envelope(
            "parser_sandbox_unavailable", "parser sandbox returned an invalid request"
        )
    sys.stdout.buffer.write(_json_bytes(envelope.model_dump(mode="json")))
    sys.stdout.buffer.flush()


def _result_envelope(result: ParseResult) -> _ResultEnvelope:
    return _ResultEnvelope(
        parser_version=result.parser_version,
        content_hash=result.content_hash,
        byte_size=result.byte_size,
        page_count=result.page_count,
        paragraph_count=result.paragraph_count,
        chunks=[
            _ChunkEnvelope(
                ordinal=chunk.ordinal,
                content=chunk.content,
                content_hash=chunk.content_hash,
                character_count=chunk.character_count,
                token_count=chunk.token_count,
                source_location=chunk.source_location,
                heading=chunk.heading,
            )
            for chunk in result.chunks
        ],
    )


def _parse_result_or_error(output: bytes) -> ParseResult:
    try:
        envelope = _strict_json_loads(output)
        if not isinstance(envelope, dict):
            raise ValueError("parser envelope must be an object")
        if envelope.get("kind") == "ok":
            parsed = _OkEnvelope.model_validate(envelope)
            result = parsed.result
            return ParseResult(
                parser_version=result.parser_version,
                content_hash=result.content_hash,
                byte_size=result.byte_size,
                page_count=result.page_count,
                paragraph_count=result.paragraph_count,
                chunks=tuple(
                    CanonicalChunk(
                        ordinal=chunk.ordinal,
                        content=chunk.content,
                        content_hash=chunk.content_hash,
                        character_count=chunk.character_count,
                        token_count=chunk.token_count,
                        source_location=chunk.source_location,
                        heading=chunk.heading,
                    )
                    for chunk in result.chunks
                ),
            )
        if envelope.get("kind") == "error":
            parsed_error = _ErrorEnvelope.model_validate(envelope)
            raise _error_from_child(parsed_error.code, parsed_error.message)
        raise ValueError("unknown parser envelope kind")
    except ParserError:
        raise
    except (
        UnicodeDecodeError,
        ValueError,
        TypeError,
        ValidationError,
        json.JSONDecodeError,
    ) as exc:
        raise ParserSandboxUnavailable("parser sandbox returned an invalid JSON envelope") from exc


def _strict_json_loads(payload: bytes) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"invalid JSON constant: {value}")

    return json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_constant,
    )


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _error_envelope(code: str, message: str) -> _ErrorEnvelope:
    safe_code = code if code in _ERROR_CODES else "parser_sandbox_unavailable"
    return _ErrorEnvelope(
        kind="error",
        code=cast(_ErrorCode, safe_code),
        message=message[:512],
    )


def _error_from_child(code: str, message: str) -> ParserError:
    error_types: Mapping[str, type[ParserError]] = {
        "unsupported_type": UnsupportedDocumentError,
        "parse_failed": MalformedDocumentError,
        "parse_timeout": ParserTimeout,
        "size_exceeded": ParserLimitExceeded,
        "security_violation": ParserSecurityError,
        "parser_sandbox_unavailable": ParserSandboxUnavailable,
    }
    error_type = error_types.get(code, ParserSandboxUnavailable)
    return error_type(message)


if __name__ == "__main__" and sys.argv[1:] == ["--child"]:
    _child_main()
