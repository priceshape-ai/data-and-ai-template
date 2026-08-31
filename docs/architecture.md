# Architecture

Why this repository is shaped the way it is. The trees and commands are in
[`TEMPLATE_GUIDE.md`](../TEMPLATE_GUIDE.md); this file covers the decisions.

## The one rule: production is one directory

`src/core/` is what a built wheel contains, and therefore what the
container runs. `pipelines/`, the `priceshape-ml` package and `viz/` are separate top-level roots.

```
src/core/   →  in the wheel, in the image, runs in production
pipelines/              →  development only (the graph and its wiring)
viz/                    →  development only (the explorer)
priceshape-ml           →  a dependency, not a root
```

In a generated project that is the whole list: `priceshape-ml` arrives as an
installed wheel and there is no fourth directory. The template repository has one
more — `priceshape-ml/`, the engine's own source — and
[Where the engine lives](#where-the-engine-lives) explains why it sits there and
why `bootstrap.py` deletes it on the way out.

Everything else follows from that. Ask "what runs in production?" and the answer is
one directory rather than a judgement call about eight files at the repository root.

### How the boundary is held

Four mechanisms, in increasing order of how early they catch a mistake:

| Mechanism | Catches |
| --- | --- |
| `[dependency-groups]` in `pyproject.toml` | `uv sync --no-dev` cannot install mlflow, dvc, streamlit or kfp |
| `.dockerignore` + `packages = ["src/core"]` | those roots are in neither the build context nor the wheel |
| `import-linter` contracts (`make imports`) | `src/` importing a dev-only package, statically, in milliseconds |
| CI: `uv sync --no-dev` then import the serving app | anything the static check missed, before merge |
| CI: import each dev module inside the built image | a leak that survived all of the above |

The import-linter contract is the one worth understanding. It is not decoration —
add `import mlflow` anywhere under `src/` and `make imports` fails with the exact
import chain. A comment saying "don't import mlflow here" would not.

### Why the dev roots are still importable

Four top-level roots would normally mean `sys.path` manipulation. One setting avoids
it:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/core"]   # what a built wheel contains
dev-mode-dirs = [".", "src"]      # what an editable install puts on sys.path
```

`dev-mode-dirs` applies to editable installs only. `uv sync` installs the project
editable, so `import pipelines.dag` works everywhere locally; `uv sync --no-editable`
in the Dockerfile builds a wheel, which contains only `src/`. The same asymmetry the
layout wants, expressed once.

`[tool.ruff] src = ["src", "."]` mirrors it, for the same reason — listing
`"pipelines"` there instead would make that package's *submodules* look top-level
and scramble import sorting.

The cost: with `.` on the path, `tests` and `scripts` are importable names in
development. It disappears in the wheel.

## Where the engine lives

`priceshape-ml` is a separate distribution with its own `pyproject.toml`, its own
lockfile and its own tests. Its *source* lives in this repository, at
`priceshape-ml/`. Those two facts are not in tension, and the arrangement is
deliberate.

A project depends on it the ordinary way — a pinned git reference in the `engine`
dependency group:

```
priceshape-ml[tracking,kubeflow,data] @
  git+ssh://git@github.com/priceshape-ai/data-and-ai-template@engine-v0.1.0#subdirectory=priceshape-ml
```

uv resolves the tag once and records the commit it pointed at, so `uv.lock` pins a
SHA even though the URL names a tag. Bumping the pin is a deliberate edit, never a
surprise.

### Why one repository and not two

The engine and the template change together. A new node-configuration field means
an engine change *and* a template change; splitting them across two repositories
means two pull requests, two reviews, and a window in which `main` of one does not
work with `main` of the other. Here they land in one commit, and
`.github/workflows/engine.yml` checks the engine on the same push that checks the
template.

The cost is one piece of discipline: **the engine must never import the project.**
It reads `log_level`, `paths`, `mlflow` and `kubeflow` off a duck-typed config
object and matches `NodeResult` structurally through a `runtime_checkable`
Protocol, so it never imports `core` or `pipelines`. Living in the same
repository makes that easy to violate by accident, which is why the engine's tests
build against a `StubConfig` that shares nothing with this project.

### Why generated projects do not keep a copy

GitHub's **Use this template** copies the entire tree, `priceshape-ml/` included.
A copy left in place would be an unpinned second engine, drifting from the one the
lockfile actually installs — exactly the failure this arrangement exists to
prevent, and the one that produced two near-identical MLflow loggers in the older
projects. So `bootstrap.py` removes the directory and the `engine-check` make
target as part of scaffolding removal, and `SKIP_DIRS` keeps the substitution pass
out of it on the way past.

`.github/workflows/engine.yml` survives, because nothing can delete a workflow file
during bootstrapping — GitHub rejects any `GITHUB_TOKEN` push that touches
`.github/workflows/`. It is inert instead: a path filter that no change in a
generated project can match, plus a directory check for the manual trigger.

### What this costs a private repository

The template repository is private, so fetching the engine needs a credential that
`GITHUB_TOKEN` cannot supply — it is scoped to the calling repository alone. A
generated project's CI therefore needs `ENGINE_TOKEN`, an organisation secret that
can clone the template; `ci.yml` uses it to rewrite `ssh://` to authenticated
`https://`, which leaves a developer's own SSH key untouched.

The production path needs none of it. `uv sync --no-dev` selects no dependency
group, so the image never fetches the engine at all. If the production CI job ever
starts asking for `ENGINE_TOKEN`, that is the signal that something has moved the
engine into `[project.dependencies]` and the boundary has broken.

## One DAG engine, not two

the engine is the pipeline. DVC does artefact versioning only, and there is
no `dvc.yaml`.

DVC pipelines are a reasonable choice on their own, but they are process-per-stage
with files between stages, and this DAG passes Python objects in memory and caches
per node — and per *item*, via `ItemCache`, which is what makes a node that does an
LLM call per record affordable to re-run. Running both would mean two dependency
graphs to keep in sync, two caches with different invalidation rules, and a standing
question about which one is authoritative.

### One definition, two backends

The same graph runs locally and on Kubeflow:

```
pipelines/build.py          the graph — the only file that knows the shape
        │
priceshape_ml/dag.py
        ├── run(backend="local")     in-process, pickle cache in .dag_cache/
        └── run(backend="kubeflow")  one pod per node, results via S3/MinIO
```

Two details make that work without the graph being written twice:

**Resources travel with the node.** Each node config carries a `NodeResources`
(`cpu_request`, `memory_request`, `accelerator_type`, `node_pool`). Locally it is
ignored; on KFP it becomes the pod's request. So a GPU node declares that where its
hyperparameters live, not in a separate manifest.

**One generic component runs every node.** `dag.py` pickles each node's callable to
object storage and compiles one task per node, all sharing
`priceshape_ml/kubeflow/node_runner.py`. Adding a node never means writing a KFP
component or rebuilding an image.

`node_runner.py` inlines its own S3 helpers rather than importing
`priceshape_ml/kubeflow/storage.py`, because KFP lightweight components ship only the
function's source — and because `pipelines/` is not in any image. What the pod does
need is the *package*, to unpickle callables that reference
`core.components...`. Point `KUBEFLOW_BASE_IMAGE` at this project's own
production image: it contains `src/` and nothing else, which is exactly right.

### Cache invalidation

A node's cache key hashes its `__call__` bytecode, its instance state (`vars(fn)`),
and its upstream nodes' keys. Nobody maintains a stage list: edit a component, change
a hyperparameter, or invalidate anything upstream, and everything downstream
invalidates transitively.

The consequence is a real constraint: **a node must not write to `self`.** A node
that increments a counter on itself changes its own fingerprint and never hits its
cache — `tests/unit/test_dag.py::test_mutating_instance_state_invalidates_own_cache`
pins that down. Hold the config, load models lazily inside `__call__`.

## Configuration is code

All of it is frozen dataclasses in `src/core/config/hyperparameters.py`,
matching the filename `taxonomy-engine` and `ai-productsmatcher` already use. No
`config.yaml`, no `params.yaml`.

The reasoning: a hyperparameter is part of what a commit means. `Literal`-typed
fields make a misspelled model name an immediate error rather than one that surfaces
three stages in, the values are navigable from the code that reads them, and there is
one place to look. A YAML layer adds a second source of truth and a resolution step,
and buys editability that nobody on this team actually needs.

Only environment-specific values come from the environment — endpoints,
credentials, log level, port. Those are the things that genuinely differ between a
laptop and a cluster, and they are exactly the things that must *not* be baked into
a commit.

`load_dotenv()` is called in `hyperparameters.py`, before `CONFIG` is built, rather than in
the entrypoint. `CONFIG` is a module-level singleton, so an entrypoint that imported
it before loading `.env` would silently get defaults — a bug the reference project it
was ported from actually has. Owning the load in the config module makes
`from core.config import CONFIG` safe from anywhere, and it is a no-op
when there is no `.env`, which is the production case.

## Reproducibility gate

Every MLflow run is tagged with a commit SHA, and a SHA is only worth recording if
the tree matched it. So `priceshape_ml.gitgate` refuses to start when the tree is
dirty or has unpushed commits.

It steps aside in three cases, and the first is the important one:

- **No git repository** — Kubeflow pods, `docker build`, some CI checkouts. The gate
  cannot answer, so it does not fail. A gate that hard-fails wherever it cannot run
  is a gate that stops production.
- **`CI=true`** — CI runs from a fixed commit by definition.
- **`--allow-dirty` / `PIPELINE_ALLOW_DIRTY=1`** — a deliberate scratch run, tagged
  `git.dirty=true` so the record stays honest.

Nothing is exempt from the dirty check, including the config directory. Config *is*
the experiment; exempting it is what makes a recorded SHA a lie.

Git introspection lives in `gitgate.py`, not in `tracking.py`, so the MLflow logger
stays a pure function of its arguments and never shells out. That is also why
`priceshape_ml` is forbidden from importing `pipelines/` — the tags are passed in.

## Failure modes that shaped the code

Choices that look arbitrary until the failure happens:

**`/livez` and `/healthz` are separate.** `/healthz` is 503 until the model loads;
`/livez` is 200 as soon as the process is up. Pointing a liveness probe at readiness
makes Kubernetes restart the pod part-way through every slow model load, forever.

**The model loads on a background thread.** A container that blocks on a
multi-gigabyte download before binding its port looks dead to Kubernetes and gets
killed.

**MLflow's retries are bounded.** The client defaults to 7 retries with exponential
backoff, so an unreachable server stalls an already-finished pipeline for minutes.
`priceshape_ml.tracking` lowers that to seconds via `os.environ.setdefault`.

**`log_run` never raises.** A tracking outage must not destroy a run whose results
are already on disk. Failures downgrade to a warning; the traceback goes to DEBUG,
because an unreachable server is an operational event, not a crash.

**Model weights are not in the image.** They are mounted or synced at startup, so a
model change is a restart rather than a rebuild — and the image stays small enough to
pull quickly.

**`.dvc` files are at the repository root.** Not tidiness — necessity. A `.dvc` file
must sit beside what it tracks; DVC does not support a parent-relative `outs` path,
and `dvc add --file` was removed in DVC 2.0.

**No default DVC remote.** `.dvc/config` leaves `core.remote` unset and each out pins
its own, so a bare `dvc push` cannot send datasets to the models bucket.

## The architecture defends itself

Four mechanisms already enforce the production boundary — dependency groups, the
Docker context, import-linter, and CI. A fifth sits earlier than all of them: a
`PreToolUse` hook in `.claude/settings.json` that refuses the edit as it is made.

That ordering is the point. import-linter tells you at `make imports`; CI tells you
at the pull request; the hook tells you before the file is written, and hands back
the rule rather than a stack trace. Same contract, four chances to learn it.

The division of labour follows the Claude Code documentation's own distinction:

- **`CLAUDE.md` and `.claude/rules/`** are context. Claude reads them and generally
  follows them; they carry the *why*, which a guard cannot.
- **The hook** is enforcement. It runs regardless of what any model decides, so it
  carries only rules that are structural, statically decidable, and have an obvious
  correct alternative.

Anything needing judgement stays in the rules files. A guard that encodes taste
produces false positives, and a guard with false positives gets disabled — at which
point it protects nothing.

The rules are path-scoped through `paths:` frontmatter, so they cost no context
until Claude touches a matching file. `CLAUDE.md` stays under the 200-line budget
that keeps adherence high, and the depth lives in the rules and skills that load on
demand.
