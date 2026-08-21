.DEFAULT_GOAL := help
PACKAGE := project_name
IMAGE    := project-name
RUN      ?=

.PHONY: help install lint format typecheck imports test check run serve viz \
        dvc-init dvc-add dvc-pull dvc-push docker-build docker-run docker-verify clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ── environment ───────────────────────────────────────────────────────────────

install:  ## Install everything a developer needs (uv installs the dev group by default)
	uv sync

# ── quality gates ─────────────────────────────────────────────────────────────

lint:  ## Lint
	uv run ruff check .

format:  ## Format
	uv run ruff format .

typecheck:  ## Type-check every root
	uv run mypy src pipelines tracking viz

imports:  ## Enforce the prod/dev import boundary
	uv run lint-imports

test:  ## Run the test suite
	uv run pytest

check: lint typecheck imports test  ## Everything CI runs

# ── running ───────────────────────────────────────────────────────────────────

run:  ## Run the pipeline (gated on a clean, pushed git tree)
	uv run pipeline

serve:  ## Serve the API locally with reload
	uv run uvicorn $(PACKAGE).serving.app:app --reload --port 8000

viz:  ## Explore pipeline runs. Pick one with: make viz RUN=2026-08-20T09-14-02
	uv run streamlit run viz/app.py -- $(RUN)

# ── data & models ─────────────────────────────────────────────────────────────

dvc-init:  ## First time only: start tracking .data/ and .models/, pinning each remote
	uv run python scripts/dvc_init.py

dvc-add:  ## Recompute the hashes in .data.dvc / .models.dvc after changing either tree
	uv run dvc add .data .models

dvc-pull:  ## Fetch data and models from S3
	uv run dvc pull

dvc-push:  ## Publish data and models to S3
	uv run dvc push

# ── container ─────────────────────────────────────────────────────────────────

docker-build:  ## Build the production image
	docker build -f docker/Dockerfile -t $(IMAGE):dev .

docker-run:  ## Run the production image
	docker run --rm -p 8000:8000 --env-file .env $(IMAGE):dev

docker-verify: docker-build  ## Assert the image carries no dev-only tooling
	@echo "Checking the image for dev-only packages and roots..."
	@for module in mlflow dvc streamlit kfp; do \
		if docker run --rm --entrypoint python $(IMAGE):dev -c "import $$module" 2>/dev/null; then \
			echo "FAIL: $$module is installed in the production image"; exit 1; \
		fi; \
	done
	@for module in pipelines tracking viz; do \
		if docker run --rm --entrypoint python $(IMAGE):dev -c "import $$module" 2>/dev/null; then \
			echo "FAIL: the $$module root leaked into the production image"; exit 1; \
		fi; \
	done
	@docker run --rm --entrypoint python $(IMAGE):dev -c "import $(PACKAGE).serving.app" \
		|| { echo "FAIL: the serving app does not import with production deps only"; exit 1; }
	@echo "OK: production image is clean."

# ── housekeeping ──────────────────────────────────────────────────────────────

clean:  ## Remove caches and build artefacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build *.egg-info htmlcov .coverage
