# incident-desk backend

FastAPI service for the incident-desk platform.

```bash
uv sync          # install
uv run pytest    # tests with coverage gate
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Integration tests expect the compose Postgres and Redis from the repo root:

```bash
docker compose up -d postgres redis mailpit
```
