"""The WebSocket endpoint: ticket-authenticated, channel-subscribed, heartbeat-guarded.

Protocol (JSON frames):

- client: ``{"action": "subscribe", "channel": "org:<slug>:incidents"}``
  or ``{"action": "subscribe", "channel": "incident:<uuid>"}``
- client: ``{"action": "unsubscribe", "channel": ...}``
- client: ``{"action": "ping"}`` -> server: ``{"type": "pong"}``
- server: ``{"type": "subscribed"|"unsubscribed"|"error"|"pong"|...}`` and
  relayed events (``incident.created``, ``comment.added``, ``presence.changed`` ...)

Heartbeat contract: the server closes a connection that stays silent for 60
seconds (code 4408). Clients ping every 20 seconds, reconnect with exponential
backoff, and after reconnecting must refetch current state through the REST
API to reconcile anything missed: the socket is a change notifier, not a
reliable delivery mechanism.

Close codes: 4401 invalid or replayed ticket, 4408 heartbeat timeout.

Cross-org subscriptions are rejected with one uniform error whether the org
exists or not; a tenant probing channel names learns nothing.
"""

import asyncio
import contextlib
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from sqlalchemy import select

from incident_desk.db import models
from incident_desk.services import realtime

HEARTBEAT_TIMEOUT_SECONDS = 60

router = APIRouter()


async def _channel_allowed(websocket: WebSocket, channel: str, user_id: uuid.UUID) -> bool:
    """Membership check for a channel name; uniform failure, no existence leaks."""
    sessionmaker = websocket.app.state.sessionmaker
    async with sessionmaker() as session:
        if channel.startswith("org:") and channel.endswith(":incidents"):
            slug = channel[len("org:") : -len(":incidents")]
            row = await session.execute(
                select(models.Membership)
                .join(models.Organization, models.Organization.id == models.Membership.org_id)
                .where(
                    models.Organization.slug == slug,
                    models.Membership.user_id == user_id,
                )
            )
            return row.first() is not None
        if channel.startswith("incident:"):
            try:
                incident_id = uuid.UUID(channel.removeprefix("incident:"))
            except ValueError:
                return False
            row = await session.execute(
                select(models.Membership)
                .join(models.Incident, models.Incident.org_id == models.Membership.org_id)
                .where(
                    models.Incident.id == incident_id,
                    models.Membership.user_id == user_id,
                )
            )
            return row.first() is not None
    return False


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    redis: Redis = websocket.app.state.redis
    broker: realtime.RealtimeBroker = websocket.app.state.broker

    user_id = await realtime.consume_ticket(redis, websocket.query_params.get("ticket", ""))
    if user_id is None:
        await websocket.close(code=4401)
        return

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    subscribed: set[str] = set()

    async def deliver() -> None:
        while True:
            await websocket.send_json(await queue.get())

    deliver_task = asyncio.create_task(deliver())
    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_json(), timeout=HEARTBEAT_TIMEOUT_SECONDS
                )
            except TimeoutError:
                await websocket.close(code=4408)
                return

            action = message.get("action")
            channel = str(message.get("channel", ""))
            if action == "ping":
                for sub in subscribed:
                    if sub.startswith("incident:"):
                        await realtime.presence_touch(
                            redis, sub.removeprefix("incident:"), str(user_id)
                        )
                await websocket.send_json({"type": "pong"})
            elif action == "subscribe":
                if channel in subscribed:
                    await websocket.send_json({"type": "subscribed", "channel": channel})
                    continue
                if not await _channel_allowed(websocket, channel, user_id):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "forbidden_channel",
                            "channel": channel,
                        }
                    )
                    continue
                await broker.add_subscriber(channel, queue)
                subscribed.add(channel)
                await websocket.send_json({"type": "subscribed", "channel": channel})
                if channel.startswith("incident:"):
                    incident_id = channel.removeprefix("incident:")
                    await realtime.presence_touch(redis, incident_id, str(user_id))
                    await broker.publish(
                        channel,
                        {
                            "type": "presence.changed",
                            "incident_id": incident_id,
                            "viewers": await realtime.presence_viewers(redis, incident_id),
                        },
                    )
            elif action == "unsubscribe":
                if channel in subscribed:
                    subscribed.discard(channel)
                    await broker.remove_subscriber(channel, queue)
                    if channel.startswith("incident:"):
                        incident_id = channel.removeprefix("incident:")
                        await realtime.presence_leave(redis, incident_id, str(user_id))
                        await broker.publish(
                            channel,
                            {
                                "type": "presence.changed",
                                "incident_id": incident_id,
                                "viewers": await realtime.presence_viewers(redis, incident_id),
                            },
                        )
                await websocket.send_json({"type": "unsubscribed", "channel": channel})
            else:
                await websocket.send_json({"type": "error", "code": "unknown_action"})
    except WebSocketDisconnect:
        pass
    finally:
        # A dropped client cancels this task; the first IO await inside a
        # plain finally would die with CancelledError and abort cleanup.
        # Run cleanup in its own shielded task so departures always broadcast.
        cleanup = asyncio.create_task(
            _cleanup(broker, redis, deliver_task, subscribed, queue, str(user_id))
        )
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.shield(cleanup)


async def _cleanup(
    broker: realtime.RealtimeBroker,
    redis: Redis,
    deliver_task: "asyncio.Task[None]",
    subscribed: set[str],
    queue: "asyncio.Queue[dict[str, Any]]",
    user_id: str,
) -> None:
    deliver_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await deliver_task
    for channel in subscribed:
        await broker.remove_subscriber(channel, queue)
        if channel.startswith("incident:"):
            incident_id = channel.removeprefix("incident:")
            await realtime.presence_leave(redis, incident_id, user_id)
            await broker.publish(
                channel,
                {
                    "type": "presence.changed",
                    "incident_id": incident_id,
                    "viewers": await realtime.presence_viewers(redis, incident_id),
                },
            )
