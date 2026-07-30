"""Cross-instance delivery: two app instances, one Redis, one message.

Instance A handles the HTTP write; instance B holds the WebSocket. The only
path between them is Redis pub/sub, so receiving the event on B proves the
fan-out works across replicas, not just within one process.
"""

import uuid
from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from incident_desk.config import get_settings
from tests.test_realtime_ws import Stack, login_headers, mint_ticket, stack

pytestmark = pytest.mark.timeout(60)

_ = stack  # re-exported fixture (committed org/users/incident)


@pytest.fixture
def two_instances(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, TestClient]]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("RATE_LIMIT_NAMESPACE", f"x-{uuid.uuid4().hex[:12]}")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_PER_MINUTE", "500")
    get_settings.cache_clear()
    from incident_desk.main import create_app

    # Two separate FastAPI applications: separate engines, separate brokers,
    # separate pubsub connections; only Redis and Postgres are shared.
    with TestClient(create_app()) as instance_a, TestClient(create_app()) as instance_b:
        yield instance_a, instance_b
    get_settings.cache_clear()


def test_event_published_on_instance_a_reaches_socket_on_instance_b(
    two_instances: tuple[TestClient, TestClient], stack: Stack
) -> None:
    instance_a, instance_b = two_instances

    headers_a = login_headers(instance_a, stack.email_a)
    headers_b = login_headers(instance_b, stack.email_b)
    ticket_b = mint_ticket(instance_b, headers_b)

    with instance_b.websocket_connect(f"/ws?ticket={ticket_b}") as ws:
        ws.send_json({"action": "subscribe", "channel": f"org:{stack.org_slug}:incidents"})
        assert ws.receive_json()["type"] == "subscribed"

        created = instance_a.post(
            f"/api/v1/orgs/{stack.org_slug}/incidents",
            json={
                "service_id": str(stack.service_id),
                "title": "crossed the wire",
                "severity": "sev1",
            },
            headers=headers_a,
        )
        assert created.status_code == 201

        event = ws.receive_json()
        assert event["type"] == "incident.created"
        assert event["title"] == "crossed the wire"
        assert event["severity"] == "sev1"


def test_incident_channel_also_crosses_instances(
    two_instances: tuple[TestClient, TestClient], stack: Stack
) -> None:
    instance_a, instance_b = two_instances

    headers_a = login_headers(instance_a, stack.email_a)
    headers_b = login_headers(instance_b, stack.email_b)
    ticket_b = mint_ticket(instance_b, headers_b)
    channel = f"incident:{stack.incident_id}"

    with instance_b.websocket_connect(f"/ws?ticket={ticket_b}") as ws:
        ws.send_json({"action": "subscribe", "channel": channel})
        assert ws.receive_json()["type"] == "subscribed"
        assert ws.receive_json()["type"] == "presence.changed"

        comment = instance_a.post(
            f"/api/v1/orgs/{stack.org_slug}/incidents/{stack.incident_id}/comments",
            json={"body": "written on A, read on B"},
            headers=headers_a,
        )
        assert comment.status_code == 201

        event = ws.receive_json()
        assert event["type"] == "comment.added"
        assert event["author_id"] == str(stack.user_a_id)
