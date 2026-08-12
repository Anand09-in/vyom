# Vyom — developer commands
# Run these in Git Bash: make <target>

.PHONY: help setup db-up db-down db-reset fmt lint test smoke \
        ingest-bse ingest-rbi ingest-sebi ingest-all eval serve

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

setup: ## Create venv + install all deps + copy .env
	uv venv
	uv pip install -e ".[dev,local,api,mcp]"
	cp -n .env.example .env || true

db-up: ## Start Postgres + pgvector + MLflow
	docker compose up -d
	@echo ""
	@echo "  Postgres  → localhost:5432"
	@echo "  MLflow    → http://localhost:5001"

db-down: ## Stop services (data is preserved)
	docker compose down

db-reset: ## Wipe everything and start fresh
	docker compose down -v
	docker compose up -d

fmt: ## Format code with ruff
	uv run ruff format .

lint: ## Lint with ruff (auto-fix safe issues)
	uv run ruff check --fix .

test: ## Run unit tests — no DB or models needed
	python -m pytest tests/unit -v

smoke: ## Integration smoke test — needs DB + Ollama running
	python -m pytest tests/integration -v -m integration

ingest-bse: ## Phase 1: pull BSE annual reports → pgvector
	python -m vyom.ingest.bse

ingest-rbi: ## Phase 1: pull RBI macro CSVs → pgvector
	python -m vyom.ingest.rbi

ingest-sebi: ## Phase 3: pull SEBI circulars → pgvector
	python -m vyom.ingest.sebi

ingest-all: ingest-bse ingest-rbi ingest-sebi ## Run all three ingest jobs

eval: ## Run RAGAS eval gate — logs to MLflow
	python eval/run_ragas.py

serve: ## Run FastAPI locally on port 8000
	uvicorn src.vyom.api.app:app --host 0.0.0.0 --port 8000 --reload