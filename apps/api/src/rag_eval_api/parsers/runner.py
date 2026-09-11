"""Process-isolated parser runner with an explicit OS sandbox boundary."""

from __future__ import annotations

import base64
import binascii
import dataclasses
import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
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
from rag_eval_api.parsers.runner_limits import MAX_MAX_PARSER_INPUT_BYTES

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
DEFAULT_MAX_PARSER_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_MAX_PARSER_OUTPUT_BYTES = 256 * 1024 * 1024
_REQUEST_METADATA_BYTES = 64 * 1024
_MAX_ENCODED_INPUT_BYTES = ((MAX_MAX_PARSER_INPUT_BYTES + 2) // 3) * 4
_MAX_CHILD_REQUEST_BYTES = _MAX_ENCODED_INPUT_BYTES + _REQUEST_METADATA_BYTES
_MAX_CHILD_STDERR_BYTES = 64 * 1024
_STARTUP_CPU_SECONDS = 302
_STARTUP_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
_SAFE_CHILD_PATH = "/usr/local/bin:/usr/bin:/bin"
_PYTHON_LIBRARY_NAME = f"python{sys.version_info.major}.{sys.version_info.minor}"
_SANDBOX_PATHS: Mapping[str, frozenset[str]] = {
    "bwrap": frozenset({"/usr/bin/bwrap", "/usr/local/bin/bwrap"}),
    # ``unshare`` cannot provide the required filesystem allowlist here, so it
    # is intentionally not an accepted parser boundary.
}
_SANDBOX_TEMPLATES: Mapping[str, tuple[str, ...]] = {
    "bwrap": (
        "--unshare-user",
        "--uid",
        "65534",
        "--gid",
        "65534",
        "--unshare-net",
        "--unshare-pid",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--tmpfs",
        "/",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/bin",
        "/bin",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind",
        "/lib64",
        "/lib64",
        "--ro-bind",
        "/etc",
        "/etc",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--chdir",
        "/tmp",
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
    data_b64: str = Field(max_length=_MAX_ENCODED_INPUT_BYTES)
    suffix: Literal[".pdf", ".docx"]
    filename: str = Field(max_length=1024)
    declared_mime: str | None = Field(default=None, max_length=255)
    limits: _LimitsEnvelope
    timeout_seconds: float
    sandbox_enabled: bool
    max_output_bytes: int = Field(
        default=DEFAULT_MAX_PARSER_OUTPUT_BYTES,
        ge=_MIN_CHILD_OUTPUT_BYTES,
        le=MAX_MAX_PARSER_OUTPUT_BYTES,
    )


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
    """Whether this runtime exposes the resource controls used by the child."""

    return _resource_limits_supported()


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
    """Check a supported, filesystem-isolated bwrap profile by executing it."""

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
    """Exercise the exact profile's filesystem, identity, network and limit boundary."""

    process: subprocess.Popen[bytes] | None = None
    probe_code = (
        "import os, pypdf, resource, socket\n"
        "import rag_eval_api.parsers.runner\n"
        "if os.geteuid() != 65534 or os.getuid() != 65534: raise SystemExit(11)\n"
        "resource.setrlimit(resource.RLIMIT_CPU, (1, 1))\n"
        "resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))\n"
        "if resource.getrlimit(resource.RLIMIT_CPU)[0] != 1: raise SystemExit(12)\n"
        "if resource.getrlimit(resource.RLIMIT_AS)[0] != 256 * 1024 * 1024: raise SystemExit(13)\n"
        "interfaces = {name for _, name in socket.if_nameindex()}\n"
        "if interfaces - {'lo'}: raise SystemExit(14)\n"
        "if os.path.exists(%r): raise SystemExit(15)\n"
        "with open('/tmp/parser-probe-write', 'w', encoding='ascii') as handle: handle.write('ok')\n"
        "status = open('/proc/self/status', encoding='ascii').read()\n"
        "if next((line for line in status.splitlines() if line.startswith('CapEff:')), '') not in {'CapEff:\\t0000000000000000', 'CapEff:        0000000000000000'}: raise SystemExit(16)\n"
    )
    try:
        with tempfile.TemporaryDirectory(prefix="rag-eval-parser-probe-") as probe_directory:
            sentinel_path = Path(probe_directory) / "host-sentinel"
            sentinel_path.write_text("must remain outside sandbox", encoding="ascii")
            sentinel = str(sentinel_path)
            command = [
                executable,
                *args,
                *_sandbox_runtime_bind_args(),
                "--",
                sys.executable,
                "-c",
                probe_code % sentinel,
            ]
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                cwd="/",
                env=_child_environment("/tmp"),
            )
            process.wait(timeout=2.0)
            return process.returncode == 0 and not sentinel_path.exists()
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        if process is not None and process.poll() is None:
            _kill_process_group(process)


def _child_output_limit(max_output_bytes: int) -> int:
    """Return the explicit serialized child-output budget.

    The budget is configured independently from normalized text limits because
    JSON metadata and many small chunks can be substantially larger than the
    normalized character count. It is still bounded to prevent a configuration
    mistake from becoming an unbounded pipe buffer.
    """

    if not isinstance(max_output_bytes, int) or isinstance(max_output_bytes, bool):
        raise ValueError("max_output_bytes must be an integer")
    if not _MIN_CHILD_OUTPUT_BYTES <= max_output_bytes <= MAX_MAX_PARSER_OUTPUT_BYTES:
        raise ValueError("max_output_bytes is outside the supported parser output budget")
    return max_output_bytes


def _max_request_bytes(max_input_bytes: int) -> int:
    """Return the JSON wire budget for a base64-encoded parser request."""

    encoded_input_bytes = ((max_input_bytes + 2) // 3) * 4
    return encoded_input_bytes + _REQUEST_METADATA_BYTES


def _child_environment(temp_dir: str | None = None) -> dict[str, str]:
    """Build the parser environment without inheriting application secrets."""

    pythonpath = [str(Path(__file__).resolve().parents[2])]
    for runtime_path in _runtime_python_paths():
        if runtime_path.name in {"site-packages", "dist-packages"}:
            pythonpath.append(str(runtime_path))
    return {
        "PATH": _SAFE_CHILD_PATH,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": os.pathsep.join(pythonpath),
        "PYTHONSAFEPATH": "1",
        "PYTHONUNBUFFERED": "1",
        "TMPDIR": temp_dir or "/tmp",
    }


def _sandbox_runtime_bind_args() -> list[str]:
    """Bind only the interpreter and parser code into bwrap's tmpfs root."""

    executable = Path(sys.executable).resolve()
    original_executable = Path(sys.executable).absolute()
    package_root = Path(__file__).resolve().parents[2]
    repository_root = _repository_root(package_root)
    base_prefix = Path(getattr(sys, "base_prefix", sys.prefix)).resolve()
    prefix = Path(sys.prefix).resolve()
    venv_root = (
        repository_root / "apps" / "api" / ".venv" if repository_root is not None else Path("/")
    )
    if any(path == Path("/") for path in (executable, package_root, base_prefix, prefix)):
        return []
    interpreter_root = base_prefix if executable.is_relative_to(base_prefix / "bin") else None
    if not (
        executable.is_file()
        and original_executable.exists()
        and original_executable.parent.name == "bin"
        and repository_root is not None
        and package_root == repository_root / "apps" / "api" / "src"
        and (package_root / "rag_eval_api").is_dir()
        and prefix == venv_root
        and interpreter_root is not None
        and _is_trusted_base_prefix(interpreter_root)
        and (
            _is_secure_runtime_path(
                original_executable, venv_root, os.getuid(), allow_final_symlink=True
            )
            or _is_secure_runtime_path(original_executable, interpreter_root, 0)
        )
        and _is_safe_runtime_entry(executable, interpreter_root)
    ):
        return []
    # Bind only exact interpreter, standard-library, dependency and package
    # directories. In particular, never turn a malformed runtime path into
    # ``--ro-bind / /`` or expose a virtualenv/project root wholesale.
    paths = {str(original_executable), str(executable), str(package_root)}
    paths.update(str(path) for path in _runtime_python_paths())
    arguments: list[str] = []
    created_parents: set[str] = set()
    for source in sorted(paths):
        source_path = Path(source)
        if not source_path.exists():
            return []
        for parent in reversed(source_path.parents):
            parent_string = str(parent)
            if parent_string == "/" or parent_string in created_parents:
                continue
            arguments.extend(("--dir", parent_string))
            created_parents.add(parent_string)
        arguments.extend(("--ro-bind", source, source))
    return arguments


def _runtime_python_paths() -> set[Path]:
    """Return exact stdlib/site-package directories safe to bind read-only."""

    package_root = Path(__file__).resolve().parents[2]
    repository_root = _repository_root(package_root)
    if repository_root is None:
        return set()
    venv_root = repository_root / "apps" / "api" / ".venv"
    base_prefix = Path(getattr(sys, "base_prefix", sys.prefix)).resolve()
    prefix = Path(sys.prefix).resolve()
    if prefix not in {venv_root, Path("/usr"), Path("/usr/local")}:
        return set()
    base_root_allowed = _is_trusted_base_prefix(base_prefix)
    allowed: set[Path] = set()
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        configured = sysconfig.get_path(key)
        if not configured:
            continue
        path = Path(configured).resolve()
        if path == Path("/") or not path.is_dir():
            return set()
        if key in {"purelib", "platlib"}:
            if path.name not in {"site-packages", "dist-packages"}:
                return set()
            if not _is_exact_site_packages(path, venv_root / "lib"):
                return set()
        elif path.name != _PYTHON_LIBRARY_NAME:
            return set()
        elif not (
            _is_exact_python_library(path, venv_root / "lib")
            or (base_root_allowed and _is_exact_python_library(path, base_prefix / "lib"))
        ):
            return set()
        if path.is_relative_to(venv_root / "lib"):
            owner_uid = os.getuid()
            owner_root = venv_root
        else:
            owner_uid = 0
            owner_root = base_prefix
        if not _is_secure_runtime_path(path, owner_root, owner_uid):
            return set()
        allowed.add(path)
    return allowed


def _repository_root(package_root: Path) -> Path | None:
    """Find the checked-out repository that owns the parser package."""

    for parent in package_root.parents:
        if (parent / "apps" / "api" / "pyproject.toml").is_file():
            return parent
    return None


def _is_trusted_base_prefix(prefix: Path) -> bool:
    """Allow only explicit, root-owned Python installation instances."""

    if prefix in {Path("/usr"), Path("/usr/local")}:
        return _is_secure_runtime_path(prefix, prefix, 0)
    hosted_root = Path("/opt/hostedtoolcache") / "Python"
    if not prefix.is_relative_to(hosted_root):
        return False
    relative = prefix.relative_to(hosted_root)
    if len(relative.parts) != 2 or not re.fullmatch(r"3\.\d+(?:\.\d+)?", relative.parts[0]):
        return False
    if relative.parts[1] not in {"x64", "arm64"}:
        return False
    return _is_secure_runtime_path(prefix, hosted_root, 0)


def _is_exact_python_library(path: Path, library_root: Path) -> bool:
    """Accept only the current interpreter's direct library directory."""

    return path.name == _PYTHON_LIBRARY_NAME and path.parent == library_root and path.is_dir()


def _is_exact_site_packages(path: Path, library_root: Path) -> bool:
    """Accept only the direct dependency directory for this interpreter."""

    return (
        path.name in {"site-packages", "dist-packages"}
        and path.parent.name == _PYTHON_LIBRARY_NAME
        and path.parent.parent == library_root
        and path.is_dir()
    )


def _is_secure_runtime_path(
    path: Path,
    root: Path,
    owner_uid: int,
    *,
    allow_final_symlink: bool = False,
) -> bool:
    """Validate every existing component of a trusted runtime path."""

    if not path.is_absolute() or not path.is_relative_to(root):
        return False
    current = path
    while True:
        try:
            stat_result = (
                current.lstat() if current == path and allow_final_symlink else current.stat()
            )
        except OSError:
            return False
        if stat_result.st_uid != owner_uid or stat_result.st_mode & 0o022:
            return False
        if current == root:
            return True
        current = current.parent


def _is_safe_runtime_entry(path: Path, trusted_root: Path) -> bool:
    """Reject writable, non-regular, or out-of-root interpreter files."""

    try:
        stat_result = path.stat()
    except OSError:
        return False
    return (
        path.is_file()
        and _is_secure_runtime_path(path, trusted_root, 0)
        and not stat_result.st_mode & 0o022
    )


@contextmanager
def _private_parser_cwd() -> Iterator[str]:
    """Provide a disposable 0700 working directory for every parser child."""

    with tempfile.TemporaryDirectory(prefix="rag-eval-parser-") as directory:
        try:
            yield directory
        finally:
            try:
                os.chmod(directory, 0o700)
            except FileNotFoundError:
                pass


def _read_bounded(stream: BinaryIO, *, max_bytes: int) -> bytes:
    """Read at most ``max_bytes`` plus one byte from an untrusted pipe."""

    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(64 * 1024, max_bytes + 1 - total))
        if not chunk:
            return b"".join(chunks)
        if not isinstance(chunk, bytes):
            raise TypeError("parser protocol stream must return bytes")
        total += len(chunk)
        if total > max_bytes:
            raise ParserLimitExceeded("parser request exceeds the protocol size limit")
        chunks.append(chunk)


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
    must provide the supported filesystem-isolated ``bwrap`` profile with
    required flags and resource-limit support.
    """

    def __init__(
        self,
        *,
        default_timeout_seconds: float = 10.0,
        max_output_bytes: int = DEFAULT_MAX_PARSER_OUTPUT_BYTES,
        require_resource_limits: bool = False,
        sandbox_executable: str | None = None,
        sandbox_args: Sequence[str] = (),
    ) -> None:
        if default_timeout_seconds <= 0 or not math.isfinite(default_timeout_seconds):
            raise ValueError("default_timeout_seconds must be finite and positive")
        if sandbox_executable is not None and not sandbox_executable.strip():
            raise ValueError("sandbox_executable must not be empty")
        self.default_timeout_seconds = default_timeout_seconds
        self.max_output_bytes = _child_output_limit(max_output_bytes)
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
        if limits.max_input_bytes > MAX_MAX_PARSER_INPUT_BYTES:
            raise ParserLimitExceeded("input bytes exceed the parent parser budget")
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
            max_output_bytes=self.max_output_bytes,
        )
        request_bytes = _json_bytes(request.model_dump(mode="json"))
        if len(request_bytes) > _MAX_CHILD_REQUEST_BYTES or len(request_bytes) > _max_request_bytes(
            limits.max_input_bytes
        ):
            raise ParserLimitExceeded("parser request exceeds the configured input budget")
        process: subprocess.Popen[bytes] | None = None
        with _private_parser_cwd() as cwd:
            try:
                process = subprocess.Popen(
                    self._command(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                    cwd=cwd,
                    env=_child_environment("/tmp" if self.uses_os_sandbox else cwd),
                )
                output, _ = self._communicate_bounded(
                    process,
                    request_bytes,
                    timeout,
                    self.max_output_bytes,
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
            args=(process.stderr, stderr_buffer, _MAX_CHILD_STDERR_BYTES),
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
        if self.uses_os_sandbox:
            child.append("--strict")
        if self.sandbox_executable is None:
            return child
        return [
            self.sandbox_executable,
            *self.sandbox_args,
            *_sandbox_runtime_bind_args(),
            "--",
            *child,
        ]

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
        limits = ParserLimits(**request.limits.model_dump())
        _configure_child_sandbox(
            limits, request.timeout_seconds, sandbox_enabled=request.sandbox_enabled
        )
        max_encoded_bytes = ((limits.max_input_bytes + 2) // 3) * 4
        if len(request.data_b64) > max_encoded_bytes:
            return _error_envelope("size_exceeded", "parser request input exceeds its byte limit")
        data = base64.b64decode(request.data_b64, validate=True)
        if len(data) > limits.max_input_bytes:
            return _error_envelope("size_exceeded", "parser request input exceeds its byte limit")
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


def _configure_startup_limits() -> None:
    """Apply fixed protocol limits before reading any child input."""

    try:
        import resource
    except ImportError as exc:
        raise ParserSandboxUnavailable("process resource limits are unavailable") from exc
    if os.name != "posix" or not all(
        hasattr(resource, name) for name in ("RLIMIT_CPU", "RLIMIT_AS")
    ):
        raise ParserSandboxUnavailable("process resource limits are unavailable")

    try:
        _set_finite_limit(resource, resource.RLIMIT_CPU, _STARTUP_CPU_SECONDS)
        _set_finite_limit(resource, resource.RLIMIT_AS, _STARTUP_MEMORY_BYTES)
    except (OSError, ValueError) as exc:
        raise ParserSandboxUnavailable("process resource limits could not be applied") from exc


def _set_finite_limit(resource_module: object, resource_kind: int, requested: int) -> None:
    getrlimit = cast(object, getattr(resource_module, "getrlimit"))
    setrlimit = cast(object, getattr(resource_module, "setrlimit"))
    current_soft, current_hard = cast(tuple[int, int], getrlimit(resource_kind))  # type: ignore[operator]
    del current_soft
    infinity = cast(int, getattr(resource_module, "RLIM_INFINITY"))
    effective = requested if current_hard == infinity else min(requested, current_hard)
    if effective < 1:
        raise ValueError("resource hard limit is not usable")
    setrlimit(resource_kind, (effective, effective))  # type: ignore[operator]


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
    original_socket = socket.socket
    original_create_connection = socket.create_connection
    request: _RequestEnvelope | None = None
    try:
        try:
            _configure_startup_limits()
        except ParserSandboxUnavailable:
            if "--strict" in sys.argv:
                raise
            _disable_network_fallback()
        request_bytes = _read_bounded(sys.stdin.buffer, max_bytes=_MAX_CHILD_REQUEST_BYTES)
        request = _RequestEnvelope.model_validate(_strict_json_loads(request_bytes))
        envelope = _child_result(request)
    except ParserLimitExceeded as exc:
        envelope = _error_envelope(exc.code, str(exc))
    except ParserSandboxUnavailable as exc:
        envelope = _error_envelope(exc.code, str(exc))
    except BaseException:
        envelope = _error_envelope(
            "parser_sandbox_unavailable", "parser sandbox returned an invalid request"
        )
    finally:
        # Keep the development-only fallback patch scoped to the disposable
        # child. This also makes direct protocol tests unable to corrupt the
        # parent interpreter's networking primitives.
        setattr(socket, "socket", original_socket)
        setattr(socket, "create_connection", original_create_connection)
    payload = _json_bytes(envelope.model_dump(mode="json"))
    if request is not None and len(payload) > request.max_output_bytes:
        payload = _json_bytes(
            _error_envelope(
                "parser_sandbox_unavailable", "parser sandbox output exceeded the limit"
            ).model_dump(mode="json")
        )
    sys.stdout.buffer.write(payload)
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
