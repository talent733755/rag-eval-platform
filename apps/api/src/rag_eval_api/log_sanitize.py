"""Shared sanitizers for structured logging and error propagation.

Kept in a leaf module so both the API entrypoint and the workers can redact
untrusted text without importing :mod:`rag_eval_api.main` (which instantiates
the FastAPI application at import time).
"""

from __future__ import annotations

import re


def redact_text(text: str) -> str:
    redacted = re.sub(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s]+", "[redacted-url]", text)
    return re.sub(
        r"(?i)\b(password|passwd|secret|token|api[_-]?key)\s*=\s*[^\s]+",
        r"\1=[redacted]",
        redacted,
    )[:200]


def sanitize_exception(exc: Exception) -> str:
    """Keep exception context useful while removing URLs and common credentials."""

    message = re.sub(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s]+", "[redacted-url]", str(exc))
    message = re.sub(
        r"(?i)\b(password|passwd|secret|token|api[_-]?key)\s*=\s*[^\s]+",
        r"\1=[redacted]",
        message,
    )
    return message[:200]
