# {{PROJECT_TITLE}}

{{PROJECT_DESCRIPTION}}

A PriceShape Data & AI project. MLflow for experiment tracking, DVC on S3 for data
and model versioning, a DAG-based pipeline that runs locally or on Kubeflow, and a
FastAPI service for inference.

---

## Setup

Python 3.12 and [uv](https://docs.astral.sh/uv/) are the only prerequisites.

```bash
uv sync                 # the whole development environment
cp .env.example .env    # then fill it in
```

`uv sync` installs the `dev` dependency group by default, which pulls in
everything: linters, tests, MLflow, DVC, Streamlit and the Kubeflow SDK. There is
no second requirements file to remember.

Fetch the data and model artefacts:

```bash
make dvc-pull
```

The pipeline runs without this — the loader falls back to a small built-in sample —
so a fresh clone works before you have S3 credentials.

---

## Layout

```text
{{PROJECT_NAME}}/
├── src/{{PACKAGE_NAME}}/      # PRODUCTION. The only thing in the wheel and the image.
│   ├── config/                # all configuration: frozen dataclasses
│   ├── components/            # one module per pipeline step
│   ├── data/                  # dataset loading
│   ├── serving/               # the FastAPI service
│   └── result.py              # NodeResult, the value every node returns
├── pipelines/                 # DEVELOPMENT. The DAG engine and its backends.
│   ├── dag.py                 # engine: local cache + Kubeflow compilation
│   ├── build.py               # ← the graph definition. Start here.
│   ├── runner.py              # `uv run pipeline`
│   ├── gitgate.py             # refuses runs that could not be reproduced
│   └── kubeflow/              # the KFP backend
├── tracking/                  # DEVELOPMENT. MLflow run logging.
├── viz/                       # DEVELOPMENT. Streamlit run explorer.
├── tests/{unit,integration}/
├── docker/Dockerfile          # multi-stage, production dependencies only
├── deploy/manifests/          # Kubernetes Deployment and Service
├── .data/  .models/           # DVC-tracked, git-ignored wholesale
├── .data.dvc  .models.dvc     # DVC pointers — created by `make dvc-init`, then committed
└── notebooks/  scripts/  docs/  reports/
```

Two things about this shape are load-bearing.

**Production is one directory.** `src/{{PACKAGE_NAME}}/` is what a built wheel
contains and therefore what the container runs. `pipelines/`, `tracking/` and
`viz/` sit outside it, so MLflow, DVC, Streamlit and the Kubeflow SDK cannot reach
production by accident — they are not in the image at all. When you need to know
what runs in production, there is one place to look.

**They are still normal packages locally.** `dev-mode-dirs` in `pyproject.toml`
puts the repository root on `sys.path` for editable installs, so
`import pipelines.dag` works in a shell, a notebook and a test without any
`sys.path` manipulation — while `uv sync --no-editable` in the Dockerfile builds a
wheel that contains `src/` and nothing else.

**`.data/` and `.models/` are dot-prefixed on purpose.** Their contents are DVC's
business rather than git's, and hiding them keeps the project root about the code.
The trade-off is that a plain `ls` and Jupyter's file browser filter them out, so
reach for `ls -a`, and set `c.ContentsManager.allow_hidden = True` in your Jupyter
config to browse them from a notebook.

---

## Configuration

All of it lives in `src/{{PACKAGE_NAME}}/config/hyperparameters.py`, as frozen
dataclasses. There is no config YAML, deliberately: `Literal`-typed fields turn a
misspelled model name into an error you see immediately rather than one that
surfaces three stages into a pipeline, and the values are navigable from the code
that reads them.

```python
from {{PACKAGE_NAME}}.config import CONFIG

CONFIG.featurizer.model_name    # "BAAI/bge-m3"
CONFIG.scorer.threshold         # 0.5
```

Only environment-specific values come from the environment (`.env` locally, real
variables in Kubernetes): endpoints, credentials, log level, port. Hyperparameters
are code, so that a commit fully determines a run.

Each node config also carries a `NodeResources`, which is what lets one graph
definition run locally and on Kubeflow — locally the resources are ignored, on KFP
they become the pod's requests.

---

## Running the pipeline

```bash
uv run pipeline                     # or: make run
uv run pipeline --backend kubeflow  # compile to KFP and submit
uv run pipeline --no-cache          # recompute every node
```

Define the graph in `pipelines/build.py`. A node is any callable whose keyword
parameters are named after the nodes it depends on:

```python
load = dag.add_node("load", DatasetLoader(config.loader))
featurize = dag.add_node("featurize", Featurizer(config.featurizer), depends_on=load)
score = dag.add_node("score", Scorer(config.scorer), depends_on=featurize)
```

A node's cache key hashes its `__call__` bytecode, its instance state and its
upstream nodes' keys. So editing a component, changing a hyperparameter, or
invalidating anything upstream all invalidate it transitively — nobody maintains a
stage list. Results cache in `.dag_cache/` across runs. Keep node instances cheap
and JSON-representable and load models lazily inside `__call__`, because instance
state is part of that key.

### The git gate

The runner refuses to start when the working tree is dirty or has unpushed
commits, because every MLflow run is tagged with a commit SHA and that SHA is only
worth recording if the tree matched it.

```bash
uv run pipeline --allow-dirty     # deliberate scratch run; tagged git.dirty=true
```

It steps aside automatically where the question is unanswerable or already
answered: outside a git checkout (Kubeflow pods, `docker build`) and when `CI=true`.

### Inspecting a run

Each run writes `runs/<timestamp>/` with the graph, each node's cache status and a
JSONL trace per node. The Streamlit explorer reads those:

```bash
make viz                                  # newest run
make viz RUN=2026-08-20T09-14-02          # a specific one
```

MLflow gets the same run: hyperparameters as params, `NodeResult.metrics` as
`<node>.<metric>`, the git provenance as tags, and `runs/<timestamp>/` as
artefacts. Set `MLFLOW_TRACKING_URI` to enable it; leave it empty and the pipeline
still runs, just unrecorded.

---

## Serving

```bash
make serve            # uvicorn with reload
make docker-build     # the production image
make docker-verify    # build, then assert no dev tooling got in
```

| Endpoint | Purpose |
|---|---|
| `GET /livez` | Liveness. 200 as soon as the process is up. |
| `GET /healthz` | Readiness. 503 until the model has loaded, then 200. |
| `POST /predict` | Inference. `{"texts": [...]}` |

The two health endpoints are separate on purpose: the model loads on a background
thread so the port binds immediately, and pointing a liveness probe at readiness
would make Kubernetes restart the pod part-way through every slow model load.

Model weights are not baked into the image. They are mounted or synced to
`/app/.models` at startup, so changing a model is a restart rather than a rebuild.

---

## Data and models

DVC tracks `.data/` and `.models/` against two S3 buckets:

| Tree | Remote | Bucket |
|---|---|---|
| `.data/` | `datasets` | `s3://priceshape-datasets/{{PROJECT_NAME}}` |
| `.models/` | `models` | `s3://priceshape-models/{{PROJECT_NAME}}` |

```bash
make dvc-init    # once per project: start tracking, pinning each remote
make dvc-pull    # fetch
make dvc-add     # after changing either tree
make dvc-push    # publish
git commit .data.dvc .models.dvc .gitignore
```

`make dvc-init` is what creates `.data.dvc` and `.models.dvc`. The template does
not ship them, because a `.dvc` file with no hash reads as a pending change
forever — `dvc status` reports `deleted: .data` and the VS Code DVC extension shows
a brand-new project as dirty.

Each output pins its own remote and `.dvc/config` sets no default, so a bare
`dvc push` cannot send datasets to the models bucket. `dvc add` has no flag for
that pin, which is why `scripts/dvc_init.py` writes it; `dvc add` preserves it
afterwards.

`.data.dvc` and `.models.dvc` live in the repository root because a `.dvc` file has
to sit beside what it tracks — DVC does not support pointing one at a parent
directory, and `dvc add --file` was removed in DVC 2.0.

**Never commit anything inside `.data/` or `.models/`, not even a `.gitkeep`.** DVC
refuses to manage a directory git tracks anything inside: `dvc add .data` fails
with `output '.data' is already tracked by SCM`. Both directories are git-ignored
wholesale, and `tests/test_smoke.py` fails if that stops being true.

There is no `dvc.yaml`. `pipelines/dag.py` is the pipeline; DVC does artefact
versioning only. Two DAG engines in one repository is a maintenance tax with no
payoff.

---

## Dependencies

One file, `pyproject.toml`, split by who needs what.

```bash
uv sync                        # dev: everything
uv sync --no-dev               # production: only [project].dependencies
uv sync --only-group lint      # just the linters, for CI
```

`[project].dependencies` is the production contract — if the image does not need
it, it does not go there. Everything else is a PEP 735 dependency group, and groups
are never published and never installed by `pip install .`:

| Group | Contents |
|---|---|
| `lint` | ruff, mypy, pre-commit |
| `test` | pytest, httpx2, import-linter |
| `tracking` | mlflow-skinny (the client; the server is remote) |
| `data` | dvc[s3] |
| `viz` | streamlit |
| `orchestration` | kfp, boto3 |
| `notebook` | ipykernel |
| `dev` | all of the above, via `include-group` |

Nothing is duplicated between production and development, and moving a dependency
across the boundary is a one-line change.

Two mechanisms keep the boundary honest, and both fail CI rather than a deploy:
the import-linter contracts in `pyproject.toml`, and a job that installs
`--no-dev` and imports the serving app.

---

## Quality gates

```bash
make check    # lint + types + import boundary + tests
```

| Command | Checks |
|---|---|
| `make lint` | ruff |
| `make format` | ruff format |
| `make typecheck` | mypy across all four roots |
| `make imports` | production imports no dev-only package |
| `make test` | pytest |
| `make docker-verify` | the built image carries no dev tooling |

`make check` is what CI runs. `make docker-verify` is the one people skip and
shouldn't — it is what proves the prod/dev split still holds after a dependency
moves.
