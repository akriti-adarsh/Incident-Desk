Build `incident-desk`, a production-quality incident management application: a real multi-tenant SaaS-shaped product with authentication, role-based authorisation, real-time collaboration, an audit trail, background jobs, and a test suite that would survive a code review at a serious company. The domain is deliberately modest so that every engineering concern gets done properly rather than half of them getting done at all.

**Precedence rule:** the "Review round" sections at the end of this file amend the sections above them; where they conflict, the review sections govern.

### 0. Absolute constraints

1. **`docker compose up` gives a working app with seeded demo data and printed login credentials.** A reviewer must be able to click around within two minutes of cloning.
2. **Security is not decorative.** Every authorisation check is enforced server-side and tested. There must be tests proving a user from tenant A cannot read, modify, or even discover the existence of tenant B's data.
3. No stubs, no TODOs, no "coming soon" UI. Every button in the interface works.
4. Backend: `mypy --strict` clean, ruff clean, ≥85% coverage. Frontend: TypeScript strict mode, no `any`, ESLint clean, ≥70% coverage on logic (hooks, stores, utils).
5. Pin all dependencies, commit lockfiles, no `:latest` tags.
6. Commit per section 12.

### 1. Stack

**Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.0 (async, with `asyncpg`), Alembic migrations, Pydantic v2, Postgres 16, Redis (caching, rate limits, pub/sub for WebSocket fan-out), ARQ or Celery for background jobs (prefer **ARQ** — async-native, less ceremony), `argon2-cffi` for password hashing, `PyJWT` for JWTs (maintained, unlike python-jose).

**Frontend:** React 19 + TypeScript + Vite, TanStack Query for server state, TanStack Router or React Router (pick one and be consistent), Zustand for the little client state that isn't server state, Tailwind CSS, `react-hook-form` + `zod` for forms, `vitest` + React Testing Library, Playwright for E2E.

**Both:** Docker multi-stage, GitHub Actions, `pre-commit`.

### 2. Domain model

Multi-tenant incident tracking for engineering teams. Tables (Alembic-migrated, every FK indexed, `created_at`/`updated_at` on everything):

- `organizations` — id, name, slug (unique), plan, settings JSONB, created_at
- `users` — id, email (unique), password_hash, full_name, avatar_url, is_active, last_login_at, mfa_secret (nullable), created_at
- `memberships` — user_id, org_id, role (`owner` | `admin` | `responder` | `viewer`), joined_at. Composite PK. **A user can belong to multiple orgs with different roles** — this is what makes the authorisation model non-trivial and worth testing.
- `services` — id, org_id, name, description, owner_team, tier (`tier1`..`tier3`)
- `incidents` — id, org_id, service_id, sequence_number (per-org, gapless), title, description, severity (`sev1`..`sev4`), status (`open` | `acknowledged` | `mitigated` | `resolved` | `postmortem`), reported_by, assigned_to (nullable), started_at, acknowledged_at, resolved_at, resolution_summary, tags (text[])
- `incident_events` — id, incident_id, actor_id (nullable for system events), event_type, payload JSONB, created_at. **Append-only timeline** — the source of truth for what happened.
- `comments` — id, incident_id, author_id, body (markdown), edited_at, deleted_at (soft delete)
- `attachments` — id, incident_id, uploader_id, filename, content_type, size_bytes, storage_key, checksum
- `on_call_schedules` — id, org_id, service_id, rotation config JSONB
- `on_call_shifts` — id, schedule_id, user_id, starts_at, ends_at (with an exclusion constraint preventing overlapping shifts for the same schedule — use Postgres `EXCLUDE USING gist` with a tstzrange; **this is a real database-level constraint and a test must prove an overlapping insert fails**)
- `audit_log` — id, org_id, actor_id, action, resource_type, resource_id, before JSONB, after JSONB, ip_address, user_agent, created_at
- `api_keys` — id, org_id, name, key_hash, prefix, scopes text[], last_used_at, expires_at, revoked_at

**Gapless per-org sequence numbers:** `INC-1`, `INC-2` per organisation. Implement with a `SELECT ... FOR UPDATE` on a per-org counter row, and write a **concurrency test** that fires 50 simultaneous incident creations and asserts sequence numbers 1–50 with no duplicates and no gaps. This one test says more about her engineering than any feature.

### 3. Authentication and authorisation

- Registration with email verification (token emailed — use MailHog in compose so it's genuinely testable and visible), password strength validation, argon2id hashing with tuned parameters
- Login returning a short-lived access JWT (15 min) and a **rotating refresh token** stored hashed in the database with a family/lineage id. On refresh, the old token is invalidated; **reuse of a consumed refresh token invalidates the entire family and forces re-login** (detection of token theft). Test this whole flow — it's the part most implementations get wrong.
- TOTP MFA: enrolment with a QR code, verification, recovery codes (hashed, single-use), and enforcement at login. Test enrolment, valid code, replayed code rejection, clock-skew window, and recovery-code consumption.
- Password reset with single-use, time-limited, hashed tokens. Reset invalidates all sessions.
- API keys: `Bearer ik_<prefix>_<secret>`, only the hash stored, scoped permissions, shown once at creation.
- **Authorisation model:** a single `Permission` enum and a matrix mapping role → permitted actions, resolved per-organisation from the request context. Implement it as a FastAPI dependency that returns an authorisation context; **no route may query the database for a resource without the org scope applied at the query level, not filtered afterwards.** Add a test that asserts every route requiring auth is registered with the dependency (introspect the app's routes — a route that forgets the dependency should fail the test suite, not production).
- Tenant isolation tests: for every resource type, a user in org A requesting an org B resource by direct id must get **404, not 403** (don't leak existence), and this must be tested for every endpoint. Write it as a parametrised test over the route table so new endpoints are automatically covered.

### 4. API

RESTful, versioned under `/api/v1`, cursor-paginated (not offset — explain why in the docs), with consistent envelopes and a single error format `{error: {code, message, details?, request_id}}`.

Resources: `auth/*`, `organizations`, `memberships` (invite, change role, remove — with a rule that the last owner cannot be demoted or removed, tested), `services`, `incidents` (with filtering by status/severity/service/assignee/tag, full-text search on title+description using a Postgres `tsvector` GIN index, and sorting), `incidents/{id}/events`, `incidents/{id}/comments`, `incidents/{id}/attachments`, `on-call/schedules`, `on-call/who-is-on-call?service_id=`, `audit-log` (admin only), `api-keys`, `metrics/summary` (MTTA/MTTR, incidents by severity over time, computed in SQL with window functions — not in Python).

Also:
- **Optimistic concurrency** on incident updates via an `If-Match` ETag / `version` column, returning 409 on conflict. The UI must handle the conflict gracefully by showing what changed. Tested.
- **Idempotency keys** on incident creation (`Idempotency-Key` header, stored with the response for 24h) so a retried request doesn't double-create. Tested.
- Rate limiting per user and per API key via Redis sliding window, with `X-RateLimit-*` headers and 429 + `Retry-After`.
- Structured request logging with a request id propagated to the frontend and shown in error toasts.
- OpenAPI docs with real examples and descriptions on every field; a committed generated `openapi.json`.
- `/health`, `/health/ready`, `/metrics` (Prometheus).

### 5. Real-time

WebSocket at `/ws?token=...`:
- Authenticated on connect (token validated, org membership resolved); unauthenticated or cross-org subscription attempts are rejected — tested
- Client subscribes to channels: `org:{id}:incidents`, `incident:{id}`
- Server publishes: incident created/updated/status-changed, comment added, assignment changed, presence (who's viewing this incident now)
- **Fan-out via Redis pub/sub** so multiple API replicas work — and prove it: an integration test with two app instances asserting a message published through instance A reaches a client connected to instance B
- Heartbeat ping/pong with a documented timeout, exponential-backoff reconnect on the client, and **on reconnect the client refetches to reconcile missed events** (don't pretend WebSockets are reliable delivery — this reconciliation step is the mark of someone who has actually shipped real-time features)
- Presence tracked in Redis with TTL so a crashed client's presence expires

### 6. Background jobs

ARQ workers for: sending emails (verification, invitation, incident notification), escalation (if a `sev1` isn't acknowledged in N minutes, notify the next person in the on-call rotation — with the escalation chain configurable and the whole thing tested with a controllable clock), a nightly job computing per-org metrics into a summary table, attachment virus-scan placeholder that is honestly labelled as a hook rather than a scanner, and audit-log retention pruning. Jobs must be idempotent and have retry policies with dead-lettering. A test must prove a job that fails 3 times lands in the dead-letter set.

### 7. Frontend

**Design direction — read this properly, do not produce a generic dashboard.**

Before writing any component, write a short design plan in `docs/design.md`: a 5-colour named palette with hex values, two typefaces (a characterful display face used with restraint plus a workhorse body face — not the default system stack, and not the same pairing you'd reach for on any project), a type scale, and one signature element the product is remembered by. Then check that plan against the brief and revise anything that reads as a default.

Specifically avoid the current AI-design clichés: cream-and-terracotta with a high-contrast serif, near-black with a single acid-green accent, and the hairline-ruled broadsheet layout. Those are defaults, not decisions.

Ground the aesthetic in the subject: this is a tool people open at 3am under stress. That has real design implications — severity must be readable at a glance and never encoded by colour alone, the timeline is the centre of the product not a side panel, density beats whitespace here, and destructive actions need friction. Let the incident timeline be the signature element and keep everything around it disciplined.

**Copy rules:** active voice, sentence case, name things by what the user controls. "Acknowledge" not "Submit". The button that says "Resolve incident" produces a toast that says "Incident resolved". Empty states say what to do next. Errors say what happened and what to do, and never apologise.

**Screens:**
- Auth: login, register, verify email, forgot/reset password, MFA challenge, MFA enrolment
- Org switcher (a user with multiple memberships must be able to switch, and the whole UI reflects the active org's role)
- Incident list: virtualised table, saved filter views persisted per user, keyboard navigation (`j`/`k` to move, `Enter` to open, `/` to focus search — real keyboard support, tested)
- Incident detail: header with severity/status/assignee, the timeline as the spine of the page, markdown comments with optimistic updates and rollback on failure, attachment upload with progress and drag-and-drop, live presence indicators, status transitions as a state machine that only offers legal transitions
- Create/edit incident with `zod`-validated forms and inline field errors
- On-call schedule view with a week/month calendar and a "who's on call now" strip
- Metrics dashboard: MTTA/MTTR trend, incidents by severity, top affected services (Recharts)
- Settings: members and roles, services, API keys, audit log viewer with filters
- 404, 403, and an error boundary that shows the request id

**Quality floor, not negotiable:** responsive to mobile, visible keyboard focus rings, `prefers-reduced-motion` respected, semantic HTML, ARIA where needed, all interactive elements reachable by keyboard, colour contrast meeting WCAG AA, form labels properly associated. Run axe in the E2E suite and fail on violations.

**Client architecture:** TanStack Query for all server state with sensible `staleTime` per resource and query-key factories; optimistic mutations with rollback on comments and status changes; WebSocket events invalidating the right query keys precisely (not a blanket `invalidateQueries()`); a typed API client generated from or checked against the OpenAPI schema so a backend field rename breaks the frontend build; skeleton loading states, not spinners; error boundaries per route.

### 8. Testing

**Backend:** unit tests for the permission matrix (every role × every action, exhaustively parametrised), the state machine (every legal and illegal transition), and the sequence generator. Integration tests against a real Postgres via `testcontainers` or a compose-managed test database, with transactional rollback per test. The named high-value tests: tenant isolation across all routes, refresh-token reuse detection, concurrent sequence generation, the on-call overlap exclusion constraint, optimistic-concurrency 409, idempotency-key replay, cross-instance WebSocket fan-out, job dead-lettering.

**Frontend:** vitest for hooks, stores, the API client, form schemas, and the permission-derived UI gating. MSW for API mocking.

**E2E (Playwright):** register → verify → create org → invite a second user → second user accepts → create incident → acknowledge → comment → assign → resolve → verify audit log. Plus: MFA enrolment and login, real-time update visible in a second browser context, permission gating (a `viewer` cannot see the resolve button and the API rejects it if they call it directly), and the axe accessibility scan. Run against the compose stack in CI.

**Load test:** a `k6` or `locust` script hitting the incident list and create endpoints, with results in `docs/performance.md`: p50/p95/p99 at 10/50/200 concurrent users, plus the `EXPLAIN ANALYZE` output for the incident-list query before and after adding the composite index, showing the actual improvement. Real numbers.

### 9. Ops

`docs/runbook.md` — how to run migrations safely, roll back a bad deploy, handle a stuck job queue, rotate secrets, and restore from backup. `scripts/backup.sh` and `restore.sh` that actually work against the compose Postgres. Structured logs, graceful shutdown (drain in-flight requests and WebSockets on SIGTERM — implemented and tested), and a documented zero-downtime migration policy (additive-only, two-phase column changes) with one migration in the history demonstrating the pattern.

### 10. Seed data

`scripts/seed.py` — 3 organisations, 12 users with varied cross-org roles, 8 services, 60 incidents spread over 90 days with realistic status distributions and full event timelines, comments, on-call schedules with shifts covering the current week, and audit-log history. Deterministic under a seed. Prints a credentials table on completion. The demo must feel like a system that's been in use, not an empty shell.

### 11. CI

Jobs: backend lint/typecheck/test with coverage gate; frontend lint/typecheck/test with coverage gate; Playwright E2E against compose; build both images; a migration check (assert `alembic upgrade head` then `downgrade -1` then `upgrade head` works cleanly, and that autogenerate produces no diff against the models — catches model/migration drift, a classic production bug); and an OpenAPI drift check (regenerate and fail if it differs from the committed file).

### 12. Commit plan

1. `chore: monorepo scaffold, tooling, ci skeleton` 2. `feat(db): schema, migrations, and constraints` 3. `feat(db): on-call overlap exclusion constraint` 4. `feat(auth): registration, argon2 hashing, email verification` 5. `feat(auth): login with rotating refresh token families` 6. `test: refresh token reuse detection` 7. `feat(auth): totp mfa with recovery codes` 8. `feat(auth): password reset and session invalidation` 9. `feat(authz): permission matrix and org-scoped dependency` 10. `test: exhaustive permission matrix and tenant isolation` 11. `feat(api): organizations, memberships, services` 12. `feat(api): incidents with gapless per-org sequence` 13. `test: concurrent sequence generation` 14. `feat(api): timeline events and state machine transitions` 15. `feat(api): comments and attachments` 16. `feat(api): full-text search and cursor pagination` 17. `feat(api): optimistic concurrency and idempotency keys` 18. `feat(api): api keys with scopes` 19. `feat(api): audit log and metrics with window functions` 20. `feat(api): rate limiting and request tracing` 21. `feat(realtime): authenticated websockets with redis fan-out` 22. `test: cross-instance websocket delivery` 23. `feat(jobs): arq worker, email, escalation with clock control` 24. `feat(jobs): retries, dead lettering, retention pruning` 25. `docs: design plan with palette, type, and signature element` 26. `feat(web): design tokens, layout shell, auth screens` 27. `feat(web): incident list with virtualisation and keyboard nav` 28. `feat(web): incident detail with timeline and optimistic comments` 29. `feat(web): realtime subscriptions with precise invalidation` 30. `feat(web): on-call calendar and metrics dashboard` 31. `feat(web): settings, members, api keys, audit viewer` 32. `feat(web): accessibility pass and reduced-motion support` 33. `feat(seed): deterministic demo data` 34. `test(e2e): full lifecycle, mfa, realtime, permissions, axe` 35. `perf: load test and index optimisation with query plans` 36. `ops: graceful shutdown, backup/restore, runbook` 37. `ci: migration drift and openapi drift checks` 38. `docs: architecture, adrs, api guide` 39. `docs: readme with screenshots and measured performance`

### 13. Definition of done

- [ ] `docker compose up` → seeded app reachable, credentials printed, everything clickable works
- [ ] Every named high-value test in section 8 exists and passes
- [ ] Tenant isolation is verified across every route by a parametrised test
- [ ] The route-registration test catches a missing auth dependency
- [ ] Concurrent sequence test: 50 parallel creates, no gaps, no duplicates
- [ ] Overlapping on-call shift insert fails at the database level, proven by test
- [ ] Refresh-token reuse invalidates the family, proven by test
- [ ] Playwright suite green including the axe scan with zero violations
- [ ] `docs/performance.md` has real load-test numbers and real query plans before/after indexing
- [ ] Migration up/down/up and autogenerate-no-diff checks pass in CI
- [ ] Backend coverage ≥85%, frontend ≥70%, `mypy --strict` clean, TS strict with no `any`
- [ ] `docs/design.md` records the design plan and what was revised away from a default
- [ ] README has real screenshots of at least 4 screens
- [ ] Graceful shutdown drains connections, tested
- [ ] CI green

### 14. Session plan

**This file is fully self-contained — no companion document is required.** Hand this single file to Claude Code and run the build as the sessions below, under this protocol:

**Session 1, before any code:** save this prompt as `docs/BUILD_SPEC.md`, create `DEVIATIONS.md` (header only), and create `CLAUDE.md` exactly as follows — commit all three as part of commit 1, and keep CLAUDE.md's State section current at every commit thereafter.

```markdown
# CLAUDE.md — standing rules and state
The spec is docs/BUILD_SPEC.md. This file is rules and state; the spec defines the work.

## Rules — non-negotiable
1. No TODO, FIXME, NotImplementedError, or stub bodies anywhere in src/. Ever.
2. Dependency versions come from the resolver (`uv add` / `npm install`); commit the lockfile.
   Never hand-type a version number the resolver has not produced.
3. Nothing is "done" until its command has run in THIS session with the real output shown —
   the actual pytest summary line, the actual exit status. "Should pass" is not a status.
4. Every number in a README or doc must exist in a committed artifact (eval_results/,
   benchmarks/results/, a CI log). An estimated or remembered number is a defect.
5. When a library, API, or dataset differs from the spec — renamed function, changed endpoint,
   auth now required — adapt to reality and add one line to DEVIATIONS.md
   (spec said / reality is / what was done). Never mock a real path to fake compliance.
6. Never weaken, skip, or delete a test to make it pass. Fix the code or flag the conflict.
7. One commit per plan milestone; the full test suite runs green before every commit.
8. If the next milestone will not fit in the session's remaining capacity, stop at the last
   green commit and update State. Do not start work you cannot finish.

## State (update at every commit)
- Plan position: <n> of <total>. Last completed: "<commit message>"
- Suite at last commit: <pytest summary line> · Coverage: <n>%
- Open deviations: <count> · Next up: commits <n+1>–<m>
- Notes for next session: <blockers, decisions pending>
```

**Every session after the first opens with this message** (the human pastes it, filling the brackets):

> Read CLAUDE.md, DEVIATIONS.md, docs/BUILD_SPEC.md (skim), and `git log --oneline -15`. We are at commit [n] of the plan. First action: run `make test` and paste the summary line. If it is not green, fixing that is the entire session — no new work on a red suite. If green, proceed with commits [n+1]–[m] only, under the CLAUDE.md rules. Stop at the last green commit before context runs low and update State.

**Between sessions (human, ~15 minutes):** run `make test`; run `grep -rnE "TODO|FIXME|NotImplementedError" src/`; compare `git log --oneline` against the commit plan; open the newest test file and check it asserts something real rather than that a mock returned what it was told; pick one number from the README and trace it to its committed artifact. Any failure means the next session opens with "fix these findings" instead of new work.

**If the build starts thrashing** — rewriting working code, a test flip-flopping between attempts, quiet "simplifications" of the spec — stop, `git reset --hard <last-green-commit>`, and open a fresh session scoped to one milestone with the exact error text pasted in.

**The session slices for this project:**

Five sessions — this is the biggest build in the set, and the backend must be provably solid before a single component is written against it.

| Session | Commits | Boundary check before closing |
|---|---|---|
| A | 1–10 (schema → auth → MFA → authz → isolation tests) | The three security suites green: exhaustive permission matrix, tenant isolation across all existing routes, refresh-token-reuse family invalidation. Read the isolation test yourself — confirm it asserts **404**, not 403. |
| B | 11–20 (all API resources → concurrency → idempotency → keys → audit → rate limits) | The 50-way concurrent sequence test green; the route-registration test proves it catches a route missing the auth dependency (temporarily add one, watch it fail, remove it). |
| C | 21–24 (WebSockets → Redis fan-out → jobs → escalation) | Cross-instance fan-out test green with two app containers; the escalation test runs on the controllable clock, not real sleeps. |
| D | 25–33 (design plan → frontend, all screens → a11y pass → seed) | `docs/design.md` written **before** components; the app fully clickable by hand against seeded data; keyboard nav works; org switching visibly changes role-gated UI. |
| E | 34–39 (E2E → load test → ops → CI drift checks → docs) + acceptance | Playwright suite green including the axe scan; load-test numbers and before/after query plans in `docs/performance.md` from real runs; migration up/down/up + autogenerate-no-diff green in CI. |

### 15. Failure recovery — project-specific

- **Mail catcher — use Mailpit, not MailHog:** MailHog is unmaintained; Mailpit is the maintained drop-in (same SMTP-sink-plus-web-UI role). Treat Mailpit as the corrected default for the compose service, and point the email-verification E2E step at its API for asserting delivery.
- **The on-call exclusion constraint needs `btree_gist`:** `EXCLUDE USING gist (schedule_id WITH =, tstzrange(starts_at, ends_at) WITH &&)` requires `CREATE EXTENSION btree_gist` for the scalar-equality part — plain GiST can't index the `=` on `schedule_id`. Put the extension creation in the same Alembic migration as the constraint, or the migration fails on a fresh database and the fresh-clone test dies at step one.
- **React 19 peer-dependency gaps:** if any pinned library refuses React 19 at resolve time, pin React 18.3 across the app and record it in DEVIATIONS.md — nothing in this build uses 19-only features, and a clean 18.3 tree beats `--legacy-peer-deps` noise in the lockfile.
- **Playwright in CI:** the job needs `npx playwright install --with-deps chromium` before the suite, and the app stack must be healthy first — gate on the compose health checks, not a sleep. Run E2E against the *built* images, not the dev servers, so the suite also validates the Dockerfiles.
- **Async SQLAlchemy + test isolation:** run integration tests inside a transaction-per-test with rollback (nested SAVEPOINT pattern), sharing one event loop per session via the pytest-asyncio config. Getting this wrong produces intermittent "another operation is in progress" asyncpg errors that look like app bugs — it's test plumbing; fix it once in `conftest.py` early in session A.
- **Argon2 parameters:** use `argon2-cffi`'s current recommended profile and record the target hash time (~50–100 ms on the dev machine) in a comment; don't hand-tune memory/iterations from memory of old advice.
- **WebSocket auth in the browser:** browsers can't set headers on WS connects — the `?token=` query-param design is deliberate; keep tokens out of access logs by scrubbing the query string in the logging middleware, and note this in the security section of the docs.

### 16. Review round 2 — added depth and corrections

- **JWT library correction:** use **PyJWT**, not `python-jose` — jose is effectively unmaintained with open advisories, and this repo's whole security story shouldn't rest on it. Validate `exp`, `iss`, and `aud` on every decode. (The stack list above has been corrected to match.)
- **Cursor mechanics:** the cursor is an opaque base64 encoding of `(sort_value, id)`; every ORDER BY includes `id` as the unique tiebreaker, or pagination silently skips and duplicates rows whenever sort values collide. Test it with duplicate timestamps — that's exactly where it breaks.
- **Rate-limit keying:** per-user on JWT routes, per-API-key on key routes, per-IP only on the unauthenticated auth endpoints; the login route additionally gets a stricter bucket and a constant-time credential comparison so failed attempts don't leak timing.

### 17. Review round 3 — final audit findings

- **WebSocket auth upgrade — supersedes the `?token=` design in section 5 and the related recovery note:** add `POST /v1/ws-ticket` (authenticated) returning a single-use, 30-second ticket stored in Redis; the client connects with `?ticket=` and the server consumes it atomically (`GETDEL`). Long-lived JWTs never enter a URL; the log-scrubbing rule still applies to the ticket parameter. Test that replaying a consumed ticket is rejected.
- **Idempotency storage, pinned down:** a Postgres table `idempotency_keys(org_id, key, status_code, response_body, created_at)` with a unique constraint on `(org_id, key)`, written in the same transaction as the created incident, pruned by the retention job after 24 h. Same-key replay returns the stored response byte-for-byte.
- **Alembic × async:** autogenerate and migrations run on a sync driver URL (`postgresql+psycopg`) in `env.py` while the app runs on `asyncpg` — configure both URLs explicitly or the CI migration checks fail in ways that look like schema bugs.

---

## After the build

**Description:** `Multi-tenant incident management platform: cross-org RBAC, rotating refresh tokens with theft detection, real-time collaboration over Redis-backed WebSockets, optimistic concurrency, and a full E2E and load-test suite.`

**Topics:** `fastapi` `react` `typescript` `postgresql` `websockets` `multi-tenant` `rbac` `full-stack`

**LinkedIn entry:**

> Built a multi-tenant incident management platform end to end. Backend: FastAPI with async SQLAlchemy, a permission matrix enforced by an org-scoped dependency (with a test that introspects the route table and fails if any endpoint forgets it), rotating refresh-token families that invalidate on reuse to detect token theft, TOTP MFA with single-use recovery codes, gapless per-organisation incident numbering verified by a 50-way concurrency test, optimistic concurrency via ETags, idempotency keys on creation, and a database-level exclusion constraint preventing overlapping on-call shifts. Real-time collaboration over authenticated WebSockets with Redis pub/sub fan-out, verified across two app instances, and client-side reconciliation on reconnect. Frontend: React 19 + TypeScript with TanStack Query, virtualised lists, keyboard navigation, optimistic mutations with rollback, and a WCAG AA accessibility pass enforced by axe in the Playwright suite. Backend coverage 87%, p95 latency XXms at 200 concurrent users after index optimisation (down from XXXms).

**Be ready for:** Why 404 rather than 403 for cross-tenant access? Walk me through refresh-token rotation and what attack it stops. Why cursor pagination? How do you keep WebSocket state consistent when a client reconnects? What breaks if you filter by org in Python instead of in the query? Why an exclusion constraint instead of application-level overlap checking? Walk me through the index you added and the plan change it caused.
