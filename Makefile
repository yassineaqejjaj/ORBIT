# ORBIT — common tasks. Run `make help` for the list.

COMPOSE ?= docker compose
BACKEND_DIR := backend
FRONTEND_DIR := frontend

# Host-side URLs of the compose infrastructure (used by dev-backend / dev-worker, run from backend/).
DEV_ENV := ORBIT_DATABASE_URL=postgresql+asyncpg://orbit:orbit@localhost:5433/orbit \
	ORBIT_OPENSEARCH_URL=http://localhost:9201 \
	ORBIT_VALKEY_URL=redis://localhost:6380/0 \
	ORBIT_OBJECT_STORE_PATH=.data/objects

.DEFAULT_GOAL := help
.PHONY: help up down logs build migrate seed test lint dev-backend dev-worker dev-frontend infra reset ps

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

up: ## Build and start the whole platform (web on http://localhost:3000)
	$(COMPOSE) up -d --build

down: ## Stop the platform (data volumes are kept)
	$(COMPOSE) down

logs: ## Follow the logs of every service
	$(COMPOSE) logs -f --tail=200

build: ## Build the images
	$(COMPOSE) build

ps: ## Show service status
	$(COMPOSE) ps

migrate: ## Apply database migrations (inside the api container)
	$(COMPOSE) exec api alembic upgrade head

seed: ## Load the demo project through the real ingestion pipeline
	$(COMPOSE) exec api python -m app.seed

infra: ## Start only postgres, opensearch and valkey (for dev-backend / tests)
	$(COMPOSE) up -d postgres opensearch valkey

test: ## Run the backend test suite (needs `make infra`)
	cd $(BACKEND_DIR) && uv run pytest

lint: ## Lint the backend
	cd $(BACKEND_DIR) && uv run ruff check app tests && uv run ruff format --check app tests

dev-backend: ## Run the API on the host with auto-reload (needs `make infra`)
	cd $(BACKEND_DIR) && $(DEV_ENV) uv run alembic upgrade head && \
		$(DEV_ENV) uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

dev-worker: ## Run the worker on the host (needs `make infra`)
	cd $(BACKEND_DIR) && $(DEV_ENV) uv run python -m app.worker

dev-frontend: ## Run the Next.js dev server on the host (proxy to http://localhost:8000)
	cd $(FRONTEND_DIR) && if [ -f pnpm-lock.yaml ]; then pnpm install && ORBIT_API_URL=http://localhost:8000 pnpm dev; \
		else npm install && ORBIT_API_URL=http://localhost:8000 npm run dev; fi

reset: ## Destroy all data volumes and restart from scratch
	$(COMPOSE) down -v --remove-orphans
	$(COMPOSE) up -d --build
