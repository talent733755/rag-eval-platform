"""Process-isolated parser runner with an explicit OS sandbox boundary."""

from __future__ import annotations

import base64
import binascii
import dataclasses
import json
import math
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import BinaryIO, Literal, cast

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
_MIN_CHILD_OUTPUT_BYTES = 1 * 1024 * 1024
_OUTPUT_ENVELOPE_BYTES = 64 * 1024
_SANDBOX_PATHS: Mapping[str, frozenset[str]] = {
    "bwrap": frozenset({"/usr/bin/bwrap", "/usr/local/bin/bwrap"}),
    "unshare": frozenset({"/usr/bin/unshare", "/bin/unshare", "/usr/local/bin/unshare"}),
}
_SANDBOX_TEMPLATES: Mapping[str, tuple[str, ...]] = {
    "bwrap": ("--unshare-net", "--die-with-parent", "--new-session"),
    "unshare": (
        "--user",
        "--map-root-user",
        "--mount",
        "--uts",
        "--ipc",
        "--net",
        "--pid",
        "--fork",
        "--kill-child",
    ),
}


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

    return _resource_limits_supported() and os.geteuid() != 0


def _resource_limits_supported() -> bool:
    try:
        import resource

        return (
            os.name == "posix"
            and sys.platform.startswith("linux")
            and hasattr(resource, "RLIMIT_CPU")
            and hasattr(resource, "RLIMIT_AS")
        )
    except (ImportError, AttributeError):
        return False


def sandbox_command_available(executable: str | None, args: Sequence[str]) -> bool:
    """Check a supported no-network, parent-death-aware OS sandbox profile."""

    if not executable or not executable.strip() or not os.path.isabs(executable):
        return False
    absolute = os.path.abspath(executable)
    resolved = os.path.realpath(absolute)
    command_name = Path(resolved).name
    if absolute != resolved or resolved not in _SANDBOX_PATHS.get(command_name, frozenset()):
        return False
    try:
        stat_result = os.stat(resolved, follow_symlinks=False)
    except OSError:
        return False
    if (
        not os.path.isfile(resolved)
        or stat_result.st_uid != 0
        or stat_result.st_mode & 0o022
        or not os.access(resolved, os.X_OK)
    ):
        return False
    if tuple(args) != _SANDBOX_TEMPLATES.get(command_name, ()):
        return False
    return _probe_sandbox_template(resolved, args)


def _probe_sandbox_template(executable: str, args: Sequence[str]) -> bool:
    """Execute the exact profile against a harmless command before accepting it."""

    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            [executable, *args, "--", "/bin/true"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        process.wait(timeout=2.0)
        return process.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        if process is not None and process.poll() is None:
            _kill_process_group(process)


def _child_output_limit(limits: ParserLimits) -> int:
    return max(
        _MIN_CHILD_OUTPUT_BYTES,
        limits.max_normalized_characters * 4 + _OUTPUT_ENVELOPE_BYTES,
    )


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass


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
        if len(data) > limits.max_input_bytes:
            raise ParserLimitExceeded("input bytes exceed the configured limit")
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
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            output, _ = self._communicate_bounded(
                process,
                _json_bytes(request.model_dump(mode="json")),
                timeout,
                _child_output_limit(limits),
            )
        except ParserTimeout:
            if process is not None:
                self._terminate(process, force_group=True)
            raise
        except ParserSandboxUnavailable:
            if process is not None:
                self._terminate(process, force_group=True)
            raise
        except (OSError, ValueError) as exc:
            if process is not None:
                self._terminate(process, force_group=True)
            raise ParserSandboxUnavailable("parser sandbox could not be started") from exc
        finally:
            if process is not None and process.poll() is None:
                self._terminate(process, force_group=True)

        if process.returncode != 0:
            self._terminate(process, force_group=True)
            raise ParserSandboxUnavailable("parser sandbox exited unexpectedly")
        try:
            return _parse_result_or_error(output)
        except ParserError:
            self._terminate(process, force_group=True)
            raise

    def _communicate_bounded(
        self,
        process: subprocess.Popen[bytes],
        request: bytes,
        timeout: float,
        output_limit: int,
    ) -> tuple[bytes, bytes]:
        """Exchange one bounded request without unbounded pipe buffering."""

        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        output_limit_hit = threading.Event()

        def drain(stream: BinaryIO | None, buffer: bytearray, limit: int) -> None:
            if stream is None:
                return
            try:
                while True:
                    chunk = stream.read(64 * 1024)
                    if not chunk:
                        return
                    if len(buffer) + len(chunk) > limit:
                        output_limit_hit.set()
                        return
                    buffer.extend(chunk)
            except (OSError, ValueError):
                return

        def write_request(stream: BinaryIO | None) -> None:
            if stream is None:
                return
            try:
                stream.write(request)
                stream.close()
            except (BrokenPipeError, OSError, ValueError):
                return

        stdout_thread = threading.Thread(
            target=drain,
            args=(process.stdout, stdout_buffer, output_limit),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=drain,
            args=(process.stderr, stderr_buffer, output_limit),
            daemon=True,
        )
        input_thread = threading.Thread(target=write_request, args=(process.stdin,), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        input_thread.start()
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None or stdout_thread.is_alive() or stderr_thread.is_alive():
                if output_limit_hit.is_set():
                    raise ParserSandboxUnavailable("parser sandbox output exceeded the limit")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ParserTimeout("parser exceeded its hard timeout")
                time.sleep(min(0.01, remaining))
            process.wait(timeout=0.5)
            if output_limit_hit.is_set():
                raise ParserSandboxUnavailable("parser sandbox output exceeded the limit")
            return bytes(stdout_buffer), bytes(stderr_buffer)
        finally:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
            stdout_thread.join(timeout=0.5)
            stderr_thread.join(timeout=0.5)
            input_thread.join(timeout=0.5)

    def _command(self) -> list[str]:
        child = [sys.executable, "-m", "rag_eval_api.parsers.runner", "--child"]
        if self.sandbox_executable is None:
            return child
        return [self.sandbox_executable, *self.sandbox_args, "--", *child]

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
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                _kill_process_group(process)


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
    except MemoryError:
        return _error_envelope(
            "parser_sandbox_unavailable", "parser process exceeded its memory limit"
        )
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

    if sandbox_enabled and not _resource_limits_supported():
        raise ParserSandboxUnavailable("process resource limits are unavailable")
    cpu_seconds = max(1, math.ceil(timeout_seconds) + 1)
    try:
        if hasattr(resource, "RLIMIT_CPU"):
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        if hasattr(resource, "RLIMIT_AS") and _resource_limits_supported():
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
