# Production image for the serving API.
#
#   docker build -f docker/Dockerfile -t project-name:dev .
#   docker run --rm -p 8000:8000 --env-file .env project-name:dev
#
# Two properties this file is responsible for:
#
# 1. **Only production dependencies.** `uv sync --no-dev` installs
#    `[project].dependencies` and no dependency group, so mlflow, dvc, streamlit
#    and kfp cannot reach the image. `make docker-verify` asserts it.
#
# 2. **Only src/.** `--no-editable` makes uv build and install a wheel, and
#    pyproject's `[tool.hatch.build.targets.wheel] packages` lists just
#    src/project_name — so pipelines/, tracking/ and viz/ are absent even though
#    they sit in the repo root. .dockerignore excludes them from the build
#    context as well, so neither layer nor context carries them.
#
# Model weights are NOT baked in. The deployment mounts them at /app/.models or
# syncs them there on start, so swapping a model is a restart, not a rebuild.

ARG PYTHON_VERSION=3.12

# ── builder ───────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, in their own layer, so editing source does not re-resolve
# or re-download anything. Bind-mounting rather than copying keeps the manifests
# out of the layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project --no-editable

# Then the project itself. README.md is here because pyproject declares it as the
# readme, and hatchling reads it while building the wheel.
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# ── runtime ───────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim

# No uv, no compilers, no build cache — only the virtualenv comes across.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    PORT=8000 \
    # There is no pyproject.toml or .git in the image, so project root discovery
    # has nothing to walk up to. Set it explicitly.
    PROJECT_ROOT=/app

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/.models /app/.data \
    && chown -R appuser:appuser /app

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

USER appuser

EXPOSE 8000

# /healthz is 503 until the model finishes loading, so the start period has to
# cover a cold weight download. /livez answers 200 immediately and is what the
# Kubernetes liveness probe uses — see deploy/manifests/deployment.yaml.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5m --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8000')}/healthz\")"

ENTRYPOINT ["serve"]

# ── GPU variant ───────────────────────────────────────────────────────────────
# For a project needing CUDA wheels, add a build arg and install torch before the
# dependency sync, as ai-productsmatcher does — the CUDA runtime ships inside the
# torch wheel, so no nvidia/cuda base image is needed:
#
#   ARG COMPUTE=cpu
#   RUN if [ "$COMPUTE" = "cpu" ]; then \
#         uv pip install torch --index-url https://download.pytorch.org/whl/cpu; \
#       else uv pip install torch; fi
