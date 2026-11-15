"""The gateway layer: everything every request passes through before and after the routes.

  - a request id (X-Request-ID, taken from the caller if sensible), echoed in the response and the log
  - rate limiting per client address, with Retry-After
  - a cap on request body size
  - security headers
  - one access-log line and the HTTP metrics per request (route template, never the query string)

Written as plain ASGI rather than BaseHTTPMiddleware so it works for WebSockets and for streaming responses (SSE)."""
import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from typing import Optional

import config
from gateway.limiter import EXEMPT, LIMITER, classify
from observability import metrics

log = logging.getLogger("sahaj.access")
request_id: ContextVar[Optional[str]] = ContextVar("request_id", default=None)

VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-resource-policy", b"same-site"),
]
NO_STORE = ("/auth/", "/users/", "/admin/", "/chat/")  # responses that hold tokens or personal data are never cached


class BodyTooLarge(Exception):
    pass


def client_ip(scope) -> str:
    if config.TRUST_PROXY_HEADERS:
        for name, value in scope["headers"]:
            if name == b"x-forwarded-for":
                return value.decode("latin-1").split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


def _header(scope, name: bytes) -> Optional[str]:
    for key, value in scope["headers"]:
        if key == name:
            return value.decode("latin-1")
    return None


async def _reject(send, status: int, detail: str, rid: str, extra=()) -> None:
    body = json.dumps({"detail": detail, "request_id": rid}).encode()
    await send({"type": "http.response.start", "status": status, "headers": [
        (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
        (b"x-request-id", rid.encode()), *extra]})
    await send({"type": "http.response.body", "body": body})


class Gateway:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            return await self._websocket(scope, receive, send)
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        incoming = _header(scope, b"x-request-id")
        rid = incoming if incoming and VALID_ID.match(incoming) else uuid.uuid4().hex
        token = request_id.set(rid)
        method, path, started = scope["method"], scope["path"], time.perf_counter()
        state = {"status": 500, "sent": False, "too_large": False}
        too_large = json.dumps({"detail": "The request is too large.", "request_id": rid}).encode()

        async def send_wrapped(message):
            if state["too_large"] and not state["sent"] and message["type"] == "http.response.start":
                # The framework turned our abort into its own 400; what the caller should see is 413.
                message = {**message, "status": 413, "headers": [
                    (b"content-type", b"application/json"), (b"content-length", str(len(too_large)).encode())]}
            elif state["too_large"] and message["type"] == "http.response.body":
                message = {**message, "body": too_large, "more_body": False}
            if message["type"] == "http.response.start":
                state["status"], state["sent"] = message["status"], True
                headers = [h for h in message["headers"] if h[0] != b"x-request-id"]
                headers.append((b"x-request-id", rid.encode()))
                headers.extend(SECURITY_HEADERS)
                if path.startswith(NO_STORE):
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        try:
            if config.RATE_LIMIT_ENABLED and path not in EXEMPT and method != "OPTIONS":
                cls, per_minute = classify(path)
                wait = LIMITER.check(cls, client_ip(scope), per_minute)
                if wait is not None:
                    metrics.RATE_LIMITED.labels(cls).inc()
                    state["status"] = 429
                    return await _reject(send_wrapped, 429, "Too many requests. Please slow down.", rid,
                                         [(b"retry-after", str(max(1, round(wait))).encode())])

            length = _header(scope, b"content-length")
            if length and length.isdigit() and int(length) > config.MAX_BODY_BYTES:
                state["status"] = 413
                return await _reject(send_wrapped, 413, "The request is too large.", rid)

            received = 0

            async def receive_counted():  # chunked bodies have no Content-Length, so count what actually arrives
                nonlocal received
                message = await receive()
                received += len(message.get("body", b"")) if message["type"] == "http.request" else 0
                if received > config.MAX_BODY_BYTES:
                    state["too_large"] = True
                    raise BodyTooLarge()
                return message

            try:
                await self.app(scope, receive_counted, send_wrapped)
            except BodyTooLarge:
                if not state["sent"]:
                    state["status"] = 413
                    await _reject(send_wrapped, 413, "The request is too large.", rid)
            except Exception:
                log.exception("Unhandled error", extra={"request_id": rid})
                if not state["sent"]:
                    state["status"] = 500
                    await _reject(send_wrapped, 500, "Something went wrong.", rid)
        finally:
            elapsed = time.perf_counter() - started
            route = getattr(scope.get("route"), "path", None) or ("unmatched" if state["status"] != 429 else "rate_limited")
            if path not in ("/metrics",):
                metrics.HTTP_REQUESTS.labels(method, route, str(state["status"])).inc()
                metrics.HTTP_SECONDS.labels(method, route).observe(elapsed)
            # The path only: query strings can carry access tokens (WebSocket) and are never logged.
            log.info("%s %s %s %.1fms", method, path, state["status"], elapsed * 1000,
                     extra={"request_id": rid, "status": state["status"], "ms": round(elapsed * 1000, 1),
                            "client": client_ip(scope), "route": route})
            request_id.reset(token)

    async def _websocket(self, scope, receive, send):
        if config.RATE_LIMIT_ENABLED:
            wait = LIMITER.check("ws", client_ip(scope), config.RATE_LIMIT_WS_PER_MIN)
            if wait is not None:
                metrics.RATE_LIMITED.labels("ws").inc()
                await receive()  # the connect message
                return await send({"type": "websocket.close", "code": 1008})  # refused before it is accepted
        await self.app(scope, receive, send)
