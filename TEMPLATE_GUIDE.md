# Running {{PROJECT_TITLE}}

Everything needed to set this project up, run it and ship it. For what the
pieces are and why they are arranged this way, see
[docs/architecture.md](docs/architecture.md). `make help` lists every command.

---

## First run

Everything you need to do to a repository just created from the template, in order:

```bash
cp .env.example .env           # 1. create your environment file
$EDITOR .env                   # 2. fill it in — AWS_PROFILE at least
set -a; source .env; set +a    # 3. load it into this shell
uv sync                        # 4. the whole development environment
make dvc-pull                  # 5. get the data, or create the dirs for it
make check                     # 6. lint, types, import boundary, tests
uv run pipeline                # 7. run the pipeline end to end
```

**Steps 1 to 3 come first on purpose.** Once the shell has your settings, every
command after it works without further thought — and the commonest first-day
failure is running `make dvc-pull` in a shell that never got your AWS profile.
`set -a` exports each variable as it is read; `set +a` stops that again, so only
`.env` is affected.

Step 5 is the only one that varies, and it tells you which case you are in. Step 7
works even if step 5 found no data — the loader falls back to a built-in sample.

The rest of this file explains each piece: [Setup](#setup),
[Data and models](#data-and-models), [Running the pipeline](#running-the-pipeline),
[Serving](#serving). `make help` lists every command.

---

## Setup

Python 3.12 and [uv](https://docs.astral.sh/uv/) are the only prerequisites.

```bash
cp .env.example .env         # create it
$EDITOR .env                 # fill it in
set -a; source .env; set +a  # load it into this shell
uv sync                      # the whole development environment
```

Settings first, then install. Nothing in `uv sync` needs them, but everything
after it does, and a shell that has them is one you can keep working in.

DVC reads AWS credentials the same way every AWS tool does: uncomment
`AWS_PROFILE=data` in `.env`, or set `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY`. That profile assumes `DataDevRole`, which is what grants
access to both buckets.

Leave `AWS_PROFILE` commented out rather than blank if you are not using it — an
empty value sends boto3 looking for a profile named `''` and fails with
`The config profile () could not be found`. `make dvc-pull` recognises that and
says so, but not setting it is simpler.

`uv sync` installs the `dev` dependency group by default, which pulls in
everything: linters, tests, MLflow, DVC and Streamlit. There is no second
requirements file to remember.

Then get the data and models:

```bash
make dvc-pull
```

That one command handles every situation, so there is nothing to choose between. It
looks at this project's prefix in each bucket and does whatever is called for:

| What it finds | What it does |
|---|---|
| `.data.dvc` committed in git | pulls from the DVC cache |
| plain files staged in S3 | downloads them and starts tracking them |
| nothing in S3, but data sitting in `.data/` | starts tracking that |
| nothing anywhere | creates `.data/` and `.models/` for you to fill |

So the first-run loop on a new project is: `make dvc-pull` creates the directories,
you put data in them, `make dvc-pull` again tracks it, `make dvc-push` publishes it.
Everyone after you just runs `make dvc-pull` once.

**One thing worth knowing, because it looks like a bug the first time.** `dvc pull`
on its own cannot fetch files somebody uploaded to the bucket by hand. A DVC remote
is a content-addressed cache, not a mirror: objects are stored by hash and found by
resolving those hashes out of `.dvc` files, which reach you through git.

```text
plain uploads    {{PROJECT_NAME}}/vendor_66bd29b5.db.tar.gz          invisible to dvc pull
a DVC remote     {{PROJECT_NAME}}/files/md5/0c/b3547c9cb4c508...     what dvc pull reads
```

`make dvc-pull` covers that gap by downloading such files itself and then tracking
them, which converts the first shape into the second. It is safe to re-run: it skips
what is already on disk, and never drags DVC's own `files/` cache into your data
directories when both live at the same prefix.

Either way the pipeline runs — the loader falls back to a small built-in sample — so
a fresh clone works before you have data or S3 credentials.

---

## Layout

Everything here is yours. The machinery that used to sit alongside it is now the
`priceshape-ml` package, installed like any other dependency.

```text
{{PROJECT_NAME}}/
├── src/core/                  # PRODUCTION. The only thing in the wheel and the image.
│   ├── components/            # one module per pipeline step   ← your steps
│   ├── config/                # frozen dataclasses             ← your settings
│   ├── data/                  # dataset loading
│   ├── serving/               # the FastAPI service
│   └── result.py              # NodeResult, what every step returns
├── pipelines/
│   ├── build.py               # ← THE GRAPH. Start here.
│   └── runner.py              # six lines: this project's config + graph → the engine
├── viz/app.py                 # the Streamlit run explorer
├── notebooks/                 # exploration
├── tests/{unit,integration}/
├── docker/Dockerfile          # multi-stage, production dependencies only
├── deploy/manifests/          # Kubernetes Deployment and Service
├── .data/  .models/           # DVC-tracked, git-ignored wholesale
└── .data.dvc  .models.dvc     # DVC pointers — created by `make dvc-pull`, then committed
```

The package is a development dependency, so it is absent from the production image,
exactly as the in-repository `engine/` directory it replaced was. You will rarely
need to look inside it: `priceshape_ml.dag` runs the graph, `priceshape_ml.gitgate`
holds the reproducibility gate, `priceshape_ml.tracking` writes to MLflow and
`priceshape_ml.dvc_sync` moves data.

**The import package is always `core`, in every project.** It is not renamed, so
imports read identically everywhere and nothing has to be substituted. The
distribution keeps this project's real name.

## How to work here

Recipes, not a tour. Every one of these is a real procedure against this
repository — if a command is not here or in `make help`, it is not how this
project works.

### Add a step to the pipeline

Three files, in this order. The engine is generic, so the engine never
changes.

**1. The step** — `src/core/components/ranker.py`

```python
class Ranker:
    def __init__(self, cfg: RankerConfig) -> None:
        self.cfg = cfg  # config only, nothing heavy

    def __call__(self, featurize: NodeResult) -> NodeResult:
        model = _load(self.cfg.model_name)  # lazily, on first call
        ...
        return NodeResult(items=ranked, metrics={"mean_rank": float(mean)})
```

The parameter name (`featurize`) must match the upstream step's name. A mismatch
is a `TypeError` on the first run, not a silent wrong answer.

**2. Its settings** — `src/core/config/hyperparameters.py`

```python
@dataclass(frozen=True)
class RankerConfig:
    model_name: EmbeddingModel = "BAAI/bge-m3"
    top_k: int = 10
```

Then add `ranker: RankerConfig = field(default_factory=RankerConfig)` to `Config`.

**3. The wiring** — `pipelines/build.py`

```python
rank = dag.add_node("rank", Ranker(config.ranker), depends_on=featurize)
```

Then `make check && uv run pipeline`. Everything downstream recomputes on its own.

Two rules the cache imposes, both non-negotiable: **never write to `self`**, and
**never load a model in `__init__`**. Instance state is part of the cache key.

### See the step in the graph

```bash
make viz                                 # newest run
make viz RUN=2026-08-20T09-14-02         # a specific one
```

The explorer draws the graph with each step coloured by whether it recomputed or
came from cache, lists every step with its status and timing, and lets you page
through the per-item traces. Each run also writes `runs/<timestamp>/` on disk —
the graph, the statuses, and one JSONL trace per step — which is what the explorer
reads and what MLflow uploads.

### Work out why nothing changed

If the log says `[cache hit: disk]` for the step you edited, it did not run.

A step's key hashes its `__call__` bytecode, its instance state, and its upstream
keys. Three kinds of change are invisible to that:

- editing a data file **in place** — the loader's `source` path did not change, so
  it keeps its key. Rename the file, or use `--no-cache`.
- changing a helper module the step imports but does not hold on `self`.
- an environment variable read inside `__call__`.

```bash
uv run pipeline --no-cache     # recompute everything
rm -rf .dag_cache              # or discard the cache entirely
```

The opposite symptom — a step that recomputes every time despite no edits — means
it is mutating `self`.

### Add a view to the explorer

`viz/app.py` is a normal Streamlit app and yours to extend. It reads only
`runs/<timestamp>/`, never the pipeline itself, which is why it can stay outside
the production package and import `streamlit` freely.

To surface a new number: have the step put it in `NodeResult.metrics`, then read
it from the run's status file in `viz/app.py`. Metrics flow to three places at
once — the explorer, MLflow, and `runs/`— so adding one there covers all three.

Run it against any past run with `make viz RUN=<timestamp>`; two terminals give
you two runs side by side.

### Record an experiment

Every run is logged automatically: hyperparameters as params, every step's
`NodeResult.metrics` as `<step>.<metric>`, git provenance as tags, and the whole
of `runs/<timestamp>/` as artefacts — traces included.

Deliberately **not** logged: paths, MLflow and serving settings. Those
differ between machines, and logging them would make one experiment run from two
laptops look like two configurations.

To add a number, return it in a step's `metrics`. Nothing else to wire.

```bash
uv run pipeline                # logged
uv run pipeline --no-cache     # logged, and actually recomputed
```

The git gate is what makes a run worth comparing later: it refuses a dirty or
unpushed tree, because the run is tagged with a commit SHA and that SHA has to
reproduce it. `--allow-dirty` runs anyway and tags `git.dirty=true`, so the record
stays honest.

Point `MLFLOW_TRACKING_URI` at the server first — the browser URL is **not** the
API URL. See the `diagnose-tracking` skill, or [Tracking](#tracking) below.

### Compare two runs

Change one thing, run, and compare in MLflow — the params show exactly what
differed, because every hyperparameter is logged and nothing else is. Keep the
change in a commit: `git commit` before the run, and the SHA on the run points at
the exact configuration that produced it.

An ablation is the same loop with a step disabled: comment out its `add_node` line
in `pipelines/build.py`, and everything downstream recomputes without it.

### Set up data for the first time

```bash
make dvc-pull
```

One command for every situation. It looks at this project's prefix in each bucket
and does what fits: pulls if the pointers are committed, downloads and starts
tracking if someone staged plain files there, tracks what is already in `.data/`,
or creates both directories if there is nothing anywhere.

Credentials come from `AWS_PROFILE=data`, which assumes `DataDevRole` — the role
that grants access to both buckets. Set it in `.env` or export it.

The paths are `s3://priceshape-datasets/{{PROJECT_NAME}}/closed-world` and
`s3://priceshape-models/{{PROJECT_NAME}}/closed-world`. That last segment names the
dataset variant and is the one part you may want to change; it is a single
commented line in `.dvc/config`.

### Add a dataset

```bash
cp ~/new-data.jsonl .data/raw/
# point the loader at it in config/hyperparameters.py:
#   source: str = "raw/new-data.jsonl"
make dvc-add                              # re-hash
make dvc-push                             # upload — BEFORE committing
git add .data.dvc src/*/config/hyperparameters.py && git commit && git push
```

**Push before you commit the pointer.** The `.dvc` file records hashes; the
content only reaches S3 via `make dvc-push`. Commit first and every later clone
gets a `dvc pull` that fails on content that exists nowhere.

Changing `source` changes the loader's cache key, so the whole pipeline recomputes
by itself.

### Work with several datasets

Add a **second loading step**, not a bigger config:

```python
# hyperparameters.py
train: LoaderConfig = field(default_factory=lambda: LoaderConfig(source="raw/train.jsonl"))
eval: LoaderConfig = field(default_factory=lambda: LoaderConfig(source="raw/eval.jsonl"))

# pipelines/build.py
train = dag.add_node("train", DatasetLoader(config.train))
evalset = dag.add_node("eval", DatasetLoader(config.eval))
score = dag.add_node("score", Scorer(config.scorer), depends_on=[featurize, evalset])
```

Each dataset then gets its own cache key and its own history, so swapping one does
not invalidate work that depended on the other. A step that needs both names both
in `__call__`.

DVC still tracks `.data/` as one tree — one pointer, one push, all datasets
versioned together.

### Go back to an earlier dataset

```bash
git checkout HEAD~1 -- .data.dvc && make dvc-pull
```

`dvc push` adds objects rather than replacing them, so every version you pushed is
still there. Restore the pointer and the content follows.

### Add a dependency

One question decides where it goes: **does `docker/Dockerfile` need it to serve a
request?**

```bash
uv add numpy                    # yes → [project.dependencies], ships
uv add --group dev pytest-xdist # no  → a dependency group, never in the image
```

Groups are never installed by `pip install .` and never reach the image. The guard
refuses `mlflow`, `dvc` or `streamlit` in the production list — `dvc` alone
pulls in about sixty packages a serving API never calls.

### Bump the shared engine

`priceshape-ml` — the DAG, the runner, the git gate, MLflow logging, the DVC sync —
is pinned to a tag in the `engine` group, so a change to it never arrives on its
own. Taking a new one is two steps:

```toml
# pyproject.toml
engine = [
    "priceshape-ml[tracking,data] @ git+ssh://git@github.com/priceshape-ai/data-and-ai-template@engine-v0.3.0#subdirectory=priceshape-ml",
]
```

```bash
uv lock && uv sync && make check
```

`uv.lock` records the commit the tag pointed at, so the pin is a SHA in practice —
re-tagging upstream cannot move you. Commit `pyproject.toml` and `uv.lock`
together; a lockfile that disagrees with its manifest fails CI at `uv sync --locked`.

The engine's source is in the template repository under `priceshape-ml/`. Changing
it is work you do there, not here — `TEMPLATE_README.md` in that repository has the
release steps.

> **CI needs `ENGINE_TOKEN`.** The template repository is private and this
> project's `GITHUB_TOKEN` cannot read it, so `.github/workflows/ci.yml` expects an
> organisation secret that can clone it. Without the secret the install step fails
> with a notice naming it — ask whoever administers the `priceshape-ai`
> organisation. The production image is unaffected: `uv sync --no-dev` selects no
> dependency group and never fetches the engine, which is why the production jobs
> stay green either way.

### Build the container

```bash
make docker-build      # build it
make docker-verify     # build, then prove no dev tooling got in
make docker-run        # run it locally
```

The image is multi-stage and contains `src/` and nothing else — no `priceshape_ml`,
no `pipelines/`, no `viz/`, and none of the dev-only packages. `make docker-verify`
asserts exactly that, and CI runs the same check before any tag is pushed.

Model weights are **not** baked in. They arrive at `/app/.models` by mount or sync
at startup, so changing a model is a restart rather than a rebuild.

Tagged pushes go to `626635402249.dkr.ecr.eu-central-1.amazonaws.com`, the registry
the cluster pulls from, authenticated through OIDC as `DataDevRole`. That needs
`OIDC_ROLE_ARN` set as a repository or organisation secret.

### When you need a second image

Usually you do not. Three cases, in order of how often they come up:

**Different processor targets** — one Dockerfile, a build argument. This is how
`ai-productsmatcher` ships a ~700 MB CPU image and a ~7 GB GPU image from one
recipe:

```dockerfile
ARG COMPUTE=gpu
RUN if [ "$COMPUTE" = "cpu" ]; then \
        pip install torch --index-url https://download.pytorch.org/whl/cpu; \
    else pip install torch; fi
```

Then a second workflow with `--build-arg COMPUTE=cpu` and a `cpu-` tag prefix.

**A genuinely separate service** — a second `docker/Dockerfile.<name>` and a second
workflow. Reach for this only when it serves different traffic, not to slim an
image.

### Deploy the service

`deploy/manifests/` holds a Deployment and a Service. Before applying them, the
image tag has to exist in the registry — push a tag and let the build workflow run.
The Deployment mounts model weights at `/app/.models`; the two health probes must
stay pointed at their own endpoints, `/livez` for liveness and `/healthz` for
readiness.

### Add an API endpoint

`src/core/serving/app.py`, with the inference logic in
`inference.py` beside it. This is production code, so the boundary applies: no
`mlflow`, no `dvc`, no `streamlit`. Add a test in
`tests/integration/test_api.py`.

Keep `/livez` and `/healthz` distinct. The model loads on a background thread so
the port binds immediately; pointing a liveness probe at readiness makes Kubernetes
restart the pod part-way through every slow load.

### Add a test

| What you are testing | Where |
| --- | --- |
| A step, the engine, config, the explorer | `tests/unit/` |
| The pipeline end to end, the API | `tests/integration/` |
| The layout and the boundary itself | `tests/test_smoke.py` |

`make check` runs lint, types, the import boundary and the suite. Run it before
calling anything done — the four catch different things.

### Tracking

`MLFLOW_TRACKING_URI` decides everything. The browser URL is **not** the API URL:
`mlflow.data.priceshape.io` sits behind an SSO proxy that answers API calls with an
HTML login page, and no username or password gets through it.

```bash
# From inside the cluster — no auth needed
MLFLOW_TRACKING_URI=http://mlflow.mlflow.svc.cluster.local

# From a laptop. The server enforces a Host allowlist, so the hostname must
# survive the tunnel — map it to localhost for the session.
sudo sh -c 'echo "127.0.0.1 mlflow.data.priceshape.io" >> /etc/hosts'
kubectl port-forward -n mlflow svc/mlflow 5000:80
MLFLOW_TRACKING_URI=http://mlflow.data.priceshape.io:5000
```

Leave it empty and the pipeline still runs, just unrecorded. If a run fails to log,
the warning says which of the three usual causes it was — SSO proxy, rejected
credential, or an experiment someone deleted in the UI (which only soft-deletes it
and keeps the name reserved).

---

## Configuration

All of it lives in `src/core/config/hyperparameters.py`, as frozen
dataclasses. There is no config YAML, deliberately: `Literal`-typed fields turn a
misspelled model name into an error you see immediately rather than one that
surfaces three stages into a pipeline, and the values are navigable from the code
that reads them.

```python
from core.config import CONFIG

CONFIG.featurizer.model_name  # "BAAI/bge-m3"
CONFIG.scorer.threshold  # 0.5
```

Only environment-specific values come from the environment (`.env` locally, real
variables in Kubernetes): endpoints, credentials, log level, port. Hyperparameters
are code, so that a commit fully determines a run.

---

## Running the pipeline

```bash
uv run pipeline                # or: make run
uv run pipeline --no-cache     # recompute every node
uv run pipeline --allow-dirty  # scratch run on a dirty tree
uv run pipeline --no-save      # do not write anything under runs/
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
answered: outside a git checkout (`docker build`, a container) and when `CI=true`.

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

**The browser URL is not the API URL.** `https://mlflow.data.priceshape.io` is
behind the platform's SSO proxy, which answers an API call with a redirect to a login
page; MLflow parses the HTML and reports `response body was not in a valid JSON
format`. No username or password gets past that — the proxy wants an OAuth session,
not HTTP basic auth. Point the client at the server directly:

```bash
# From inside the cluster — no auth needed
MLFLOW_TRACKING_URI=http://mlflow.mlflow.svc.cluster.local

# From a laptop — port-forward. The server enforces a Host allowlist, so the
# hostname has to survive; map it to localhost for the session.
sudo sh -c 'echo "127.0.0.1 mlflow.data.priceshape.io" >> /etc/hosts'
kubectl port-forward -n mlflow svc/mlflow 5000:80
MLFLOW_TRACKING_URI=http://mlflow.data.priceshape.io:5000
```

Either way the pipeline still finishes if tracking fails — the run is logged to
`runs/` regardless, and the warning says which of these two problems it hit.

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
make dvc-pull    # get data: sync, adopt, track or create — whichever applies
make dvc-push    # publish
make dvc-add     # re-hash after changing either tree
```

`make dvc-pull` is what creates `.data.dvc` and `.models.dvc`. The template does not
ship them, because a `.dvc` file with no hash reads as a pending change forever —
`dvc status` reports `deleted: .data` and the VS Code DVC extension shows a
brand-new project as dirty.

**Push before you commit the pointer.** `.data.dvc` records hashes; the content
those hashes name lives in S3 and gets there via `make dvc-push`. Commit the pointer
without pushing and everyone else — including future you, on a fresh clone — gets a
`dvc pull` that fails, because the pointer names content that exists nowhere. Always:

```bash
make dvc-add     # re-hash
make dvc-push    # upload — this one first
git add .data.dvc .models.dvc .gitignore && git commit
```

`make dvc-pull` detects that situation and says so, but the only real fix is a
`make dvc-push` from a machine that still has the files. If none does, the data is
gone and the pointer has to be deleted.

**Never commit anything inside `.data/` or `.models/`, not even a `.gitkeep`.** DVC
refuses to manage a directory git tracks anything inside: `dvc add .data` fails with
`output '.data' is already tracked by SCM`. Both are git-ignored wholesale, and
`tests/test_smoke.py` fails if that stops being true.

Each output pins its own remote and `.dvc/config` sets no default, so a bare
`dvc push` cannot send datasets to the models bucket. `.data.dvc` and `.models.dvc`
sit in the repository root because a `.dvc` file has to live beside what it tracks
— DVC does not support pointing one at a parent directory, and `dvc add --file` was
removed in DVC 2.0.

There is no `dvc.yaml`. the engine is the pipeline; DVC does artefact
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
| `engine` | priceshape-ml, pinned to an `engine-v*` tag |
| `lint` | ruff, mypy, pre-commit |
| `test` | pytest, httpx2, import-linter |
| `tracking` | mlflow-skinny (the client; the server is remote) |
| `data` | dvc[s3] |
| `viz` | streamlit |
| `notebook` | ipykernel |
| `dev` | all of the above, via `include-group` |

Nothing is duplicated between production and development, and moving a dependency
across the boundary is a one-line change.

Two mechanisms keep the boundary honest, and both fail CI rather than a deploy:
the import-linter contracts in `pyproject.toml`, and a job that installs
`--no-dev` and imports the serving app.

---

## Working with Claude Code

The repository explains and defends its own architecture, so an agent — or a new
teammate reading over its shoulder — gets the rules without being told.

| File | Loaded | Does |
| --- | --- | --- |
| `CLAUDE.md` | every session | the invariants and landmines, kept under 200 lines |
| `.claude/rules/*.md` | when you touch matching files | the deep rules for one area |
| `.claude/skills/*/SKILL.md` | when the task matches | step-by-step workflows |
| `.claude/hooks/architecture_guard.py` | before every edit | refuses structural violations |

The split matters. `CLAUDE.md` and the rules are *context*: Claude reads them and
generally follows them. The hook is *enforcement*: it runs regardless of what any
model decides, which is why the structural rules live there and the judgement calls
do not.

```text
.claude/
├── settings.json                    # wires the hook; committed, so the team shares it
├── hooks/architecture_guard.py      # refuses root .py files, forbidden imports, …
├── rules/
│   ├── production-boundary.md       # loads when editing src/, pyproject, docker/
│   ├── pipeline-nodes.md            # loads when editing pipelines/ or components/
│   └── data-versioning.md           # loads when editing .dvc files or .gitignore
└── skills/
    ├── add-pipeline-node/           # add or rewire a DAG step
    ├── sync-data/                   # datasets in and out of S3
    ├── diagnose-tracking/           # why a run did not reach MLflow
    └── debug-pipeline-cache/        # why results did not change
```

What the hook refuses, each with the alternative named:

- a `.py` file at the repository root
- `mlflow`, `dvc`, `streamlit`, `priceshape_ml`, `pipelines` or `viz` imported
  under `src/`
- `config.yaml`, `params.yaml`, `requirements.txt` reappearing
- a `.gitkeep` inside `.data/` or `.models/`
- one of the heavy dev packages added to `[project.dependencies]`

It asks rather than refuses for two judgement calls: hand-editing a `.dvc` file,
and giving a credential-shaped field a literal default. It fails open on anything
it does not understand — a guard that blocks work when confused is worse than none.

`tests/unit/test_architecture_guard.py` tests both directions, because a guard that
starts blocking legitimate work gets switched off.

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
