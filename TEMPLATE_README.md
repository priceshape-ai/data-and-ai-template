# data-and-ai-template

The standard starting point for PriceShape Data, Data Science and AI/ML repositories.
MLflow, DVC on S3, a DAG-based pipeline that runs locally or on Kubeflow, a FastAPI
service, and a hard separation between what production runs and what development
needs.

> **This file documents the template itself.** `bootstrap.py` deletes it from
> generated repositories, along with itself, so a new project keeps only its own
> `README.md`.

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
uv sync
cp .env.example .env
uv run pytest
```

## What happens on the first push

`.github/workflows/bootstrap.yml` runs `bootstrap.py`, which:

1. Substitutes every token and sentinel, deriving the values from the repository
   name, owner and description.
2. Renames `src/project_name/` to `src/<your_package>/`.
3. Validates the result — every rewritten `.py` still parses, no token or sentinel
   survives, the package directory exists. If anything fails it leaves
   `bootstrap.py` in place and exits non-zero, so CI does not commit a broken tree.
4. Commits, deletes `bootstrap.py` and `TEMPLATE_README.md`, and disables itself.

It is guarded by `if: github.event.repository.is_template == false`, so it never
rewrites the template, and it exits early when `bootstrap.py` is already gone, so a
second push cannot bootstrap twice. Generating a repository does trigger it — the
initial commit counts as a push.

If it fails or you skipped it: **Actions → Bootstrap template → Run workflow**, or
run the script locally.

## Running the bootstrapper by hand

```bash
python bootstrap.py --dry-run     # print the plan, change nothing
python bootstrap.py              # do it
```

| Option | Effect |
| --- | --- |
| `--project NAME` | Project name. Default: the repository name. |
| `--package NAME` | Python package name. Default: derived from the project name. |
| `--owner NAME` | GitHub owner. Default: from the `origin` remote. |
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
| `{{PACKAGE_NAME}}` | the repository name, made importable | `churn_predictor` |
| `{{PROJECT_TITLE}}` | the repository name, title-cased | `Churn Predictor` |
| `{{PROJECT_DESCRIPTION}}` | the GitHub repository description | `Predicts subscriber churn.` |
| `{{GITHUB_OWNER}}` | the repository owner | `priceshape-ai` |
| `{{GITHUB_REPO}}` | owner and repository | `priceshape-ai/churn-predictor` |
| `{{AUTHOR_NAME}}` | `git config user.name`, or the owner | `Thiva V` |
| `{{AUTHOR_EMAIL}}` | `git config user.email` | `thv@priceshape.dk` |
| `{{YEAR}}` | the current year | `2026` |

### Sentinels — the literal `project_name` and `project-name`

For anywhere the value must be **syntactically valid before bootstrapping**:

- `project-name` — the distribution name in `pyproject.toml`, the Docker image tag,
  the S3 paths in `.dvc/config`, the Kubernetes resource names, `MLFLOW_EXPERIMENT`.
- `project_name` — the package directory, every `import` statement, the Makefile's
  `PACKAGE` variable, `[tool.hatch.build.targets.wheel] packages`.

Why not tokens everywhere? Because `name = "{{PROJECT_NAME}}"` is not a valid
package name and `uv sync` refuses it. Sentinels keep **the template itself
installable, testable and CI-green**, which is what makes it maintainable — you can
run `make check` on the template and get a real answer.

So: when you add a file *inside* the package, put it under `src/project_name/`.
When you *write about* the package, use `{{PACKAGE_NAME}}`.

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
make check            # lint, import boundary, tests
make docker-verify    # build the image, assert no dev tooling got in
uv run pipeline --allow-dirty   # the example pipeline runs with no data present
```

`make docker-verify` is the one people skip and shouldn't: it is what proves the
prod/dev split still holds after a dependency moves.
