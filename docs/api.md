# API guide

The full, authoritative reference is the OpenAPI schema: interactive docs at
`/docs` on a running server, and the committed [openapi.json](../backend/openapi.json)
(kept in sync by a CI drift check). This guide covers the conventions a client
author needs.

## Base URL and versioning

All endpoints live under `/api/v1`. Breaking changes would ship under a new
version prefix.

## Authentication

Two kinds of principal:

- **Users** authenticate with a bearer access JWT:
  `Authorization: Bearer <access_token>`. Get one from `POST /auth/login`.
- **API keys** authenticate with `Authorization: Bearer ik_<prefix>_<secret>`.
  Keys act as their organisation within their granted scopes and can never
  author content (incidents, comments, uploads need a user).

### Login and token rotation

```
POST /api/v1/auth/login       { email, password }
  -> { data: { access_token, refresh_token, expires_in } }
     or { data: { mfa_required: true, mfa_token } } for MFA accounts

POST /api/v1/auth/mfa/challenge { mfa_token, code }   # TOTP or recovery code
  -> { data: { access_token, refresh_token, expires_in } }

POST /api/v1/auth/refresh     { refresh_token }
  -> { data: { access_token, refresh_token, expires_in } }
```

Access tokens last 15 minutes. When one expires, exchange the refresh token for
a new pair. Refresh tokens are single use and rotate; store the new one each
time. Reusing a consumed refresh token revokes the whole session family (see
[ADR-0002](adr/0002-refresh-token-families.md)).

## Response envelopes

Single resources: `{ "data": <object> }`. Lists: `{ "data": [...],
"next_cursor": "<token>|null" }`. Pass `next_cursor` back as `?cursor=` for the
next page; `null` means the last page.

## Errors

Every error, from any layer, uses one shape:

```json
{ "error": { "code": "version_conflict", "message": "...",
             "details": { }, "request_id": "..." } }
```

`code` is stable and machine-readable; `message` is for humans and may change.
`request_id` matches the `X-Request-ID` response header and the server logs.

Common codes: `unauthorized` (401), `forbidden` (403), `not_found` (404, also
returned for cross-tenant access), `conflict`/`version_conflict`/`last_owner`/
`slug_taken` (409), `validation_error` (422), `precondition_required` (428),
`rate_limited` (429).

## Optimistic concurrency

`GET /orgs/{slug}/incidents/{id}` returns an `ETag: "<version>"` header.
`PATCH` requires `If-Match: "<version>"`; a stale version answers 409 with the
server's current state in `error.details` so the client can show what changed.
Missing `If-Match` is 428.

## Idempotency

`POST /orgs/{slug}/incidents` accepts an `Idempotency-Key` header. A retried
request with the same key returns the original response byte-for-byte (with
`Idempotency-Replayed: true`) and creates nothing, so a network retry never
double-creates.

## Rate limits

Every response carries `X-RateLimit-Limit`, `-Remaining`, and `-Reset`. A 429
adds `Retry-After`. Limits are keyed per user on JWT routes, per key on API-key
routes, and per IP on the unauthenticated auth endpoints; login has a stricter
bucket.

## Real-time

`POST /api/v1/ws-ticket` (authenticated) returns a single-use ticket. Connect a
WebSocket to `/ws?ticket=...` within 30 seconds. Subscribe with
`{"action":"subscribe","channel":"org:<slug>:incidents"}` or
`"incident:<uuid>"`. Ping every 20s; on reconnect, refetch to reconcile. See
[ADR-0006](adr/0006-redis-websocket-fanout.md).

## Filtering and search

`GET /orgs/{slug}/incidents` accepts `status`, `severity` (repeatable),
`service_id`, `assigned_to`, `tag`, `q` (full-text over title and description),
`sort` (`created_at`|`started_at`), `limit`, and `cursor`.
