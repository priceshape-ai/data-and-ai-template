# priceshape-ml

The machinery every PriceShape Data & AI project shares: a DAG that turns a graph
of callables into a cached run, the reproducibility gate, MLflow run logging, and
the DVC sync.

It knows nothing about any particular project. What the steps are and how they are
configured arrive as arguments, which is what lets one copy serve every repository —
and what makes a bug fix here a version bump rather than a copy-paste into each one.

This directory is the engine's source. It lives inside `data-and-ai-template`
because the engine and the template change together — see
[Where the engine lives](../docs/architecture.md#where-the-engine-lives) — but it
is a separate distribution with its own lockfile, its own tests and its own CI job,
and projects install it as a pinned wheel, never as a path.

```bash
uv add "priceshape-ml[tracking,data] @ git+https://github.com/priceshape-ai/data-and-ai-template@engine-v0.2.1#subdirectory=priceshape-ml"
```

## What a project provides

```python
# pipelines/runner.py — the whole wiring
from core.config import CONFIG
from pipelines.build import build_pipeline
from priceshape_ml import run


def main() -> int:
    return run(build_pipeline, CONFIG)
```

`config` is duck-typed: the engine reads `log_level`, `paths` and `mlflow` off it
and ignores everything else, so a project hangs its own hyperparameters beside
those without this package needing to know.

## Extras

| Extra | Brings | Needed for |
| --- | --- | --- |
| `tracking` | `mlflow-skinny` | recording runs |
| `data` | `dvc[s3]` | `priceshape_ml.dvc_sync` |

The base install has **no dependencies at all**, so a project that only wants the
DAG gets the DAG and nothing else.

## Working on it

From the template repository root:

```bash
make engine-check          # lint, format, types and tests, on the engine alone
cd priceshape-ml && uv sync && uv run pytest -k dag
```

The engine has its own environment on purpose. A project installs a built wheel, so
the engine has to stand up without anything the template provides — `tests/conftest.py`
builds a `StubConfig` that shares nothing with any project, which is what keeps the
duck-typed config contract honest.

**The engine must never import a project.** No `core`, no `pipelines`, no `viz`.
It reads `log_level`, `paths` and `mlflow` off whatever config object it is handed,
and matches `NodeResult` structurally through a `runtime_checkable` Protocol. Sharing a repository with the template makes that easy to break by
accident; nothing but discipline and those tests prevents it.

## Releasing

Tag the commit. Consumers pin the tag, so nothing moves under them until they bump.
The prefix matters: `engine-v*` tags the engine, plain `v*` tags the template and
triggers an image build.

```bash
git tag -a engine-v0.2.0 -m "priceshape-ml 0.2.0 — <what changed>"
git push origin engine-v0.2.0
```

Then bump the consumers. In each project, edit the `engine` group in
`pyproject.toml` to the new tag and run `uv lock` — uv records the tag's commit, so
the lockfile pins a SHA either way.

Bump `version` in this directory's `pyproject.toml` in the same commit as the change
it describes, not at tag time; a wheel whose version does not match its tag is how
two projects end up believing they run the same engine when they do not.
