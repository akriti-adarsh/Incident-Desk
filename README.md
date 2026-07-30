# incident-desk

Multi-tenant incident management platform: cross-org RBAC, rotating refresh tokens with theft detection, real-time collaboration over Redis-backed WebSockets, optimistic concurrency, and a full E2E and load-test suite.

Under active build. The build spec lives in [docs/BUILD_SPEC.md](docs/BUILD_SPEC.md).

## Quick start

```bash
docker compose up
```

- API: http://localhost:8000 (OpenAPI docs at `/docs`)
- Mailpit (captured email): http://localhost:58026

## Development

Backend (Python 3.13, uv):

```bash
cd backend
uv sync
uv run pytest
```

Frontend (React + TypeScript + Vite):

```bash
cd frontend
npm install
npm test
```

Or from the repo root: `make test`.
