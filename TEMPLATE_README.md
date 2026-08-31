# data-and-ai-template

The standard starting point for PriceShape Data, Data Science and AI/ML repositories.
MLflow, DVC on S3, a DAG-based pipeline that runs locally or on Kubeflow, a FastAPI
service, and a hard separation between what production runs and what development
needs.

> **This file documents the template itself.** `bootstrap.py` deletes it from
> generated repositories, along with itself, so a new project keeps only its own
> `README.md`, `TEMPLATE_GUIDE.md`, `CLAUDE.md` and the `.claude/` directory.

---

## Generate a repository

Any of these produces the same result.

**The button.** Open the template repository, click **Use this template → Create a
new repository**, and name it.

**The new-repository page.** [github.com/new](https://github.com/new), then pick
`priceshape-ai/data-and-ai-template` from the **Repository template** dropdown.

**The CLI.**

```bash
gh repo create my-new-project \
  --template priceshape-ai/data-and-ai-template \
  --private --clone
```

**Name the repository well** — it is the only input the bootstrapper needs.
`churn-predictor` becomes the package `churn_predictor` and the title
`Churn Predictor`. Add a description while you are there; it becomes the project
description.

Then:

```bash
cp .env.example .env
$EDITOR .env                 # AWS_PROFILE at least
set -a; source .env; set +a
uv sync
uv run pytest
```

## What happens on the first push

`.github/workflows/bootstrap.yml` runs `bootstrap.py`, which:

1. Substitutes every token and the `project-name` sentinel, deriving the values
   from the repository name, owner and description.
2. Removes `priceshape-ml/` — the engine's source belongs to the template, and a
   project consumes it as a pinned dependency.
3. Re-sorts imports and reformats, so a generated project does not start life with
   a red `ruff check`.
4. Validates the result — every rewritten `.py` still parses, no token or sentinel
   survives, `src/core/` exists. If anything fails it leaves `bootstrap.py` in
   place and exits non-zero, so CI does not commit a broken tree.
5. Commits, deletes `bootstrap.py` and `TEMPLATE_README.md`, and disables itself.

It does **not** rename the package directory. `src/core/` keeps that name in every
project — see [Sentinels](#sentinels--the-literal-project-name) below.

Two guards stop it rewriting the template itself, and it needs both:

```yaml
github.event.repository.is_template == false &&
github.repository != 'priceshape-ai/data-and-ai-template'
```

`is_template` alone is not enough, and relying on it destroyed this template once.
You create the repository, push, and only *then* tick **Template repository** in
settings — so on that first push `is_template` is still `false`, the guard passes,
and the workflow bootstraps the template: it substitutes every token, removes
`priceshape-ml/`, and deletes `bootstrap.py`. Every repository generated afterwards
inherits the template's own name, with no bootstrapper and no engine source left to
fix it.
The name check needs no setting anyone has to remember, so it holds from the first
push. `bootstrap.py` refuses the same thing locally, via `TEMPLATE_PROJECT_NAMES`.

If you rename or fork this template, **update both that literal and
`TEMPLATE_PROJECT_NAMES` in `bootstrap.py`** — they are the only things standing
between a fork and the failure above.

It also exits early when `bootstrap.py` is already gone, so a second push cannot
bootstrap twice. Generating a repository does trigger it — the initial commit counts
as a push.

If it fails or you skipped it: **Actions → Bootstrap template → Run workflow**, or
run the script locally.

## Running the bootstrapper by hand

```bash
python bootstrap.py --dry-run     # print the plan, change nothing
python bootstrap.py               # do it
```

| Option | Effect |
| --- | --- |
| `--project NAME` | Project name. Default: the repository name. |
| `--owner NAME` | GitHub owner. Default: from the `origin` remote. |
| `--flavor SHAPE` | `full`, `pipeline`, `service` or `explore`. Default: `full`. |
| `--description "..."` | One-line description. |
| `--author "..."` / `--email "..."` | Default: `git config`. |
| `--keep-scaffolding` | Leave `bootstrap.py` and this file in place. |
| `--dry-run` | Print the plan and change nothing. |

Run locally with a `workflow`-scoped token and `bootstrap.yml` is deleted properly
rather than merely disabled.

---

## Two kinds of placeholder, and when to use which

This is the one thing to get right when adding content to the template.

### Tokens — `{{LIKE_THIS}}`

For prose: READMEs, docstrings, comments, YAML descriptions. Unambiguous, easy to
grep. `bootstrap.py` rewrites them across every text file.

| Token | Derived from | Example |
| --- | --- | --- |
| `{{PROJECT_NAME}}` | the repository name, as-is | `churn-predictor` |
| `{{PROJECT_TITLE}}` | the repository name, title-cased | `Churn Predictor` |
| `{{PROJECT_DESCRIPTION}}` | the GitHub repository description | `Predicts subscriber churn.` |
| `{{GITHUB_OWNER}}` | the repository owner | `priceshape-ai` |
| `{{GITHUB_REPO}}` | owner and repository | `priceshape-ai/churn-predictor` |
| `{{AUTHOR_NAME}}` | `git config user.name`, or the owner | `Thiva V` |
| `{{AUTHOR_EMAIL}}` | `git config user.email` | `thv@priceshape.dk` |
| `{{YEAR}}` | the current year | `2026` |

### Sentinels — the literal `project-name`

There is exactly one, for the places where the value must be **syntactically valid
before bootstrapping**: the distribution name in `pyproject.toml`, the Docker image
tag, the S3 paths in `.dvc/config`, the Kubernetes resource names,
`MLFLOW_EXPERIMENT`.

Why not a token there? Because `name = "{{PROJECT_NAME}}"` is not a valid package
name and `uv sync` refuses it. The sentinel keeps **the template itself installable,
testable and CI-green**, which is what makes it maintainable — you can run
`make check` on the template and get a real answer.

### The import package is always `core`

`src/core/` is not renamed and not substituted. Every project's code is
`from core.config import CONFIG`, so imports read identically everywhere, nothing in
`.github/workflows/` has to know a package name, and the reformatting step has no
import order to repair. The *distribution* still carries the project's real name —
that is what `project-name` becomes.

So: when you add a file inside the package, put it under `src/core/`, in the
template and in a generated project alike.

---

## Why `.github/workflows/` is special

GitHub refuses **any** push from `GITHUB_TOKEN` that creates, updates or deletes a
file under `.github/workflows/`, and no permission grants it:

```
! [remote rejected] HEAD -> main (refusing to allow a GitHub App to create or
  update workflow `.github/workflows/ci.yml` without `workflows` permission)
```

One rejected file rejects the whole push, so a bootstrap commit touching that
directory would fail and leave the new repository sitting on the raw template. Two
things prevent that, and both matter:

- **No workflow file contains a token or a sentinel.** `ci.yml` and `build.yml`
  discover the package and image names at run time instead
  (`package=$(ls src | head -1)`). Adding a `{{TOKEN}}` to anything under
  `.github/workflows/` breaks unattended bootstrapping.
- **`bootstrap.py` skips that directory entirely when `GITHUB_ACTIONS=true`**, so it
  never tries to delete `bootstrap.yml`. The workflow disables itself via the API.

---

## The engine lives here too

`priceshape-ml/` is the shared pipeline engine: the DAG, the runner, the git gate,
MLflow logging, the DVC sync and the Kubeflow backend. It is a **separate
distribution** — its own `pyproject.toml`, its own `uv.lock`, its own tests — whose
source happens to sit in this repository.

Projects consume it as a pinned git dependency, never as a path:

```toml
engine = [
    "priceshape-ml[tracking,kubeflow,data] @ git+ssh://git@github.com/priceshape-ai/data-and-ai-template@engine-v0.1.0#subdirectory=priceshape-ml",
]
```

### Why it is not a second repository

The engine and the template change together. Adding a field to a node's
configuration is an engine change *and* a template change; across two repositories
that is two pull requests and a window where `main` of one does not work with
`main` of the other. Here it is one commit, and one CI run covers both.

`docs/architecture.md` has the longer version, including the one rule this
arrangement depends on: **the engine must never import a project.**

### Generated projects do not keep it

**Use this template** copies the whole tree, so a generated repository briefly
contains `priceshape-ml/`. `bootstrap.py` removes it, along with the `engine-check`
make target, as part of scaffolding removal — a leftover copy would be an unpinned
second engine drifting from the one the lockfile installs, which is the exact
failure that left the two older projects with near-identical MLflow loggers that
had already diverged.

`.github/workflows/engine.yml` does survive, because nothing may delete a workflow
file during bootstrapping. It is inert there: a path filter nothing in a generated
project can match, plus a directory check covering the manual trigger.

### Changing the engine

```bash
make engine-check       # lint, format, types and tests, engine only
```

Then release it, and bump whoever should follow:

```bash
# 1. version bump in priceshape-ml/pyproject.toml, in the same commit as the change
# 2. tag it — engine-v* is the engine, plain v* is the template's image build
git tag -a engine-v0.2.0 -m "priceshape-ml 0.2.0 — what changed"
git push origin main engine-v0.2.0
# 3. in each consuming project: edit the `engine` group's tag, then
uv lock
```

Nothing moves under a project until someone does step 3. That is the point of the
pin — and `uv.lock` records the tag's commit, so the pin is a SHA in practice.

### `ENGINE_TOKEN`

This repository is private, and `GITHUB_TOKEN` is scoped to the repository that
calls it — so a *generated* project's CI cannot clone this one to fetch the engine.
`ci.yml` expects an organisation secret named `ENGINE_TOKEN`: a read-only token
that can clone `priceshape-ai/data-and-ai-template`. With it set, the workflow
rewrites `ssh://` to authenticated `https://`.

Without it the workflow falls back to `GITHUB_TOKEN`, which is enough **here** and
nowhere else: in this repository the engine source *is* the repository the job is
running in. So the template stays green with no secret to configure, and a
generated project fails with a notice naming the secret rather than an opaque
`Permission denied (publickey)`.

It sits alongside `OIDC_ROLE_ARN`, which `build.yml` needs for ECR. Neither is
stored in a repository.

Two things do **not** need it, and that is deliberate: a developer with a GitHub SSH
key (the URL is already `ssh://`), and the production image (`uv sync --no-dev`
selects no dependency group, so it never fetches the engine at all).

---

## Working on the template

Clone it directly; do not generate a repository from it.

```bash
git clone git@github.com:priceshape-ai/data-and-ai-template.git
cd data-and-ai-template
uv sync
make check                     # lint + import boundary + tests, on the template itself
python bootstrap.py --dry-run  # confirm the plan still looks right
```

A repository created with **Use this template** starts from a single commit and
shares no history with the template, so changes made in a generated repository
**cannot be opened as a pull request back here** — GitHub refuses the comparison.
Improvements belong in a branch of this repository.

Two rules for anything you add:

1. **Use the right placeholder** (see above).
2. **Ship it complete and runnable, not as a stub.** Whatever is here is what every
   generated project starts from. `make check` and `make docker-verify` must pass on
   the template, or the first thing a new project inherits is a broken build.

### Verifying a change to the template

```bash
make check            # lint, import boundary, tests — the template
make engine-check     # lint, types, tests — the bundled engine
make docker-verify    # build the image, assert no dev tooling got in
uv run pipeline --allow-dirty   # the example pipeline runs with no data present
```

`make docker-verify` is the one people skip and shouldn't: it is what proves the
prod/dev split still holds after a dependency moves.

And if you changed anything under `priceshape-ml/`, check what a *consumer* sees
before tagging — the engine is installed as a built wheel, not as this directory:

```bash
uv build --wheel priceshape-ml --out-dir /tmp/engine-dist
uv run --no-project --with /tmp/engine-dist/*.whl python -c "import priceshape_ml"
```
