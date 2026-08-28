# CLAUDE.md

A PriceShape Data & AI project generated from `data-and-ai-template`.

Read `EXECUTE.md` for how to run things and `docs/architecture.md` for why the
repository is shaped this way. This file is the short version: the rules that are
easy to break and expensive to unbreak.

## Commands

```bash
make check      # lint + types + import boundary + tests — run before saying "done"
make run        # the pipeline (refuses a dirty or unpushed tree)
make dvc-pull   # get data: sync from S3, adopt plain uploads, or create the dirs
make viz        # Streamlit run explorer
make help       # everything else
```

Never invent a command. If it is not in `make help`, it is not how this project
works.

## The one architectural rule

**Production is one directory: `src/{{PACKAGE_NAME}}/`.** That is what the wheel
contains and what the container runs. Three other roots exist and none of them ship:

| Root | Ships? | Holds | You edit it? |
| --- | :---: | --- | --- |
| `src/{{PACKAGE_NAME}}/` | yes | components, data loading, config, the FastAPI service | constantly |
| `pipelines/` | no | `build.py` — the graph, and nothing else | constantly |
| `viz/` | no | the Streamlit run explorer | often |
| `engine/` | no | DAG engine, runner, git gate, MLflow logging, DVC sync, Kubeflow backend | almost never |

`engine/` is machinery. The one part of it worth opening is `engine/kubeflow/`,
which decides how a run becomes cluster tasks.

So `src/` must never import `mlflow`, `dvc`, `streamlit`, `kfp`, `engine`,
`pipelines` or `viz`. `make imports` fails with the exact import chain if it does,
and a `PreToolUse` hook refuses the edit before that. Dev code importing `src/` is
the correct direction and is always fine.

**Nothing goes at the repository root.** No `.py` files, no `main.py`, no `app.py`.
Entry points are `[project.scripts]` in `pyproject.toml` pointing into a package.
The root is for configuration files only.

## Configuration is code

All of it is frozen dataclasses in
`src/{{PACKAGE_NAME}}/config/hyperparameters.py`. There is no `config.yaml` and no
`params.yaml`, deliberately — `tests/test_smoke.py` fails if one appears.

A hyperparameter is part of what a commit means, so it belongs in the dataclass.
Only environment-specific values come from the environment: endpoints, credentials,
log level, port. **Never put a credential in a dataclass**, even as a default.

## Pipeline nodes

A node's cache key hashes its `__call__` bytecode, its instance state (`vars(self)`)
and its upstream nodes' keys. Two consequences that bite:

- **A node must not write to `self`.** It changes its own fingerprint mid-run and
  never hits its cache again.
- **Load models lazily inside `__call__`, never in `__init__`.** Instance state is
  part of the cache key, so a loaded model in `__init__` is both slow and wrong.

Define the graph in `pipelines/build.py`. Adding a node needs no change to
`engine/dag.py` — use the `add-pipeline-node` skill.

## Data and models

`.data/` and `.models/` are DVC's, never git's. Committing anything inside them —
even a `.gitkeep` — makes `dvc add` fail outright with "output is already tracked
by SCM".

**Push before you commit the pointer.** `.data.dvc` records hashes; the content
lives in S3 and only gets there via `make dvc-push`. Commit the pointer first and
every later clone gets a `dvc pull` that fails on content that exists nowhere.

## Landmines

- **`uv run` re-syncs before running.** A bare `uv run` reinstalls the `dev` group,
  so anything asserting production-only dependencies must use `uv run --no-dev`.
- **The MLflow browser URL is not the API URL.** `mlflow.data.priceshape.io` sits
  behind an SSO proxy that answers API calls with an HTML login page. Username and
  password cannot get through it. Use the in-cluster address, or a port-forward.
- **Deleting an MLflow experiment in the UI only soft-deletes it.** The name stays
  reserved and every later run fails until it is restored.
- **A cache hit is not a re-run.** If `make run` reports `[cache hit: disk]` for
  every node, nothing recomputed. Use `uv run pipeline --no-cache` to force one.
- **The git gate is real.** `make run` refuses a dirty or unpushed tree, because
  every MLflow run is tagged with a commit SHA. `--allow-dirty` for a scratch run.

## Working here

- Run `make check` before reporting work complete. Not `make test` alone — the
  import boundary and the type checker catch different things.
- Prefer editing an existing module over adding a root-level one. If a new file
  genuinely belongs somewhere new, say why.
- When a change spans config and code, commit both together. The config *is* the
  experiment; a run whose SHA does not reproduce it is a lie.
- Secrets go in `.env`, which is git-ignored. Never in `.env.example`, never in a
  dataclass, never in a commit.
