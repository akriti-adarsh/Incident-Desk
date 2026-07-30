"""Graceful shutdown: WebSockets are drained with code 1001 on shutdown."""

from incident_desk.shutdown import WS_GOING_AWAY, ConnectionRegistry


class FakeWebSocket:
    def __init__(self) -> None:
        self.closed_with: int | None = None

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


async def test_registry_drains_all_connections() -> None:
    registry = ConnectionRegistry()
    sockets = [FakeWebSocket() for _ in range(3)]
    for s in sockets:
        registry.add(s)
    assert registry.count == 3

    drained = await registry.drain()
    assert drained == 3
    assert registry.count == 0
    assert all(s.closed_with == WS_GOING_AWAY for s in sockets)


async def test_drain_is_safe_with_no_connections() -> None:
    registry = ConnectionRegistry()
    assert await registry.drain() == 0


async def test_drain_survives_a_failing_close() -> None:
    class Broken(FakeWebSocket):
        async def close(self, code: int = 1000) -> None:
            raise RuntimeError("already gone")

    registry = ConnectionRegistry()
    ok = FakeWebSocket()
    registry.add(ok)
    registry.add(Broken())
    # One socket errors on close; the other still drains, and the count clears.
    drained = await registry.drain()
    assert drained == 1
    assert ok.closed_with == WS_GOING_AWAY
    assert registry.count == 0


async def test_lifespan_drains_a_live_socket(database_url: str) -> None:
    """End to end: a socket registered during the app's life is closed when the
    lifespan shuts down."""
    import os

    from starlette.testclient import TestClient

    from incident_desk.config import get_settings

    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()
    from incident_desk.main import create_app

    app = create_app()
    fake = FakeWebSocket()
    with TestClient(app):
        app.state.ws_registry.add(fake)
    # Exiting the TestClient context runs lifespan shutdown, which drains.
    assert fake.closed_with == WS_GOING_AWAY
    get_settings.cache_clear()
