"""Process-isolated parser runner with an explicit OS sandbox boundary."""

from __future__ import annotations

import math
import os
import pickle
import shutil
import signal
import socket
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Any, cast

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
from rag_eval_api.parsers.models import ParseResult, ParserLimits
from rag_eval_api.parsers.pdf import PdfParser
from rag_eval_api.parsers.protocol import DocumentParser


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


def sandbox_executable_available(executable: str | None) -> bool:
    """Check whether an explicitly configured sandbox command is executable."""

    if not executable or not executable.strip():
        return False
    resolved = shutil.which(executable)
    return resolved is not None and os.access(resolved, os.X_OK)


class ParserRunner:
    """Run hostile PDF/DOCX parsing in a disposable child process.

    Without ``sandbox_executable`` this is a development fallback only. It
    applies process-local limits where possible and monkey-patches Python
    sockets, but that is not OS-level network isolation. Strict deployments
    must provide an external command such as a configured ``unshare`` or
    ``bwrap`` profile and resource-limit support.
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
        if self.require_resource_limits:
            if not sandbox_executable_available(self.sandbox_executable):
                raise ParserSandboxUnavailable(
                    "an explicit OS parser sandbox executable is required"
                )
            if not restricted_sandbox_available():
                raise ParserSandboxUnavailable("CPU and memory resource limits are required")

        payload = (data, suffix, filename, declared_mime, limits, timeout, self.uses_os_sandbox)
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                self._command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=os.name == "posix",
            )
            output, _ = process.communicate(pickle.dumps(payload), timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                self._terminate(process)
            raise ParserTimeout("parser exceeded its hard timeout") from exc
        except (OSError, ValueError, pickle.PickleError) as exc:
            if process is not None:
                self._terminate(process)
            raise ParserSandboxUnavailable("parser sandbox could not be started") from exc
        finally:
            if process is not None and process.poll() is None:
                self._terminate(process)

        if process.returncode != 0:
            raise ParserSandboxUnavailable("parser sandbox exited unexpectedly")
        try:
            message = pickle.loads(output)
        except (EOFError, pickle.PickleError, TypeError, ValueError) as exc:
            raise ParserSandboxUnavailable("parser sandbox returned no valid result") from exc
        if not isinstance(message, tuple) or not message:
            raise ParserSandboxUnavailable("parser sandbox returned no valid result")
        if message[0] == "ok" and len(message) == 2:
            return cast(ParseResult, message[1])
        if message[0] == "error" and len(message) == 3:
            raise _error_from_child(message[1], message[2])
        raise ParserSandboxUnavailable("parser sandbox returned an invalid result")

    def _command(self) -> list[str]:
        child = [sys.executable, "-m", "rag_eval_api.parsers.runner", "--child"]
        if self.sandbox_executable is None:
            return child
        return [self.sandbox_executable, *self.sandbox_args, *child]

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
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


def _child_result(
    payload: tuple[bytes, str, str, str | None, ParserLimits, float, bool],
) -> tuple[Any, ...]:
    data, suffix, filename, declared_mime, limits, timeout_seconds, sandbox_enabled = payload
    try:
        _configure_child_sandbox(
            limits, timeout_seconds, sandbox_enabled=sandbox_enabled
        )
        parser_class = {".pdf": PdfParser, ".docx": DocxParser}[suffix]
        parser: DocumentParser = cast(DocumentParser, parser_class())
        result = parser.parse(
            data,
            filename=filename,
            declared_mime=declared_mime,
            limits=limits,
        )
        return ("ok", result)
    except ParserError as exc:
        code = "security_violation" if isinstance(exc, ParserSecurityError) else exc.code
        return ("error", code, str(exc))
    except BaseException:
        return ("error", "parse_failed", "document could not be parsed safely")


def _configure_child_sandbox(
    limits: ParserLimits, timeout_seconds: float, *, sandbox_enabled: bool
) -> None:
    try:
        import resource
    except ImportError as exc:
        raise ParserSandboxUnavailable("process resource limits are unavailable") from exc

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
        payload = pickle.load(sys.stdin.buffer)
        result = _child_result(payload)
        pickle.dump(result, sys.stdout.buffer)
        sys.stdout.buffer.flush()
    except BaseException:
        # An EOF or crash is deliberately observed by the parent as a sandbox
        # failure; do not write a traceback or an unbounded exception message.
        return


def _error_from_child(code: str, message: str) -> ParserError:
    error_types: Mapping[str, type[ParserError]] = {
        "unsupported_type": UnsupportedDocumentError,
        "parse_failed": MalformedDocumentError,
        "parse_timeout": ParserTimeout,
        "size_exceeded": ParserLimitExceeded,
        "security_violation": ParserSecurityError,
        "parser_sandbox_unavailable": ParserSandboxUnavailable,
    }
    error_type = error_types.get(code, MalformedDocumentError)
    return error_type(message)


if __name__ == "__main__" and sys.argv[1:] == ["--child"]:
    _child_main()
