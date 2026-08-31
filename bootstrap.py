#!/usr/bin/env python3
"""Turn this template into a named project. Runs once, then deletes itself.

`.github/workflows/bootstrap.yml` calls this on the first push to a repository
generated from the template, so normally nobody runs it by hand. To do it
manually:

    python bootstrap.py --dry-run     # show the plan
    python bootstrap.py               # do it

With no arguments it derives everything: the project name from the `origin`
remote (or the directory name), the package name from that, the author from
`git config`, and the year from today.

There are two kinds of substitution, and the difference matters when you add files
to the template:

**Tokens** — `{{PROJECT_NAME}}` and friends. Use these in prose: READMEs, docstrings,
comments, YAML descriptions. They are unambiguous and easy to grep for.

**Sentinels** — the literal strings `core` and `project-name`. Use these
wherever the value has to be syntactically valid *before* bootstrapping:
`pyproject.toml`'s distribution name, the package directory, import statements,
Makefile variables, S3 paths. This is what keeps the template itself installable
and its own CI green — a `name = "{{PROJECT_NAME}}"` in pyproject.toml would be an
invalid package name and `uv sync` would refuse it.

So: inside the package, add files under `src/core/`; when writing *about*
the package, use `core`.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Deleted once bootstrapping succeeds — they only exist to bootstrap.
SCAFFOLDING = ("bootstrap.py", "TEMPLATE_README.md")

# Directories that belong to the template repository and must not survive into a
# generated project. `priceshape-ml/` is the shared engine's source: it lives here
# so that a fix and the template change that needs it land in one commit, but a
# project consumes it as a pinned dependency (see the `engine` group in
# pyproject.toml). Leaving a copy behind would recreate exactly the drift this
# arrangement exists to prevent — two near-identical engines, silently diverging.
TEMPLATE_ONLY_DIRS = ("priceshape-ml",)

# Make targets that only make sense while the engine source is present.
TEMPLATE_ONLY_TARGETS = ("engine-check",)

# Never walked into.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".dag_cache",
        "node_modules",
        ".data",
        ".models",
        "runs",
        "mlruns",
        # The bundled engine is a separate distribution with its own history and
        # its own name. Substituting this project's sentinels into it would
        # rewrite `priceshape_ml` imports; it is removed wholesale instead.
        "priceshape-ml",
    }
)

# Rewriting a wheel or a PNG would corrupt it. Text detection also guards this,
# but an explicit list is cheaper and clearer.
SKIP_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".svg",
        ".pdf",
        ".whl",
        ".zip",
        ".gz",
        ".tar",
        ".bz2",
        ".xz",
        ".pkl",
        ".pickle",
        ".joblib",
        ".parquet",
        ".arrow",
        ".pt",
        ".pth",
        ".onnx",
        ".safetensors",
        ".so",
        ".dylib",
        ".pyc",
    }
)

# Bootstrapping the template itself is destructive and near-irrecoverable: it
# substitutes every token, removes the engine source and deletes this script,
# leaving no way to generate a correctly-named project again. The workflow guards against it
# too, but this catches a local `python bootstrap.py` run in a template checkout.
TEMPLATE_PROJECT_NAMES = frozenset({"data-and-ai-template", "ml-project-template"})

PROJECT_SENTINEL = "project-name"


# ── shapes ───────────────────────────────────────────────────────────────────
# Not every project needs all six tools. A shape removes the edges it will not
# use; the DAG, config, data versioning and run logging are in every one of them,
# because those are what make a project reproducible rather than optional extras.
#
# validate() re-walks every surviving import after pruning, so a shape that cuts
# something still referenced fails loudly here rather than at someone's first run.

PARTS: dict[str, dict[str, list[str]]] = {
    "serving": {
        "paths": ["src/core/serving", "deploy", "tests/integration/test_api.py"],
        "deps": ["fastapi", "uvicorn"],
        "targets": ["serve", "docker-run"],
    },
    "viz": {
        "paths": ["viz", "tests/unit/test_viz.py"],
        "groups": ["viz"],
        "targets": ["viz"],
        # import-linter resolves every root package it is given, so a pruned root
        # left in the config fails the whole check with "Could not find package".
        "roots": ["viz"],
        "modules": ["viz", "streamlit"],
    },
    "kubeflow": {
        # The backend lives in priceshape-ml now, so pruning it means dropping the
        # extra rather than deleting files.
        "extras": ["kubeflow"],
        "groups": ["orchestration"],
        "modules": ["kfp"],
    },
}

FLAVORS: dict[str, tuple[tuple[str, ...], str]] = {
    "full": ((), "everything: a graph, a served model, the cluster backend, the explorer"),
    "pipeline": (("serving",), "a batch pipeline — no HTTP service to deploy"),
    "service": (("viz", "kubeflow"), "a served model or language-model product — no cluster runs"),
    "explore": (("serving", "kubeflow"), "analysis and notebooks — nothing deployed"),
}


def prune(flavor: str, dry_run: bool) -> list[str]:
    """Remove the parts this shape does not use. Returns what went."""
    removed: list[str] = []
    for part in FLAVORS[flavor][0]:
        spec = PARTS[part]
        for rel in spec.get("paths", []):
            path = ROOT / rel
            if not path.exists():
                continue
            removed.append(rel)
            if dry_run:
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        if not dry_run:
            _drop_dependencies(spec.get("deps", []), spec.get("groups", []))
            _drop_targets(spec.get("targets", []))
            _drop_from_checks(spec.get("roots", []), spec.get("modules", []))
    return removed


def _drop_dependencies(deps: list[str], groups: list[str]) -> None:
    """Take the packages and dependency groups a pruned part needed out of pyproject."""
    path = ROOT / "pyproject.toml"
    lines = path.read_text().splitlines()
    out, skipping = [], False
    for line in lines:
        stripped = line.strip()
        if skipping:
            if stripped.startswith("]"):
                skipping = False
            continue
        if any(stripped.startswith(f"{g} = [") for g in groups):
            skipping = not stripped.endswith("]")
            if not skipping:
                continue
            continue
        if any(stripped.startswith(f'"{d}') for d in deps):
            continue
        # A pruned group must also stop being included by the umbrella dev group.
        if any(f'include-group = "{g}"' in stripped for g in groups):
            continue
        out.append(line)
    path.write_text("\n".join(out) + "\n")


def _drop_from_checks(roots: list[str], modules: list[str]) -> None:
    """Take a pruned root out of the import-linter and ruff configuration.

    import-linter resolves every name in `root_packages`, so one that no longer
    exists fails the whole check with "Could not find package" rather than being
    skipped. The forbidden-module lists are cosmetic once the package is gone, but
    leaving them invites someone to re-add the dependency and wonder why nothing
    complains.
    """
    names = set(roots) | set(modules)
    if not names:
        return

    path = ROOT / "pyproject.toml"
    kept: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip().rstrip(",")
        # A list member on its own line: drop the line entirely.
        if stripped[1:-1] in names and stripped[:1] in {'"', "'"}:
            continue
        # A member of an inline list: remove just that element.
        for name in names:
            line = re.sub(rf'"{re.escape(name)}",\s*', "", line)
            line = re.sub(rf',\s*"{re.escape(name)}"', "", line)
        kept.append(line)
    path.write_text("\n".join(kept) + "\n")


def _drop_targets(targets: list[str]) -> None:
    """Remove make targets whose command no longer exists."""
    if not targets:
        return
    path = ROOT / "Makefile"
    lines = path.read_text().splitlines()
    out, skipping = [], False
    for line in lines:
        if skipping:
            if line.strip() == "":
                skipping = False
                continue
            if line.startswith("\t") or line.startswith("#"):
                continue
            skipping = False
        if any(line.startswith(f"{t}:") for t in targets):
            skipping = True
            continue
        out.append(line)
    text = "\n".join(out) + "\n"
    for target in targets:
        text = text.replace(f" {target} ", " ").replace(f" {target}\n", "\n")
    path.write_text(text)


# ── deriving the values ───────────────────────────────────────────────────────


def git_output(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def detect_repo() -> tuple[str, str]:
    """Return `(owner, repo)` from the origin remote, falling back to the directory."""
    url = git_output("config", "--get", "remote.origin.url")
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url)
    if match:
        return match.group(1), match.group(2)
    return "priceshape-ai", ROOT.name


def to_title(project: str) -> str:
    """`churn-predictor` -> `Churn Predictor`."""
    return " ".join(word.capitalize() for word in re.split(r"[-_\s]+", project) if word)


def build_context(args: argparse.Namespace) -> dict[str, str]:
    owner, repo = detect_repo()
    owner = args.owner or owner
    project = args.project or repo

    if project in TEMPLATE_PROJECT_NAMES:
        sys.exit(
            f"Refusing to bootstrap '{project}': that is the template itself.\n"
            "Bootstrapping it would substitute every token, prune to one shape and\n"
            "delete this script, leaving nothing that can generate a project again.\n"
            "Generate a repository from the template first, then run this there — or\n"
            "pass --project <other-name> to bootstrap this checkout under a\n"
            "different name.\n"
            "See TEMPLATE_README.md, 'Working on the template itself'."
        )
    title = to_title(project)

    return {
        "PROJECT_NAME": project,
        "PROJECT_TITLE": title,
        "PROJECT_DESCRIPTION": args.description or f"{title} — a PriceShape Data & AI project.",
        "GITHUB_OWNER": owner,
        "GITHUB_REPO": f"{owner}/{project}",
        "AUTHOR_NAME": args.author or git_output("config", "user.name") or owner,
        "AUTHOR_EMAIL": args.email
        or git_output("config", "user.email")
        or f"{owner}@users.noreply.github.com",
        "YEAR": str(datetime.date.today().year),
    }


# ── rewriting ─────────────────────────────────────────────────────────────────


def in_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def walk_files() -> list[Path]:
    """Every candidate file for rewriting, in a stable order."""
    found: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        found.append(path)
    return found


def should_skip_workflow(path: Path) -> bool:
    """True for `.github/workflows/*` while running inside Actions.

    GitHub rejects any push from GITHUB_TOKEN that creates, updates or deletes a
    file under `.github/workflows/`, and there is no permission that grants it.
    One rejected file rejects the *whole* push, so a bootstrap commit that touched
    that directory would fail and leave the new repository sitting on the raw
    template. Hence: no tokens in any workflow file, and no rewrites here in CI.
    Running locally with a `workflow`-scoped token, this restriction does not apply.
    """
    if not in_actions():
        return False
    parts = path.relative_to(ROOT).parts
    return len(parts) >= 2 and parts[0] == ".github" and parts[1] == "workflows"


def substitute(text: str, context: dict[str, str]) -> str:
    for key, value in context.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    # The sentinel last, so a token expanding to something containing
    # "project-name" is not then re-substituted.
    return text.replace(PROJECT_SENTINEL, context["PROJECT_NAME"])


def rewrite_files(context: dict[str, str], dry_run: bool) -> list[Path]:
    changed: list[Path] = []
    for path in walk_files():
        # Never rewrite the scaffolding: this file must not change mid-run, and
        # TEMPLATE_README.md documents the sentinels literally, so substituting
        # them there would mangle the very text that explains them.
        if path.name in SCAFFOLDING:
            continue
        if should_skip_workflow(path):
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable
        updated = substitute(original, context)
        if updated != original:
            changed.append(path)
            if not dry_run:
                path.write_text(updated, encoding="utf-8")
    return changed


def _ruff_command() -> list[str] | None:
    """Find a runnable ruff, or None.

    Tried in order of how likely it is to be present: the interpreter running this
    script, PATH, then uv's ephemeral-tool runner.
    """
    candidates = [
        [sys.executable, "-m", "ruff"],
        ["ruff"],
        ["uv", "run", "ruff"],
        ["uvx", "ruff"],
    ]
    for command in candidates:
        # check=False suppresses a non-zero exit, not a missing executable: probing
        # a command that is not installed raises FileNotFoundError. Unhandled, that
        # crashed bootstrap.py *after* it had rewritten every file, leaving a
        # half-bootstrapped tree on any machine without a global ruff.
        try:
            probe = subprocess.run(
                [*command, "--version"], capture_output=True, text=True, check=False
            )
        except OSError:
            continue
        if probe.returncode == 0:
            return command
    return None


def format_code(dry_run: bool) -> bool:
    """Re-sort imports and reformat after substitution.

    Renaming the package changes where its imports sort: `churn_predictor` comes
    before `pipelines`, where `core` came after. Every module importing both
    is left with an unsorted import block, so a generated project would start life
    with a red `ruff check` — the worst possible first impression of the template.
    Fixing it here is what makes `make check` pass on a fresh generated repository.
    """
    if dry_run:
        return True
    command = _ruff_command()
    if command is None:
        print(
            "  ruff not found — skipping the import re-sort. Run `uv run ruff check "
            "--fix . && uv run ruff format .` once you have synced.",
            file=sys.stderr,
        )
        return False
    subprocess.run([*command, "check", "--fix", "--quiet", "."], cwd=ROOT, check=False)
    subprocess.run([*command, "format", "--quiet", "."], cwd=ROOT, check=False)
    return True


def lint_problems() -> list[str]:
    """Whatever `ruff check` still reports after the reformat.

    The template is lint-clean by construction, so anything here was *caused* by
    substitution — and not everything is auto-fixable. The case that motivated this:
    a longer package name pushes a line past the limit, and `ruff format` cannot
    split a string literal, so the generated project starts with a failing
    `ruff check`. Catching it here means the bootstrapper refuses rather than
    handing someone a red repository.
    """
    command = _ruff_command()
    if command is None:
        return []
    result = subprocess.run(
        [*command, "check", "--output-format", "concise", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return []
    return [
        f"ruff: {line.strip()}"
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("Found ")
    ]


def remove_scaffolding(dry_run: bool) -> list[Path]:
    removed: list[Path] = []
    for name in SCAFFOLDING:
        path = ROOT / name
        if path.exists():
            removed.append(path)
            if not dry_run:
                path.unlink()

    for name in TEMPLATE_ONLY_DIRS:
        path = ROOT / name
        if path.is_dir():
            removed.append(path)
            if not dry_run:
                shutil.rmtree(path)
                # The make targets that drove it would now point at nothing.
                _drop_targets(list(TEMPLATE_ONLY_TARGETS))

    # The bootstrap workflow disables itself through the API rather than being
    # deleted here — see should_skip_workflow() for why a delete would be rejected.
    workflow = ROOT / ".github" / "workflows" / "bootstrap.yml"
    if workflow.exists() and not in_actions():
        removed.append(workflow)
        if not dry_run:
            workflow.unlink()
    return removed


# ── validation ────────────────────────────────────────────────────────────────


def validate(context: dict[str, str]) -> list[str]:
    """Check the rewritten tree before anything is committed.

    Returns a list of problems. A non-empty list means the caller should leave
    `bootstrap.py` in place and exit non-zero, so CI does not commit a broken tree.
    """
    problems: list[str] = []

    package_dir = ROOT / "src" / "core"
    if not (package_dir / "__init__.py").is_file():
        problems.append(f"package not found: {package_dir}/__init__.py")

    for path in walk_files():
        if path.name in SCAFFOLDING or should_skip_workflow(path):
            continue  # about to be deleted, or deliberately left alone
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        relative = path.relative_to(ROOT)
        for leftover in re.findall(r"\{\{[A-Z_]+\}\}", text):
            problems.append(f"{relative}: unsubstituted token {leftover}")
        if PROJECT_SENTINEL in text:
            problems.append(f"{relative}: leftover sentinel")

        if path.suffix == ".py":
            try:
                ast.parse(text, filename=str(path))
            except SyntaxError as exc:
                problems.append(f"{relative}: syntax error after rewrite: {exc}")

    return problems


# ── entrypoint ────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--flavor",
        choices=sorted(FLAVORS),
        default=os.environ.get("TEMPLATE_FLAVOR", "full"),
        help="Which shape to keep: " + "; ".join(f"{k} ({v[1]})" for k, v in FLAVORS.items()),
    )
    parser.add_argument("--project", help="Project name (default: the repository name)")
    parser.add_argument("--owner", help="GitHub owner (default: from the origin remote)")
    parser.add_argument("--description", help="One-line project description")
    parser.add_argument("--author", help="Author name (default: git config user.name)")
    parser.add_argument("--email", help="Author email (default: git config user.email)")
    parser.add_argument(
        "--keep-scaffolding",
        action="store_true",
        help="Leave bootstrap.py and TEMPLATE_README.md in place.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and change nothing.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    context = build_context(args)

    print("Bootstrapping with:")
    for key, value in context.items():
        print(f"  {key:22} {value}")
    print()

    changed = rewrite_files(context, args.dry_run)
    verb = "Would rewrite" if args.dry_run else "Rewrote"
    print(f"{verb} {len(changed)} file(s).")

    dropped = prune(args.flavor, args.dry_run)
    verb = "Would keep" if args.dry_run else "Keeping"
    print(f"{verb} the '{args.flavor}' shape — {FLAVORS[args.flavor][1]}.")
    if dropped:
        verb = "Would remove" if args.dry_run else "Removed"
        print(f"  {verb}: {', '.join(dropped)}")

    if args.dry_run:
        print("\nDry run — nothing changed.")
        return 0

    problems = validate(context)
    if format_code(dry_run=False):
        print("Re-sorted imports and reformatted.")
        problems += lint_problems()
    if problems:
        print("\nBootstrap produced a broken tree, so nothing was cleaned up:", file=sys.stderr)
        for problem in problems[:40]:
            print(f"  - {problem}", file=sys.stderr)
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more", file=sys.stderr)
        return 1

    if not args.keep_scaffolding:
        for path in remove_scaffolding(dry_run=False):
            print(f"Removed {path.relative_to(ROOT)}")

    print(
        "\nDone. Next:"
        "\n  cp .env.example .env"
        "\n  $EDITOR .env                 # AWS_PROFILE at least"
        "\n  set -a; source .env; set +a"
        "\n  uv sync"
        "\n  make dvc-pull"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
