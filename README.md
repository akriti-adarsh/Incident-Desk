# incident-desk

[![ci](https://github.com/akriti-adarsh/Incident-Desk/actions/workflows/ci.yml/badge.svg)](https://github.com/akriti-adarsh/Incident-Desk/actions/workflows/ci.yml)

A multi-tenant incident management platform for engineering teams, built end to end as a production-shaped SaaS product: organisations, role-based access control resolved per organisation, a hardened authentication stack (rotating refresh-token families with theft detection, TOTP MFA, single-use recovery codes), an append-only incident timeline, and a test suite that treats security guarantees as things to prove, not things to assume.

The domain is deliberately modest. The point of this repository is that every engineering concern around the domain (tenancy, authorisation, migrations, concurrency, auditability, operability, testing) is done properly rather than half of them getting done at all.

---

## Table of contents

- [Project status](#project-status)
- [What is implemented today](#what-is-implemented-today)
- [Architecture](#architecture)
- [Domain model](#domain-model)
- [Security model](#security-model)
- [API](#api)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Testing](#testing)
- [Engineering practices](#engineering-practices)
- [Roadmap](#roadmap)
- [Repository guide](#repository-guide)

---

## Project status

The project is built in five planned phases against a written specification ([docs/BUILD_SPEC.md](docs/BUILD_SPEC.md)), with one commit per milestone and the full test suite green before every commit.

| Phase | Scope | Status |
|---|---|---|
| A | Schema, migrations, database constraints, full authentication, MFA, authorisation model, tenant-isolation test suites | **Complete** |
| B | All API resources: incidents with gapless per-org numbering, timeline events, comments, attachments, search, cursor pagination, optimistic concurrency, idempotency keys, API keys, audit log, metrics, rate limiting | Planned |
| C | Real-time: authenticated WebSockets with Redis pub/sub fan-out across instances, background jobs with retries and dead-lettering, escalation on a controllable clock | Planned |
| D | Frontend: design system, auth screens, virtualised incident list with keyboard navigation, incident detail with live timeline, on-call calendar, metrics dashboard, accessibility pass, deterministic seed data | Planned |
| E | Playwright E2E with axe accessibility scans, load testing with before/after query plans, ops (graceful shutdown, backup/restore, runbook), CI drift checks, final docs | Planned |

Current backend quality gates, from the latest [CI run](https://github.com/akriti-adarsh/Incident-Desk/actions/runs/30558446034) and reproducible locally with `make test`:

| Gate | Requirement | Current |
|---|---|---|
| Backend tests | all green | 146 passed |
| Backend coverage | at least 85%, enforced by pytest | 98.47% |
| Static typing | `mypy --strict`, zero errors | clean |
| Linting | ruff check and ruff format, zero findings | clean |
| Frontend | TypeScript strict, ESLint clean, vitest green | clean |

## What is implemented today

Everything below exists in code, is exercised by tests, and runs in CI against real Postgres, Redis, and an SMTP sink. Nothing in this section is aspirational.

- **Multi-tenant foundation.** Organisations with per-org membership roles. A user can belong to several organisations with a different role in each; every authorisation decision is resolved from the membership in the organisation named in the URL, never from a global role.
- **Registration and email verification.** Argon2id password hashing, password strength validation, single-use hashed verification tokens delivered over real SMTP (Mailpit in development, so every email is visible in a web UI and assertable by tests).
- **Login sessions.** Short-lived access JWTs (15 minutes) plus rotating refresh-token families. Reusing an already-consumed refresh token is treated as evidence of theft: the entire family is revoked, cutting off both the attacker's copy and the victim's, and forcing a fresh login.
- **TOTP MFA.** Two-phase enrolment (the secret is not enforced until the user proves their authenticator works), a clock-skew window of one 30-second step in each direction, replay rejection by persisted timestep counter, and ten single-use hashed recovery codes shown exactly once.
- **Password reset.** Single-use, 30-minute, hashed tokens. A completed reset revokes every refresh-token family and bumps the user's token version so every outstanding access JWT stops validating on its next use.
- **Authorisation.** A single `Permission` enum, an explicit role matrix, and one FastAPI dependency (`require`) that resolves the organisation and the caller's membership in a single query and enforces permissions server-side on every request.
- **Tenant isolation.** A request for another tenant's organisation answers 404, never 403, whether or not the organisation exists, so tenants cannot probe for each other. This is enforced by a test that is parametrised over the live route table: any newly added org-scoped route is covered automatically.
- **Schema discipline.** Seventeen Alembic-migrated tables, every foreign key indexed, timestamps everywhere, and a database-level exclusion constraint (`EXCLUDE USING gist`) that makes overlapping on-call shifts impossible to insert no matter which code path tries.
- **Operational surface.** Liveness and readiness probes, a single error envelope with request ids on every response, and a multi-stage Docker build that runs as a non-root user.

## Architecture

### System shape

```mermaid
flowchart LR
    client["Client / API consumer"] --> api["FastAPI app\n(async SQLAlchemy, Pydantic v2)"]
    api --> pg[("PostgreSQL 16\nsource of truth")]
    api --> redis[("Redis 7\ncache, rate limits,\npub/sub fan-out")]
    api --> smtp["Mailpit\nSMTP sink + web UI"]
    web["React 19 + TypeScript web app\n(phase D)"] -.-> api
    worker["ARQ workers\n(phase C)"] -.-> pg
    worker -.-> redis
```

Solid arrows exist today; dotted arrows are planned phases.

### Stack

| Layer | Choice | Why |
|---|---|---|
| API framework | FastAPI (Python 3.13) | async end to end, typed request/response models, OpenAPI for free |
| ORM and migrations | SQLAlchemy 2.0 (async, asyncpg) + Alembic | typed 2.0-style models; migrations and autogenerate run on a sync psycopg URL while the app runs on asyncpg, which keeps both drivers honest |
| Database | PostgreSQL 16 | exclusion constraints, JSONB, arrays, transactional DDL |
| Cache / messaging | Redis 7 | rate limiting and WebSocket fan-out in later phases |
| Password hashing | argon2-cffi (Argon2id) | current recommended profile: time_cost 3, 64 MiB memory, parallelism 4; measured at about 135 ms per hash on the dev machine (recorded in `security/passwords.py`) |
| Tokens | PyJWT | maintained JWT implementation; `exp`, `iss`, and `aud` validated on every decode |
| Email | aiosmtplib + Mailpit | real SMTP in development and CI, assertable through Mailpit's API |
| Frontend | React 19, TypeScript strict, Vite, vitest | scaffolded now, built out in phase D |
| Tooling | uv, ruff, mypy --strict, pre-commit, GitHub Actions | locked dependencies, zero-warning gates |

### Monorepo layout

```
incident-desk/
  backend/
    src/incident_desk/
      api/            HTTP layer: routers, auth dependencies, authz dependency
      db/             declarative models, engine plumbing, naming conventions
      schemas/        Pydantic request/response models
      security/       argon2, JWT, TOTP, opaque-token primitives
      services/       business logic: auth, sessions, MFA, orgs, email
      authz.py        Permission enum and the role matrix
      config.py       pydantic-settings configuration
      errors.py       error types and the single error envelope
      main.py         app factory, lifespan, health probes
    alembic/          migration environment and versioned migrations
    tests/            pytest suite (real Postgres, transactional isolation)
    Dockerfile        multi-stage, uv-locked, non-root runtime
  frontend/           React + TypeScript app (Vite, vitest, ESLint, strict tsc)
  docs/BUILD_SPEC.md  the full specification this build follows
  docker-compose.yml  Postgres, Redis, Mailpit, API
  Makefile            test / lint / type / up / down entry points
  .github/workflows/  CI pipeline
```

## Domain model

Seventeen tables, all Alembic-migrated, all with `created_at` and `updated_at`, every foreign key indexed (a schema test introspects the migrated database and fails if any of these conventions is violated).

### Core domain

| Table | Purpose | Notable constraints |
|---|---|---|
| `organizations` | Tenants | unique slug |
| `users` | Accounts (global, membership decides org access) | unique email, `token_version` for session invalidation, MFA state |
| `memberships` | User-to-org link with a role | composite primary key `(user_id, org_id)`; one user, many orgs, different roles |
| `services` | Things incidents happen to | unique `(org_id, name)`, tier `tier1..tier3` |
| `incidents` | The core record | unique `(org_id, sequence_number)` for gapless per-org numbering, severity `sev1..sev4`, status state machine, tags array |
| `incident_events` | Append-only timeline, the source of truth for what happened | system events allowed (nullable actor) |
| `comments` | Markdown discussion | soft delete via `deleted_at` |
| `attachments` | File metadata | unique storage key, checksum |
| `on_call_schedules` | Rotation configuration per service | JSONB rotation blob |
| `on_call_shifts` | Concrete shifts | `EXCLUDE USING gist (schedule_id WITH =, tstzrange(starts_at, ends_at) WITH &&)`: the database itself rejects overlapping shifts on a schedule; also a check that shifts end after they start |
| `audit_log` | Who did what, with before/after JSONB | indexed by `(org_id, created_at)` |
| `api_keys` | Programmatic access | only a hash stored, scoped permissions, revocable |
| `organization_counters` | Per-org counter row for gapless incident numbers | locked with `SELECT ... FOR UPDATE` at issue time (phase B) |

### Authentication support

| Table | Purpose | Lifecycle |
|---|---|---|
| `refresh_tokens` | One link in a rotating family (`family_id`) | consumed on rotation, revoked on logout, reset, or detected reuse |
| `email_verification_tokens` | Prove mailbox ownership | hashed, single use, 24-hour expiry |
| `password_reset_tokens` | Password recovery | hashed, single use, 30-minute expiry |
| `mfa_recovery_codes` | Authenticator-lost fallback | hashed, single use each |

## Security model

### Why this section is long

Multi-tenant security is the product here. Every guarantee below is enforced server-side and has at least one test whose only job is to prove it.

### Authentication flows

**Registration.** Email is normalised to lowercase, passwords must be at least 10 characters with some variety and not on a common-password denylist, and the hash is Argon2id with the library's current recommended parameters. A verification link (opaque 256-bit token, only its SHA-256 stored) is emailed; consuming it is single-use and idempotent failures are indistinguishable (invalid, expired, and replayed tokens all answer the same way).

**Login.** Unknown email and wrong password produce identical responses, and the unknown-email path still performs a full argon2 verification against a decoy hash so the two failures cost the same time. Unverified and deactivated accounts cannot log in.

**Sessions.** A successful login returns:

| Token | Lifetime | Shape | Purpose |
|---|---|---|---|
| Access token | 15 minutes | JWT (HS256, `iss`/`aud`/`exp` validated, versioned) | `Authorization: Bearer` on every API call |
| Refresh token | 30 days, single use | opaque 256-bit value, hash stored | obtain the next token pair |
| MFA token | 5 minutes | JWT, distinct `type` claim | only issued mid-login to MFA-enabled accounts; unusable as an access token |
| Verification token | 24 hours, single use | opaque, hash stored | email verification |
| Reset token | 30 minutes, single use | opaque, hash stored | password reset |

**Refresh rotation with theft detection.** Every refresh consumes the presented token and issues the next one in the same family:

```mermaid
sequenceDiagram
    participant V as Victim client
    participant A as Attacker
    participant S as Server
    V->>S: login
    S-->>V: refresh token R1 (family F)
    A-->>A: steals R1
    V->>S: refresh with R1
    S-->>V: R1 consumed, R2 issued (family F)
    A->>S: refresh with stolen R1
    S-->>A: 401 refresh_reused, family F fully revoked
    V->>S: refresh with R2
    S-->>V: 401 invalid_refresh (family dead), must log in again
```

The replayed token reveals the theft, and killing the whole family guarantees the attacker's copy dies even though the victim pays with one forced re-login. Other concurrent sessions (other families) are untouched. All of this is asserted in `tests/test_refresh_reuse.py`.

**MFA.** Enrolment is two-phase: a pending secret is only enforced after the first valid authenticator code confirms it, at which point ten hashed recovery codes are generated and shown once. Verification accepts one 30-second step of clock skew in each direction, and the accepted timestep is persisted so the same code can never be accepted twice. Recovery codes are single use and checked only after TOTP fails.

**Password reset.** Reset tokens are single use and expire in 30 minutes. A completed reset revokes every refresh-token family and bumps `users.token_version`; access JWTs carry the version they were minted with, so every outstanding access token dies at its next request. Completing a reset also proves mailbox ownership, so an unverified account becomes verified by it.

### Authorisation

One `Permission` enum (17 permissions), one explicit matrix, four roles that strictly escalate:

| Permission group | viewer | responder | admin | owner |
|---|---|---|---|---|
| View org, members, services, incidents, on-call, metrics | yes | yes | yes | yes |
| Create and update incidents, comment, upload attachments | | yes | yes | yes |
| Manage members, services, on-call; moderate comments; view audit log; manage API keys | | | yes | yes |
| Manage the organisation itself | | | | yes |

Enforcement is a single dependency, `require(*permissions)`, attached to every org-scoped route. It resolves the organisation named in the URL and the caller's membership in one query and returns an authorisation context carrying the org, so downstream queries apply the org scope at the query level rather than filtering results afterwards.

Two structural tests keep this honest:

- **Route registration.** A test walks the live route table and fails if any `/api/v1` route lacks authentication, or any org-scoped route lacks a `require()` dependency. The checker is itself tested against a deliberately unprotected route to prove it catches the mistake.
- **Tenant isolation.** A parametrised test calls every org-scoped route as an owner of a *different* organisation and asserts **404, not 403**. The caller being an owner elsewhere guarantees the failure cannot be role-based, so the 404 proves the tenant boundary. Because the parametrisation is generated from the route table at collection time, new endpoints are covered the moment they exist.

Why 404 and not 403: a 403 confirms the resource exists. Across a tenant boundary, "you cannot see this" and "this does not exist" must be the same answer, or org slugs and resource ids become an oracle.

### The exhaustive permission matrix test

Every role is crossed with every permission (4 x 17 cells) against a second, hand-written copy of the matrix in the test file. Loosening a role therefore requires editing two files in the same direction; it cannot happen by accident. Additional invariants: every role appears in the matrix, each step up the ladder only adds permissions, and no permission is unreachable.

## API

### Conventions

- Versioned under `/api/v1`. Interactive documentation at `/docs`, OpenAPI JSON at `/openapi.json`.
- Success responses wrap payloads in an envelope: `{"data": ...}` (list endpoints will add `next_cursor` with cursor pagination in phase B).
- Every error, from any layer, uses one format:

```json
{
  "error": {
    "code": "invalid_refresh",
    "message": "Refresh token is invalid",
    "details": null,
    "request_id": "6f0d2c9a4b8e4f1e9c3a7d5b2e8f1a4c"
  }
}
```

- Every response carries an `X-Request-ID` header (honoured from the client when sane, generated otherwise) and the same id appears in error envelopes, so a user-visible failure can be traced to the exact server log lines.
- Machine-readable `code` values are stable API; human-readable messages are not.

### Endpoints implemented today

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | liveness: the process serves requests |
| GET | `/health/ready` | none | readiness: the database is reachable (503 otherwise) |
| POST | `/api/v1/auth/register` | none | create an account, email a verification link |
| POST | `/api/v1/auth/verify-email` | none | consume a verification token |
| POST | `/api/v1/auth/resend-verification` | none | always 202; resends only if unverified account exists |
| POST | `/api/v1/auth/login` | none | password login; returns tokens, or an MFA challenge for MFA-enabled accounts |
| POST | `/api/v1/auth/mfa/challenge` | mfa token | complete an MFA login with a TOTP or recovery code |
| POST | `/api/v1/auth/mfa/enroll` | bearer | start TOTP enrolment (secret + otpauth URI for the QR code) |
| POST | `/api/v1/auth/mfa/verify` | bearer | confirm enrolment, receive recovery codes |
| POST | `/api/v1/auth/refresh` | refresh token | rotate the refresh token, new pair |
| POST | `/api/v1/auth/logout` | refresh token | revoke the token's whole family; idempotent |
| GET | `/api/v1/auth/me` | bearer | the authenticated account |
| POST | `/api/v1/auth/forgot-password` | none | always 202; emails a 30-minute reset link if the account exists |
| POST | `/api/v1/auth/reset-password` | none | consume a reset token, set the password, kill all sessions |
| POST | `/api/v1/orgs` | bearer | create an organisation; caller becomes owner |
| GET | `/api/v1/orgs` | bearer | organisations the caller belongs to, with their role in each |
| GET | `/api/v1/orgs/{org_slug}` | org: `org:view` | organisation details |
| PATCH | `/api/v1/orgs/{org_slug}` | org: `org:manage` | rename or update settings (owner only) |

Incidents, services, memberships, on-call, audit log, API keys, and metrics endpoints arrive in phase B on top of the same authorisation dependency, and the isolation and registration suites will cover them automatically.

## Getting started

### Prerequisites

- Docker (with Compose v2)
- For local development: Python 3.13 with [uv](https://docs.astral.sh/uv/), Node 20+ (Node 24 used in CI)

### Run the stack

```bash
git clone https://github.com/akriti-adarsh/Incident-Desk.git
cd Incident-Desk
docker compose up -d --build
```

| Service | URL | Notes |
|---|---|---|
| API | http://localhost:8000 | interactive docs at `/docs` |
| Mailpit | http://localhost:58026 | every email the app sends, in a web UI |
| PostgreSQL | localhost:55433 | user/password/db: `incident` / `incident` / `incident_desk` |
| Redis | localhost:56379 | |
| SMTP (Mailpit sink) | localhost:58025 | where the app delivers mail in development |

Host ports are deliberately non-standard so the stack never collides with a locally installed Postgres or Redis. Inside the compose network the services use standard ports.

The seeded demo environment with printed login credentials, and the web application itself, land in phase D; until then the API is exercised through `/docs`, tests, or any HTTP client.

### Local development

Backend:

```bash
cd backend
uv sync                                  # install exact locked dependencies
docker compose up -d postgres redis mailpit   # infra for tests (from repo root)
uv run pytest                            # full suite with the 85% coverage gate
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Frontend:

```bash
cd frontend
npm install
npm run test
npm run lint
npm run typecheck
```

Everything at once, from the repo root:

```bash
make test
```

### Migrations

```bash
cd backend
uv run alembic upgrade head        # apply
uv run alembic downgrade -1        # step back
uv run alembic revision --autogenerate -m "describe the change"
```

Migrations run on a synchronous psycopg URL (configured in `alembic/env.py`) while the application runs on asyncpg. The test suite drops and re-migrates its database from zero on every run, so a migration that cannot build a fresh database fails immediately.

## Configuration

All configuration is environment variables (pydantic-settings; a local `.env` is honoured). Defaults target the compose stack as seen from the host.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://incident:incident@localhost:55433/incident_desk` | application database (async driver) |
| `SYNC_DATABASE_URL` | same server, psycopg driver | Alembic migrations and autogenerate |
| `REDIS_URL` | `redis://localhost:56379/0` | cache, rate limits, pub/sub (later phases) |
| `JWT_SECRET` | dev-only value | HS256 signing key; must be at least 32 bytes |
| `JWT_ISSUER` | `incident-desk` | validated on every decode |
| `JWT_AUDIENCE` | `incident-desk-api` | validated on every decode |
| `ACCESS_TOKEN_TTL_SECONDS` | `900` | access JWT lifetime (15 minutes) |
| `REFRESH_TOKEN_TTL_DAYS` | `30` | refresh token lifetime |
| `SMTP_HOST` / `SMTP_PORT` | `localhost` / `58025` | outbound mail (Mailpit in dev) |
| `EMAIL_FROM` | `incident-desk <no-reply@incident-desk.local>` | sender address |
| `FRONTEND_BASE_URL` | `http://localhost:8080` | base for links in emails |
| `ENVIRONMENT` | `dev` | environment name |
| `TEST_DATABASE_URL` (tests only) | `...@localhost:55433/incident_desk_test` | created and migrated automatically by the test suite |
| `MAILPIT_API_URL` (tests only) | `http://localhost:58026` | where tests assert delivered email |

## Testing

### Philosophy

Integration tests run against a real PostgreSQL, real SMTP delivery, and the real HTTP stack (httpx against the ASGI app). Nothing security-relevant is mocked. Each test runs inside an outer transaction with savepoint-joined sessions and is rolled back afterwards, so tests are isolated without sacrificing realism; the test database itself is dropped and rebuilt from the migrations at the start of every run.

### What the suite proves

| Suite | The guarantee it proves |
|---|---|
| `test_schema.py` | every FK is indexed, every table has timestamps, tenant-scoped uniqueness exists (introspects the migrated database, so model/migration drift surfaces here) |
| `test_oncall_exclusion.py` | overlapping on-call shifts fail at the database with the exclusion constraint; adjacent shifts and other schedules are fine |
| `test_auth_register.py` | registration emails a working single-use token (asserted through Mailpit), duplicates conflict, weak passwords are rejected, expiry is enforced |
| `test_auth_login.py` | credential failures are uniform, unverified and inactive accounts cannot log in, rotation and logout behave |
| `test_refresh_reuse.py` | the full theft scenario: reuse kills the family, the victim's live token included, other families untouched |
| `test_auth_mfa.py` | enrolment is two-phase, replayed codes are rejected, one step of clock skew is accepted and more is not, recovery codes work exactly once |
| `test_auth_password_reset.py` | reset tokens are single use and time-limited, and a reset invalidates every session including outstanding access JWTs |
| `test_permission_matrix.py` | all 4 roles crossed with all 17 permissions match an independently written truth table; roles strictly escalate |
| `test_route_authz_registration.py` | every route is registered with auth; org routes carry the authz dependency; and the checker demonstrably catches a route that forgets |
| `test_tenant_isolation.py` | every org-scoped route answers 404 (never 403) to a cross-tenant caller, parametrised from the live route table |
| `test_models.py`, `test_health.py` | ORM round-trips, defaults, enums, error envelope, request-id propagation, readiness probe |

Current numbers (also visible in the [CI logs](https://github.com/akriti-adarsh/Incident-Desk/actions)): 146 tests, 98.47% line coverage against an enforced 85% floor, `mypy --strict` clean across 51 source files.

Phase B adds the named high-value tests from the spec that need their features first: 50 concurrent incident creations asserting gapless sequence numbers, optimistic-concurrency 409s, idempotency-key replay, and later cross-instance WebSocket delivery and job dead-lettering.

## Engineering practices

- **Locked dependencies everywhere.** `uv.lock` and `package-lock.json` are committed; Docker builds install with `--locked`; no `:latest` image tags anywhere in the stack.
- **CI runs the real thing.** GitHub Actions boots Postgres 16.10, Redis 7.4.2, and Mailpit as services and runs the same commands a developer runs. Frontend and backend are separate jobs with their own gates.
- **One error surface.** Application errors, validation failures, and bare HTTP exceptions all leave through the same envelope with a request id.
- **Migrations are tested by existence.** The suite rebuilds its database from migration zero on every run; CI will additionally gain upgrade/downgrade/upgrade and autogenerate-drift checks in phase E.
- **Pre-commit hooks** run ruff (check and format) and file hygiene checks on every commit.
- **The build follows a written spec** with a commit-per-milestone plan, a standing-rules file ([CLAUDE.md](CLAUDE.md)) requiring a green suite before every commit, and a deviations log ([DEVIATIONS.md](DEVIATIONS.md)) for any point where reality disagreed with the spec (currently empty).

## Roadmap

The remaining phases, in order, from the commit plan in the spec:

| Phase | Highlights |
|---|---|
| B (commits 11 to 20) | organisations/memberships/services management (last-owner protection), incidents with `SELECT ... FOR UPDATE` gapless numbering proven by a 50-way concurrency test, append-only timeline with a status state machine, comments and attachments, Postgres full-text search, cursor pagination with unique tiebreakers, ETag optimistic concurrency, idempotency keys stored transactionally, scoped API keys, audit log, SQL window-function metrics, Redis sliding-window rate limiting |
| C (commits 21 to 24) | single-use ticket WebSocket auth, channel subscriptions, Redis pub/sub fan-out proven across two app instances, presence with TTL, reconnect-and-reconcile client contract, ARQ workers with retries and dead-lettering, escalation chains tested on a controllable clock |
| D (commits 25 to 33) | design plan first, then the full web app: org switcher, virtualised keyboard-driven incident list, timeline-centred incident detail with optimistic comments, on-call calendar, metrics dashboard, settings, WCAG AA pass, deterministic seed data with printed credentials |
| E (commits 34 to 39) | Playwright E2E including axe scans, k6 load tests with before/after `EXPLAIN ANALYZE` in `docs/performance.md`, graceful shutdown, backup and restore scripts, runbook, migration and OpenAPI drift checks in CI, final documentation with screenshots |

## Repository guide

| File | What it is |
|---|---|
| [docs/BUILD_SPEC.md](docs/BUILD_SPEC.md) | the complete specification this project is built against |
| [CLAUDE.md](CLAUDE.md) | standing engineering rules and current build state |
| [DEVIATIONS.md](DEVIATIONS.md) | log of any spec-versus-reality adaptations |
| [docker-compose.yml](docker-compose.yml) | the full development stack |
| [Makefile](Makefile) | `make test`, `make lint`, `make type`, `make up`, `make down` |
| [.github/workflows/ci.yml](.github/workflows/ci.yml) | the CI pipeline |
