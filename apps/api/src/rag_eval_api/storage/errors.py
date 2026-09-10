"""Stable, redacted errors raised by blob stores."""

from __future__ import annotations


class BlobStoreError(Exception):
    """Base class for safe, machine-classifiable blob errors."""

    code = "blob_store_error"


class BlobKeyError(BlobStoreError, ValueError):
    code = "invalid_storage_key"


class BlobNotFound(BlobStoreError, FileNotFoundError):
    code = "blob_not_found"


class BlobAlreadyExists(BlobStoreError, FileExistsError):
    code = "blob_already_exists"


class BlobSizeExceeded(BlobStoreError, ValueError):
    code = "size_exceeded"


class BlobChecksumMismatch(BlobStoreError, ValueError):
    code = "checksum_mismatch"


class BlobSecurityError(BlobStoreError, PermissionError):
    code = "blob_security_error"
