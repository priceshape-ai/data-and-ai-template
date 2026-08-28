#!/usr/bin/env python3
"""PreToolUse hook: refuse edits that break the repository's architecture.

Wired to Write|Edit in `.claude/settings.json`. CLAUDE.md and `.claude/rules/` tell
Claude what the rules are; this makes the structural ones true regardless of what
any model decides, which is the distinction the Claude Code docs draw between
context and enforcement.

It only encodes rules that are **structural, statically decidable, and already have
a correct alternative** — every refusal below names what to do instead. Anything
needing judgement stays in the rules files, where it belongs.

Fails open. A malformed payload, an unreadable field, an unexpected exception:
exit 0 and let the edit through. A guard that blocks work when it is confused is
worse than no guard.

Test it by hand:

    echo '{"tool_name":"Write","tool_input":{"file_path":"main.py","content":""}}' \\
      | python3 .claude/hooks/architecture_guard.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Dev-only roots and the third-party packages that come with them. src/ importing
# any of these is what the import-linter contract forbids; this catches it earlier.
FORBIDDEN_IN_SRC = ("mlflow", "dvc", "streamlit", "kfp", "engine", "pipelines", "viz")

_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+(" + "|".join(FORBIDDEN_IN_SRC) + r")\b",
    re.MULTILINE,
)

# A credential with a literal default in a config dataclass is a credential headed
# for a commit. An empty string or a call like _env("X") is fine.
_SECRET_RE = re.compile(
    r"^\s*\w*(?:password|secret|token|api_key|access_key|credential)\w*\s*"
    r"(?::[^=]+)?=\s*[\"'][^\"']+[\"']",
    re.IGNORECASE | re.MULTILINE,
)

# Files that legitimately sit at the repository root despite being Python.
ROOT_PY_ALLOWED = {"bootstrap.py", "conftest.py", "noxfile.py", "setup.py"}

BANNED_FILENAMES = {
    "config.yaml": "Configuration is frozen dataclasses in src/*/config/hyperparameters.py. "
    "There is deliberately no config YAML, and tests/test_smoke.py fails if one appears.",
    "params.yaml": "Hyperparameters are code, not YAML — they live in "
    "src/*/config/hyperparameters.py so a commit fully determines a run.",
    "requirements.txt": "Dependencies live in pyproject.toml. Production is "
    "[project.dependencies]; everything else is a [dependency-groups] entry.",
    "requirements.local.txt": "Dependencies live in pyproject.toml, in "
    "[dependency-groups]. That is what replaced the two-requirements-files split.",
}


def deny(reason: str) -> None:
    """Refuse the edit and tell Claude exactly why, then exit cleanly."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def ask(reason: str) -> None:
    """Hand the decision to the human — for rules with legitimate exceptions."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def check(path_text: str, content: str) -> None:
    """Run every rule against one edit. Returns only if the edit is acceptable."""
    path = Path(path_text)
    parts = path.parts
    name = path.name

    # ── A new .py at the repository root ──────────────────────────────────────
    # The mistake this template exists to prevent: the reference project it was
    # drawn from grew eight top-level modules, and nothing told a newcomer which
    # of them production ran.
    if len(parts) == 1 and path.suffix == ".py" and name not in ROOT_PY_ALLOWED:
        deny(
            f"{name} would be a Python file at the repository root, and nothing goes "
            "there — the root is for configuration files only.\n\n"
            "Put it where it belongs instead:\n"
            "  production code        src/<package>/\n"
            "  a pipeline node        src/<package>/components/\n"
            "  the graph definition   pipelines/build.py\n"
            "  an operational script  scripts/\n\n"
            "Entry points are [project.scripts] in pyproject.toml pointing into a "
            "package, not files at the root."
        )

    # ── A file whose very name reintroduces a rejected design ─────────────────
    if name in BANNED_FILENAMES and len(parts) <= 2:
        deny(f"{name}: {BANNED_FILENAMES[name]}")

    # ── Anything git-trackable inside a DVC output ───────────────────────────
    if parts and parts[0] in (".data", ".models") and name == ".gitkeep":
        deny(
            f"A .gitkeep inside {parts[0]}/ breaks DVC outright: it refuses to "
            "manage a directory git tracks anything inside, so `dvc add "
            f"{parts[0]}` fails with \"output '{parts[0]}' is already tracked by "
            'SCM".\n\n'
            "The directory does not need preserving — `make dvc-pull` creates it."
        )

    # ── Hand-edited DVC pointers ─────────────────────────────────────────────
    if path.suffix == ".dvc":
        ask(
            f"{name} is a DVC pointer — hashes DVC computes, not text to edit. "
            "Hand-editing it detaches the pointer from the content it names.\n\n"
            "Use `make dvc-add` to re-hash after changing the tree, then "
            "`make dvc-push` before committing.\n\n"
            "Proceed only if you are deliberately repairing a corrupted pointer."
        )

    # ── Dev-only tooling reaching production ─────────────────────────────────
    if parts and parts[0] == "src":
        match = _IMPORT_RE.search(content)
        if match:
            offender = match.group(1)
            deny(
                f"`{match.group(0).strip()}` in {path_text} crosses the production "
                "boundary. src/ is what the wheel contains and what the container "
                f"runs, and {offender} is not installed there — this would fail at "
                "import time in the image, not here.\n\n"
                "Where it belongs instead:\n"
                "  mlflow      engine/tracking.py\n"
                "  kfp         engine/kubeflow/\n"
                "  streamlit   viz/\n"
                "  dvc         engine/dvc_sync.py, or a make target\n\n"
                "If production genuinely needs this behaviour, move the code into "
                "src/ rather than relaxing the boundary. `make imports` enforces the "
                "same contract."
            )

    # ── Production dependencies gaining weight ───────────────────────────────
    if name == "pyproject.toml":
        prod_block = content.split("[dependency-groups]")[0]
        if "dependencies = [" in prod_block:
            section = prod_block.split("dependencies = [", 1)[1].split("]", 1)[0]
            for package in ("mlflow", "dvc", "streamlit", "kfp"):
                if re.search(rf"[\"']{package}\b", section):
                    deny(
                        f"{package} is being added to [project.dependencies], which "
                        "is the production contract — it would be installed in the "
                        "serving image.\n\n"
                        "Put it in the matching [dependency-groups] entry instead. "
                        "Those are never installed by `pip install .` and never reach "
                        "the image. dvc alone pulls in around sixty packages the API "
                        "never calls."
                    )

    # ── Credentials with literal defaults ────────────────────────────────────
    if path.suffix == ".py" and "config" in parts:
        match = _SECRET_RE.search(content)
        if match:
            ask(
                f"{path_text} looks like it gives a credential a literal default:\n\n"
                f"    {match.group(0).strip()}\n\n"
                "Hyperparameters are code and get committed; credentials must not. "
                "Read it from the environment instead, and add the variable to "
                ".env.example with an empty value.\n\n"
                "Proceed only if that string is not actually a secret."
            )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # unreadable payload: fail open

    try:
        if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
            return 0

        tool_input = payload.get("tool_input") or {}
        file_path = tool_input.get("file_path") or ""
        if not file_path:
            return 0

        # Paths arrive absolute; the rules are all about position in the repo.
        project_dir = payload.get("cwd") or ""
        try:
            relative = str(Path(file_path).resolve().relative_to(Path(project_dir).resolve()))
        except (ValueError, OSError):
            relative = file_path

        # Write carries the whole file; Edit only the replacement text. Checking the
        # replacement is right: it is the text actually being introduced.
        content = tool_input.get("content") or tool_input.get("new_string") or ""
        if isinstance(tool_input.get("edits"), list):  # MultiEdit
            content = "\n".join(
                str(e.get("new_string", "")) for e in tool_input["edits"] if isinstance(e, dict)
            )

        check(relative, content if isinstance(content, str) else "")
    except SystemExit:
        raise
    except Exception:
        return 0  # any surprise: fail open
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
