"""Process-isolated parser runner with hard timeout and resource bounds."""

from __future__ import annotations

import math
import multiprocessing
import os
import socket
import sys
from collections.abc import Mapping
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import cast

from rag_eval_api.parsers.docx import DocxParser
from rag_eval_api.parsers.errors import (
    MalformedDocumentError,
    ParserError,
    ParserLimitExceeded,
    ParserSecurityError,
    UnsupportedDocumentError,
)
from rag_eval_api.parsers.models import ParseResult, ParserLimits
from rag_eval_api.parsers.pdf import PdfParser
from rag_eval_api.parsers.protocol import DocumentParser


class ParserTimeout(ParserError):
    code = "parse_timeout"
    retryable = True


class ParserSandboxUnavailable(ParserError):
    code = "parser_sandbox_unavailable"


def restricted_sandbox_available() -> bool:
    """Whether this runtime can enforce process resource limits safely."""

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


class ParserRunner:
    """Run hostile PDF/DOCX parsing in a disposable, network-disabled child."""

    def __init__(
        self,
        *,
        default_timeout_seconds: float = 10.0,
        require_resource_limits: bool = False,
    ) -> None:
        if default_timeout_seconds <= 0 or not math.isfinite(default_timeout_seconds):
            raise ValueError("default_timeout_seconds must be finite and positive")
        self.default_timeout_seconds = default_timeout_seconds
        self.require_resource_limits = require_resource_limits

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
        if os.name != "posix" or os.geteuid() == 0:
            raise ParserSandboxUnavailable(
                "a non-root POSIX process sandbox is required"
            )
        if self.require_resource_limits and not restricted_sandbox_available():
            raise ParserSandboxUnavailable("CPU and memory resource limits are required")
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        process = context.Process(
            target=_parse_in_child,
            args=(
                send,
                data,
                suffix,
                filename,
                declared_mime,
                limits,
                timeout,
                self.require_resource_limits,
            ),
            daemon=True,
        )
        process.start()
        send.close()
        try:
            if not receive.poll(timeout):
                self._terminate(process)
                raise ParserTimeout("parser exceeded its hard timeout")
            message = receive.recv()
        finally:
            receive.close()
            if process.is_alive():
                self._terminate(process)
            else:
                process.join(timeout=0.2)
        if message[0] == "ok":
            return cast(ParseResult, message[1])
        raise _error_from_child(message[1], message[2])

    @staticmethod
    def _terminate(process: BaseProcess) -> None:
        process.terminate()
        process.join(timeout=0.5)
        if process.is_alive():
            process.kill()
            process.join(timeout=0.5)


def _parse_in_child(
    send: Connection,
    data: bytes,
    suffix: str,
    filename: str,
    declared_mime: str | None,
    limits: ParserLimits,
    timeout_seconds: float,
    require_resource_limits: bool,
) -> None:
    connection = send
    try:
        _configure_child_sandbox(limits, timeout_seconds, require_resource_limits)
        parser_class = {".pdf": PdfParser, ".docx": DocxParser}[suffix]
        parser: DocumentParser = cast(DocumentParser, parser_class())
        result = parser.parse(
            data,
            filename=filename,
            declared_mime=declared_mime,
            limits=limits,
        )
        connection.send(("ok", result))
    except ParserError as exc:
        code = "security_violation" if isinstance(exc, ParserSecurityError) else exc.code
        connection.send(("error", code, str(exc)))
    except Exception:
        connection.send(("error", "parse_failed", "document could not be parsed safely"))
    finally:
        connection.close()


def _configure_child_sandbox(
    limits: ParserLimits, timeout_seconds: float, require_resource_limits: bool
) -> None:
    import resource

    if os.name != "posix" or os.geteuid() == 0:
        raise ParserSandboxUnavailable("restricted parser sandbox is unavailable")
    cpu_seconds = max(1, math.ceil(timeout_seconds) + 1)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    if restricted_sandbox_available():
        memory_bytes = min(
            max(1024 * 1024 * 1024, limits.max_input_bytes * 8),
            2 * 1024 * 1024 * 1024,
        )
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    elif require_resource_limits:
        raise ParserSandboxUnavailable("memory resource limits are unavailable")
    _disable_network()


def _disable_network() -> None:
    class DeniedSocket:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("network access is disabled in parser sandbox")

    setattr(socket, "socket", DeniedSocket)
    setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("network access is disabled in parser sandbox")
        ),
    )


def _error_from_child(code: str, message: str) -> ParserError:
    error_types: Mapping[str, type[ParserError]] = {
        "unsupported_type": UnsupportedDocumentError,
        "parse_failed": MalformedDocumentError,
        "size_exceeded": ParserLimitExceeded,
        "security_violation": ParserSecurityError,
        "parser_sandbox_unavailable": ParserSandboxUnavailable,
    }
    error_type = error_types.get(code, MalformedDocumentError)
    return error_type(message)
