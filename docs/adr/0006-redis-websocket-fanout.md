# ADR-0006: Redis pub/sub WebSocket fan-out and ticket-based auth

## Status
Accepted.

## Context
Real-time collaboration needs to push incident and comment events to connected
clients. The API runs as multiple replicas behind a load balancer, so a client
may be connected to a different replica than the one handling a write. Browsers
also cannot set headers on a WebSocket handshake, so the access token cannot be
sent the usual way.

## Decision
- **Fan-out through Redis pub/sub.** Every replica runs one broker that
  subscribes to Redis channels; publishing an event always goes through Redis.
  A write on replica A reaches a socket held by replica B because both talk to
  the same Redis.
- **Ticket-based auth.** The client POSTs to an authenticated `/ws-ticket`
  endpoint for a single-use, 30-second ticket stored in Redis, then connects
  with `?ticket=...`. The server consumes the ticket atomically with `GETDEL`.

## Consequences
- **Horizontal scale works.** Proven by `tests/test_realtime_cross_instance.py`:
  two separate app instances share only Redis and Postgres, and an event
  published through instance A reaches a WebSocket client on instance B.
- **Long-lived JWTs never enter a URL** (and therefore never a proxy or access
  log). Replaying a consumed ticket is rejected. The log-scrubbing middleware
  still redacts the ticket parameter as defence in depth.
- **The socket is a change notifier, not reliable delivery.** The client
  heartbeats, reconnects with exponential backoff, and on reconnect refetches
  through the REST API to reconcile anything missed while disconnected.
- **Presence** is a Redis ZSET per incident scored by last-seen time, so a
  crashed client ages out of the "who is viewing" set without any cleanup code
  running.

## Alternatives considered
- **In-process subscriptions**: simpler, but only works with a single replica.
  Rejected because the system is designed to scale out.
- **Token in the query string**: rejected; it puts the long-lived credential in
  URLs and logs. The single-use ticket avoids that.
