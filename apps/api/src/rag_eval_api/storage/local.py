"""Atomic, private local filesystem blob store.

All filesystem operations after initialization use directory descriptors and
``*at``-style calls. User-controlled storage keys therefore cannot turn an
exists-then-use pathname check into a symlink traversal race.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import logging
import os
import re
import secrets
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from rag_eval_api.storage.errors import (
    BlobAlreadyExists,
    BlobChecksumMismatch,
    BlobKeyError,
    BlobNotFound,
    BlobSecurityError,
    BlobSizeExceeded,
)
from rag_eval_api.storage.protocol import BlobObject, StoredBlob

LOGGER = logging.getLogger(__name__)
_KEY_PATTERN = re.compile(r"^[a-z2-7]{16}/[a-z2-7]{32}$")
_BUCKET_PATTERN = re.compile(r"^[a-z2-7]{16}$")
_OBJECT_PATTERN = re.compile(r"^[a-z2-7]{32}$")
_READ_CHUNK_SIZE = 1024 * 1024
_STALE_UPLOAD_PREFIX = ".upload-"


class LocalBlobStore:
    """A private local backend with no overwrite and atomic publication."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_bytes: int = 50 * 1024 * 1024,
        stale_upload_ttl_seconds: int = 24 * 60 * 60,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if stale_upload_ttl_seconds < 1:
            raise ValueError("stale_upload_ttl_seconds must be positive")
        raw_root = os.fspath(root)
        if not os.path.isabs(raw_root):
            raise BlobSecurityError("blob root must be an absolute private directory")
        normalized_root = os.path.normpath(os.sep + raw_root.lstrip(os.sep))
        if normalized_root == os.sep:
            raise BlobSecurityError("blob root must not be the system root")
        self.root = Path(normalized_root)
        self.root_fd = self._open_directory_chain(self.root, create=True)
        os.fchmod(self.root_fd, 0o700)
        self.max_bytes = max_bytes
        self.stale_upload_ttl_seconds = stale_upload_ttl_seconds
        self.reap_stale_uploads()

    def __enter__(self) -> LocalBlobStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()

    def close(self) -> None:
        """Close the pinned root descriptor."""

        if self.root_fd >= 0:
            os.close(self.root_fd)
            self.root_fd = -1

    def put(
        self,
        source: BinaryIO,
        *,
        expected_sha256: str | None = None,
        max_bytes: int | None = None,
    ) -> StoredBlob:
        limit = self.max_bytes if max_bytes is None else min(max_bytes, self.max_bytes)
        if limit < 1:
            raise ValueError("max_bytes must be positive")
        temp_path: Path | None = None
        try:
            temp_path = self._write_temp(source, limit=limit)
            byte_size, sha256 = self._digest_file(temp_path)
            if expected_sha256 is not None and sha256 != expected_sha256:
                raise BlobChecksumMismatch("blob checksum does not match the declared digest")
            key = self._new_key()
            self._publish_temp_name(temp_path.name, key)
            temp_path = None
            LOGGER.info("blob stored", extra={"blob_size": byte_size, "blob_sha256": sha256})
            return StoredBlob(storage_key=key, byte_size=byte_size, sha256=sha256)
        finally:
            if temp_path is not None:
                self._unlink_name_quietly(temp_path.name)

    def _write_temp(self, source: BinaryIO, *, limit: int | None = None) -> Path:
        effective_limit = self.max_bytes if limit is None else limit
        temp_name = self._new_temp_name()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._close_on_exec_flag()
        try:
            fd = os.open(temp_name, flags, 0o600, dir_fd=self.root_fd)
        except OSError as exc:
            raise BlobSecurityError("blob temporary file could not be created safely") from exc
        try:
            with os.fdopen(fd, "wb") as destination:
                total = 0
                while True:
                    chunk = source.read(_READ_CHUNK_SIZE)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        raise TypeError("blob source must return bytes")
                    total += len(chunk)
                    if total > effective_limit:
                        raise BlobSizeExceeded("blob exceeds the configured size limit")
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
        except BaseException:
            self._unlink_name_quietly(temp_name)
            raise
        return self.root / temp_name

    def _digest_file(self, path: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        try:
            fd = os.open(
                path.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | self._close_on_exec_flag(),
                dir_fd=self.root_fd,
            )
        except FileNotFoundError as exc:
            raise BlobNotFound("blob temporary file does not exist") from exc
        except OSError as exc:
            raise BlobSecurityError("blob temporary file could not be opened safely") from exc
        with os.fdopen(fd, "rb") as source:
            while chunk := source.read(_READ_CHUNK_SIZE):
                size += len(chunk)
                digest.update(chunk)
        return size, digest.hexdigest()

    def _new_key(self) -> str:
        token = base64.b32encode(secrets.token_bytes(30)).decode("ascii").lower().rstrip("=")
        return f"{token[:16]}/{token[16:48]}"

    @staticmethod
    def _new_temp_name() -> str:
        return f"{_STALE_UPLOAD_PREFIX}{secrets.token_urlsafe(24)}"

    @staticmethod
    def _close_on_exec_flag() -> int:
        return getattr(os, "O_CLOEXEC", 0)

    @staticmethod
    def _directory_flags() -> int:
        required = getattr(os, "O_DIRECTORY", 0)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if not required or not nofollow or os.open not in os.supports_dir_fd:
            raise BlobSecurityError("secure directory-descriptor storage is unavailable")
        return os.O_RDONLY | required | nofollow | LocalBlobStore._close_on_exec_flag()

    @classmethod
    def _open_directory_chain(cls, path: Path, *, create: bool) -> int:
        flags = cls._directory_flags()
        fd: int | None = None
        try:
            fd = os.open(os.sep, flags)
            for component in path.parts[1:]:
                if component in {"", ".", ".."}:
                    raise BlobSecurityError("blob root contains an unsafe path component")
                if create:
                    try:
                        os.mkdir(component, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                next_fd = os.open(component, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            return fd
        except BlobSecurityError:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise
        except OSError as exc:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if exc.errno == errno.ELOOP:
                raise BlobSecurityError("blob root or an existing parent is a symlink") from exc
            raise BlobSecurityError(
                "blob root or an existing parent is not a safe directory or symlink"
            ) from exc

    def _open_bucket(self, prefix: str, *, create: bool) -> int:
        if not re.fullmatch(r"[a-z2-7]{16}", prefix):
            raise BlobKeyError("storage key is not a valid opaque key")
        flags = self._directory_flags()
        try:
            if create:
                try:
                    os.mkdir(prefix, 0o700, dir_fd=self.root_fd)
                except FileExistsError:
                    pass
            fd = os.open(prefix, flags, dir_fd=self.root_fd)
            if create:
                os.fchmod(fd, 0o700)
            return fd
        except FileNotFoundError as exc:
            raise BlobNotFound("blob does not exist") from exc
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise BlobKeyError("storage key resolves through a symlink") from exc
            raise BlobKeyError("storage key resolves through an unsafe directory") from exc

    def _parse_key(self, storage_key: str) -> tuple[str, str]:
        if not isinstance(storage_key, str) or not _KEY_PATTERN.fullmatch(storage_key):
            raise BlobKeyError("storage key is not a valid opaque key")
        return tuple(storage_key.split("/", 1))  # type: ignore[return-value]

    def _path_for_key(self, storage_key: str) -> Path:
        prefix, filename = self._parse_key(storage_key)
        return self.root / prefix / filename

    def _publish_temp_name(self, temp_name: str, storage_key: str) -> None:
        prefix, filename = self._parse_key(storage_key)
        bucket_fd: int | None = None
        try:
            bucket_fd = self._open_bucket(prefix, create=True)
            os.link(
                temp_name,
                filename,
                src_dir_fd=self.root_fd,
                dst_dir_fd=bucket_fd,
                follow_symlinks=False,
            )
            destination_fd = os.open(
                filename,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | self._close_on_exec_flag(),
                dir_fd=bucket_fd,
            )
            try:
                os.fsync(destination_fd)
            finally:
                os.close(destination_fd)
            os.fsync(bucket_fd)
            os.unlink(temp_name, dir_fd=self.root_fd)
            os.fsync(self.root_fd)
        except FileExistsError as exc:
            raise BlobAlreadyExists("blob storage key already exists") from exc
        except BlobAlreadyExists:
            raise
        except OSError as exc:
            raise BlobSecurityError("blob could not be published safely") from exc
        finally:
            if bucket_fd is not None:
                os.close(bucket_fd)
            self._unlink_name_quietly(temp_name)

    def _publish_temp_file(self, temp_path: Path, destination: Path) -> None:
        """Compatibility helper retained for deterministic low-level tests."""

        try:
            relative = destination.relative_to(self.root)
        except ValueError as exc:
            raise BlobKeyError("destination is outside the private blob root") from exc
        self._publish_temp_name(temp_path.name, str(relative))

    @contextmanager
    def open(self, storage_key: str) -> Iterator[BinaryIO]:
        prefix, filename = self._parse_key(storage_key)
        bucket_fd = self._open_bucket(prefix, create=False)
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | self._close_on_exec_flag()
            try:
                fd = os.open(filename, flags, dir_fd=bucket_fd)
            except FileNotFoundError as exc:
                raise BlobNotFound("blob does not exist") from exc
            except OSError as exc:
                raise BlobSecurityError("blob could not be opened safely") from exc
        finally:
            os.close(bucket_fd)
        try:
            with os.fdopen(fd, "rb") as handle:
                yield handle
        finally:
            pass

    def exists(self, storage_key: str) -> bool:
        prefix, filename = self._parse_key(storage_key)
        try:
            bucket_fd = self._open_bucket(prefix, create=False)
        except BlobNotFound:
            return False
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | self._close_on_exec_flag()
            try:
                fd = os.open(filename, flags, dir_fd=bucket_fd)
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise BlobSecurityError("blob existence could not be checked safely") from exc
            try:
                return stat.S_ISREG(os.fstat(fd).st_mode)
            finally:
                os.close(fd)
        finally:
            os.close(bucket_fd)

    def delete(self, storage_key: str) -> None:
        prefix, filename = self._parse_key(storage_key)
        bucket_fd = self._open_bucket(prefix, create=False)
        try:
            try:
                metadata = os.stat(filename, dir_fd=bucket_fd, follow_symlinks=False)
            except FileNotFoundError as exc:
                raise BlobNotFound("blob does not exist") from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise BlobKeyError("storage key resolves to an unsafe file")
            os.unlink(filename, dir_fd=bucket_fd)
            os.fsync(bucket_fd)
        except OSError as exc:
            raise BlobSecurityError("blob could not be deleted safely") from exc
        finally:
            os.close(bucket_fd)

    def iter_objects(self) -> Iterator[BlobObject]:
        """Yield only published regular objects from the private root."""

        for prefix in os.listdir(self.root_fd):
            if not _BUCKET_PATTERN.fullmatch(prefix):
                continue
            try:
                bucket_fd = self._open_bucket(prefix, create=False)
            except (BlobKeyError, BlobNotFound, BlobSecurityError):
                LOGGER.warning("blob object enumeration skipped", extra={"cleanup_failed": True})
                continue
            try:
                for filename in os.listdir(bucket_fd):
                    if not _OBJECT_PATTERN.fullmatch(filename):
                        continue
                    try:
                        metadata = os.stat(filename, dir_fd=bucket_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if not stat.S_ISREG(metadata.st_mode):
                        continue
                    yield BlobObject(
                        storage_key=f"{prefix}/{filename}",
                        byte_size=metadata.st_size,
                        modified_at=datetime.fromtimestamp(metadata.st_mtime, UTC),
                    )
            finally:
                os.close(bucket_fd)

    def reap_stale_uploads(self, *, ttl_seconds: int | None = None) -> int:
        """Remove only old regular temp files directly under the private root."""

        ttl = self.stale_upload_ttl_seconds if ttl_seconds is None else ttl_seconds
        if ttl < 1:
            raise ValueError("ttl_seconds must be positive")
        cutoff = time.time() - ttl
        removed = 0
        for name in os.listdir(self.root_fd):
            if not name.startswith(_STALE_UPLOAD_PREFIX):
                continue
            try:
                metadata = os.stat(name, dir_fd=self.root_fd, follow_symlinks=False)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_mtime >= cutoff:
                    continue
                os.unlink(name, dir_fd=self.root_fd)
                removed += 1
            except FileNotFoundError:
                continue
            except OSError:
                LOGGER.warning("blob stale upload cleanup failed", extra={"cleanup_failed": True})
        if removed:
            os.fsync(self.root_fd)
        return removed

    def _unlink_name_quietly(self, name: str) -> None:
        try:
            os.unlink(name, dir_fd=self.root_fd)
        except FileNotFoundError:
            pass
        except OSError:
            LOGGER.warning("blob temporary cleanup failed", extra={"cleanup_failed": True})
