"""Low-level ASGI middleware for request-wide resource limits."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from starlette.responses import JSONResponse

ASGIMessage = MutableMapping[str, Any]
ASGIScope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[ASGIMessage]]
Send = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp = Callable[[ASGIScope, Receive, Send], Awaitable[None]]


class RequestBodyLimitMiddleware:
    """Reject oversized bodies before Starlette parses multipart form fields."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: ASGIScope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        content_length = self._content_length(scope)
        if content_length is not None and content_length > self.max_body_bytes:
            await self._send_rejection(scope, receive, send)
            return

        received_bytes = 0
        exceeded = False

        async def limited_receive() -> ASGIMessage:
            nonlocal received_bytes, exceeded
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def limited_send(message: ASGIMessage) -> None:
            if not exceeded:
                await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded:
            await self._send_rejection(scope, receive, send)

    @staticmethod
    def _content_length(scope: ASGIScope) -> int | None:
        for key, value in scope.get("headers", []):
            if key.lower() != b"content-length":
                continue
            try:
                length = int(value)
            except (TypeError, ValueError):
                return None
            return length if length >= 0 else None
        return None

    async def _send_rejection(self, scope: ASGIScope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "size_exceeded",
                    "message": "Request body exceeds the configured size limit.",
                }
            },
        )
        await response(scope, receive, send)
