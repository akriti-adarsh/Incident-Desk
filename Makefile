.PHONY: test lint type backend-test frontend-test up down

test: backend-test frontend-test

backend-test:
	cd backend && uv run pytest

frontend-test:
	cd frontend && npm run test

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint

type:
	cd backend && uv run mypy .
	cd frontend && npm run typecheck

up:
	docker compose up -d --build

down:
	docker compose down
