"""Stable errors for candidate generation transports."""

from __future__ import annotations


class ProviderSecurityError(ValueError):
    """The configured provider endpoint violates the network policy."""


class ProviderTransportError(RuntimeError):
    """A safe, redacted provider transport failure."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)
