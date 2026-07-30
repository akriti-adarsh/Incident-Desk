"""Request-scoped context: request id assignment and propagation.

Every request gets an id that is echoed in the ``X-Request-ID`` response
header and embedded in error envelopes, so a user-visible error can be traced
to the exact server-side log lines.
"""

import re
import uuid
from contextvars import ContextVar

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Return the id of the request currently being handled, or ``-`` outside one."""
    return _request_id.get()


class RequestIDMiddleware:
    """Pure ASGI middleware assigning a per-request id.

    An inbound ``X-Request-ID`` is honoured when it looks like a sane id
    (so a client retrying a request can carry one id across attempts);
    anything else is replaced with a fresh uuid4 hex.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        inbound = Headers(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = inbound if _VALID_REQUEST_ID.fullmatch(inbound) else uuid.uuid4().hex
        token = _request_id.set(request_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _request_id.reset(token)
