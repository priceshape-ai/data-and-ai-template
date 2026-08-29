---
paths:
  - "src/**/*.py"
  - "pyproject.toml"
  - "docker/**"
---

# The production boundary

You are editing code that ships. `src/` is what the wheel contains and what the
container runs; the `priceshape-ml` package, `pipelines/` and `viz/` are development-only roots that
are in neither.

## Forbidden imports under `src/`

`mlflow`, `dvc`, `streamlit`, `kfp`, and the `engine` / `pipelines` / `viz`
packages. Four mechanisms catch a violation, in the order they fire:

1. A `PreToolUse` hook refuses the edit as you make it.
2. `make imports` (import-linter) fails with the exact import chain.
3. CI installs production dependencies only and imports the serving app.
4. CI imports each dev module inside the built image and fails if one resolves.

The reason is weight, not taste: `dvc` alone pulls in around sixty packages
including botocore, aiobotocore and celery that a serving API never calls.

If production genuinely needs something a dev root has, the answer is to move that
code into `src/` — not to relax the contract.

## Adding a dependency

`[project.dependencies]` is the production contract. Everything a developer needs
and production does not belongs in a `[dependency-groups]` entry, which is never
installed by `pip install .` and never reaches the image.

Ask: does `docker/Dockerfile` need it to serve a request? If no, it is a group.

## Serving

`serving/app.py` binds the port immediately and loads the model on a background
thread. `/livez` answers as soon as the process is up; `/healthz` stays 503 until
the model is ready. Keep them distinct — pointing a liveness probe at readiness
makes Kubernetes restart the pod part-way through every slow model load.

Model weights are not baked into the image. They arrive at `/app/.models` by mount
or sync, so changing a model is a restart, not a rebuild.
