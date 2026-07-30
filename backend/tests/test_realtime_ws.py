"""WebSockets: ticket auth, channel authorisation, delivery, presence, heartbeat.

These tests run the real app (lifespan included: Redis broker and all) via
Starlette's TestClient, against really committed rows, because WebSocket
subscribers and HTTP publishers use separate database sessions.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy import delete, make_url
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from incident_desk.config import get_settings
from incident_desk.db import models
from incident_desk.enums import Role, ServiceTier, Severity
from tests.factories import PASSWORD, PASSWORD_HASH

pytestmark = pytest.mark.timeout(60)


@dataclass
class Stack:
    org_slug: str = ""
    other_slug: str = ""
    email_a: str = ""
    email_b: str = ""
    user_a_id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_b_id: uuid.UUID = field(default_factory=uuid.uuid4)
    service_id: uuid.UUID = field(default_factory=uuid.uuid4)
    incident_id: uuid.UUID = field(default_factory=uuid.uuid4)


@pytest.fixture
def stack(database_url: str) -> Iterator[Stack]:
    """Really committed org/users/incident, removed again afterwards."""
    from datetime import UTC, datetime

    sync_url = make_url(database_url).set(drivername="postgresql+psycopg")
    engine = create_sync_engine(sync_url)
    ctx = Stack()
    suffix = uuid.uuid4().hex[:10]
    ctx.org_slug = f"rt-{suffix}"
    ctx.other_slug = f"rt-other-{suffix}"
    ctx.email_a = f"rt-a-{suffix}@example.com"
    ctx.email_b = f"rt-b-{suffix}@example.com"

    with Session(engine) as session:
        user_a = models.User(
            email=ctx.email_a,
            password_hash=PASSWORD_HASH,
            full_name="Realtime A",
            email_verified_at=datetime.now(UTC),
        )
        user_b = models.User(
            email=ctx.email_b,
            password_hash=PASSWORD_HASH,
            full_name="Realtime B",
            email_verified_at=datetime.now(UTC),
        )
        org = models.Organization(name="RT Org", slug=ctx.org_slug)
        other = models.Organization(name="Other Org", slug=ctx.other_slug)
        session.add_all([user_a, user_b, org, other])
        session.flush()
        service = models.Service(org_id=org.id, name="rt-svc", tier=ServiceTier.TIER2)
        session.add_all(
            [
                models.Membership(user_id=user_a.id, org_id=org.id, role=Role.OWNER),
                models.Membership(user_id=user_b.id, org_id=org.id, role=Role.RESPONDER),
                models.Membership(user_id=user_b.id, org_id=other.id, role=Role.OWNER),
                models.OrganizationCounter(org_id=org.id),
                models.OrganizationCounter(org_id=other.id),
                service,
            ]
        )
        session.flush()
        incident = models.Incident(
            org_id=org.id,
            service_id=service.id,
            sequence_number=1,
            title="rt incident",
            severity=Severity.SEV3,
            reported_by=user_a.id,
        )
        counter = session.get(models.OrganizationCounter, org.id)
        assert counter is not None
        counter.incident_seq = 1
        session.add(incident)
        session.flush()
        ctx.user_a_id, ctx.user_b_id = user_a.id, user_b.id
        ctx.service_id, ctx.incident_id = service.id, incident.id
        org_id, other_id = org.id, other.id
        session.commit()

    yield ctx

    with Session(engine) as session:
        session.execute(delete(models.Organization).where(models.Organization.id == org_id))
        session.execute(delete(models.Organization).where(models.Organization.id == other_id))
        session.execute(delete(models.User).where(models.User.id == ctx.user_a_id))
        session.execute(delete(models.User).where(models.User.id == ctx.user_b_id))
        session.commit()
    engine.dispose()


@pytest.fixture
def rt_client(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("RATE_LIMIT_NAMESPACE", f"rt-{uuid.uuid4().hex[:12]}")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_PER_MINUTE", "500")
    get_settings.cache_clear()
    from incident_desk.main import create_app

    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


def login_headers(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def mint_ticket(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/api/v1/ws-ticket", headers=headers)
    assert response.status_code == 200
    ticket: str = response.json()["data"]["ticket"]
    return ticket


def test_ticket_flow_and_replay_rejection(rt_client: TestClient, stack: Stack) -> None:
    headers = login_headers(rt_client, stack.email_a)
    ticket = mint_ticket(rt_client, headers)

    with rt_client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        ws.send_json({"action": "subscribe", "channel": f"org:{stack.org_slug}:incidents"})
        assert ws.receive_json() == {
            "type": "subscribed",
            "channel": f"org:{stack.org_slug}:incidents",
        }
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}

    # The consumed ticket is dead: a replayed connect is closed with 4401.
    with rt_client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4401


def test_missing_or_garbage_ticket_is_rejected(rt_client: TestClient) -> None:
    for url in ("/ws", "/ws?ticket=not-a-ticket"):
        with rt_client.websocket_connect(url) as ws:
            message = ws.receive()
            assert message["type"] == "websocket.close"
            assert message["code"] == 4401


def test_cross_org_subscription_is_rejected(rt_client: TestClient, stack: Stack) -> None:
    headers = login_headers(rt_client, stack.email_a)
    ticket = mint_ticket(rt_client, headers)
    with rt_client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        # user_a is not a member of the other org; a made-up org answers identically.
        for channel in (
            f"org:{stack.other_slug}:incidents",
            "org:no-such-org:incidents",
            f"incident:{uuid.uuid4()}",
        ):
            ws.send_json({"action": "subscribe", "channel": channel})
            response = ws.receive_json()
            assert response["type"] == "error"
            assert response["code"] == "forbidden_channel"


def test_incident_events_reach_org_subscribers(rt_client: TestClient, stack: Stack) -> None:
    headers = login_headers(rt_client, stack.email_a)
    ticket = mint_ticket(rt_client, headers)
    with rt_client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        ws.send_json({"action": "subscribe", "channel": f"org:{stack.org_slug}:incidents"})
        assert ws.receive_json()["type"] == "subscribed"

        created = rt_client.post(
            f"/api/v1/orgs/{stack.org_slug}/incidents",
            json={
                "service_id": str(stack.service_id),
                "title": "socket sees this",
                "severity": "sev2",
            },
            headers=headers,
        )
        assert created.status_code == 201

        event = ws.receive_json()
        assert event["type"] == "incident.created"
        assert event["title"] == "socket sees this"

        acked = rt_client.post(
            f"/api/v1/orgs/{stack.org_slug}/incidents/{stack.incident_id}/status",
            json={"status": "acknowledged"},
            headers=headers,
        )
        assert acked.status_code == 200
        event = ws.receive_json()
        assert event["type"] == "incident.status_changed"
        assert event["to"] == "acknowledged"


def test_comments_and_presence_on_incident_channel(rt_client: TestClient, stack: Stack) -> None:
    headers_a = login_headers(rt_client, stack.email_a)
    headers_b = login_headers(rt_client, stack.email_b)
    channel = f"incident:{stack.incident_id}"

    with rt_client.websocket_connect(f"/ws?ticket={mint_ticket(rt_client, headers_a)}") as ws_a:
        ws_a.send_json({"action": "subscribe", "channel": channel})
        assert ws_a.receive_json()["type"] == "subscribed"
        presence = ws_a.receive_json()
        assert presence["type"] == "presence.changed"
        assert presence["viewers"] == [str(stack.user_a_id)]

        with rt_client.websocket_connect(f"/ws?ticket={mint_ticket(rt_client, headers_b)}") as ws_b:
            ws_b.send_json({"action": "subscribe", "channel": channel})
            assert ws_b.receive_json()["type"] == "subscribed"
            joined = ws_a.receive_json()
            assert joined["type"] == "presence.changed"
            assert set(joined["viewers"]) == {str(stack.user_a_id), str(stack.user_b_id)}

            comment = rt_client.post(
                f"/api/v1/orgs/{stack.org_slug}/incidents/{stack.incident_id}/comments",
                json={"body": "seen live"},
                headers=headers_b,
            )
            assert comment.status_code == 201
            ws_b.receive_json()  # ws_b's own presence event from its subscribe
            event_a = ws_a.receive_json()
            assert event_a["type"] == "comment.added"
            assert event_a["author_id"] == str(stack.user_b_id)

        # ws_b disconnected: its presence entry is removed and broadcast.
        left = ws_a.receive_json()
        assert left["type"] == "presence.changed"
        assert left["viewers"] == [str(stack.user_a_id)]


def test_presence_window_expires_stale_viewers(rt_client: TestClient, stack: Stack) -> None:
    """A crashed client ages out of the ZSET window without any cleanup running."""
    import asyncio
    import time

    from redis.asyncio import Redis

    from incident_desk.services import realtime

    async def scenario() -> list[str]:
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            incident_id = str(uuid.uuid4())
            await realtime.presence_touch(redis, incident_id, "crashed-user")
            # Backdate the entry beyond the window instead of sleeping.
            await redis.zadd(
                f"presence:incident:{incident_id}",
                {"crashed-user": time.time() - realtime.PRESENCE_WINDOW_SECONDS - 1},
            )
            await realtime.presence_touch(redis, incident_id, "live-user")
            return await realtime.presence_viewers(redis, incident_id)
        finally:
            await redis.aclose()

    viewers = asyncio.run(scenario())
    assert viewers == ["live-user"]
