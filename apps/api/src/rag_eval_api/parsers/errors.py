"""Stable parser error taxonomy for API and worker layers."""

from __future__ import annotations


class ParserError(Exception):
    code = "parse_failed"
    retryable = False


class UnsupportedDocumentError(ParserError):
    code = "unsupported_type"


class MalformedDocumentError(ParserError):
    code = "parse_failed"


class ParserLimitExceeded(ParserError):
    code = "size_exceeded"


class ParserSecurityError(ParserError):
    code = "parse_failed"


class ParserTimeout(ParserError):
    code = "parse_timeout"
    retryable = True


class ParserSandboxUnavailable(ParserError):
    code = "parser_sandbox_unavailable"
