"""Structured logging: JSON events in production, readable console in dev.

Every access-log line carries the request id (also returned to clients in the
``X-Request-ID`` header and in error envelopes), so a user-reported error can
be joined to its exact server-side records. Query strings are scrubbed before
logging: token-bearing parameters must never reach access logs.
"""

import logging
import time
from urllib.parse import parse_qsl, urlencode

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from incident_desk.middleware import get_request_id

SENSITIVE_QUERY_KEYS = {"token", "ticket", "refresh_token", "mfa_token", "access_token"}

access_logger = structlog.get_logger("incident_desk.access")


def configure_logging(json_output: bool) -> None:
    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    logging.getLogger("incident_desk.access").setLevel(logging.INFO)
    logging.getLogger("incident_desk.ratelimit").setLevel(logging.WARNING)


def scrub_query(query_string: str) -> str:
    """Redact token-bearing parameters; keep the rest for debuggability."""
    if not query_string:
        return ""
    pairs = parse_qsl(query_string, keep_blank_values=True)
    scrubbed = [
        (key, "[redacted]" if key.lower() in SENSITIVE_QUERY_KEYS else value)
        for key, value in pairs
    ]
    return urlencode(scrubbed)


class AccessLogMiddleware:
    """Pure ASGI: one structured log line per HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_holder = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            access_logger.info(
                "request",
                method=scope.get("method", ""),
                path=scope.get("path", ""),
                query=scrub_query(scope.get("query_string", b"").decode("latin-1")),
                status=status_holder["status"],
                duration_ms=duration_ms,
                request_id=get_request_id(),
            )
