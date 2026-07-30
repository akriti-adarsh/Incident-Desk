"""Graceful shutdown helpers.

On SIGTERM, uvicorn stops accepting new connections and waits for in-flight
HTTP requests to finish before running the lifespan shutdown. WebSockets do
not drain on their own, so the app tracks open sockets and closes them with
code 1001 ("going away") during shutdown, letting clients reconnect to a
healthy replica instead of seeing an abrupt drop.
"""

import asyncio
from typing import Protocol

import structlog

logger = structlog.get_logger("incident_desk.shutdown")

WS_GOING_AWAY = 1001


class Closable(Protocol):
    async def close(self, code: int = ...) -> None: ...


class ConnectionRegistry:
    """Tracks open WebSocket connections so shutdown can drain them."""

    def __init__(self) -> None:
        self._connections: set[Closable] = set()

    def add(self, connection: Closable) -> None:
        self._connections.add(connection)

    def discard(self, connection: Closable) -> None:
        self._connections.discard(connection)

    @property
    def count(self) -> int:
        return len(self._connections)

    async def drain(self) -> int:
        """Close every tracked connection; returns how many were drained."""
        connections = list(self._connections)
        if connections:
            logger.info("draining_websockets", count=len(connections))
        results = await asyncio.gather(
            *(self._close(c) for c in connections), return_exceptions=True
        )
        self._connections.clear()
        return sum(1 for r in results if not isinstance(r, Exception))

    async def _close(self, connection: Closable) -> None:
        await connection.close(code=WS_GOING_AWAY)
