FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10.7 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY . .
RUN uv sync --locked --no-dev

FROM python:3.13-slim

RUN groupadd --system app && useradd --system --gid app app

WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

USER app
EXPOSE 8000

CMD ["uvicorn", "incident_desk.main:app", "--host", "0.0.0.0", "--port", "8000"]
