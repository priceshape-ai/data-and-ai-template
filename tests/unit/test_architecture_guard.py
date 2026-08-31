"""The Claude Code architecture hook is enforcement, so it gets tested like code.

A guard nobody tests rots in one of two directions, and both are bad: it stops
catching what it was written for, or it starts blocking legitimate work and gets
switched off. The allow cases below matter at least as much as the deny cases.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "architecture_guard.py"
ROOT = GUARD.parents[2]


def decide(file_path: str, content: str, tool: str = "Write") -> str:
    """Run the hook over one edit and return "allow", "deny" or "ask"."""
    key = "content" if tool == "Write" else "new_string"
    payload = {
        "tool_name": tool,
        "cwd": str(ROOT),
        "tool_input": {"file_path": str(ROOT / file_path), key: content},
    }
    result = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"the hook must always exit 0, got {result.returncode}"
    if not result.stdout.strip():
        return "allow"
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("main.py", "x = 1\n"),
        ("app.py", "x = 1\n"),
        ("params.yaml", "seed: 42\n"),
        ("config.yaml", "paths: {}\n"),
        ("requirements.txt", "numpy\n"),
        (".data/raw/.gitkeep", ""),
        (".models/.gitkeep", ""),
        ("src/core/components/scorer.py", "import mlflow\n"),
        ("src/core/serving/app.py", "from priceshape_ml import DAG\n"),
        ("src/core/serving/app.py", "from pipelines.build import build_pipeline\n"),
        ("src/core/data/loader.py", "import dvc.api\n"),
        ("pyproject.toml", 'dependencies = [\n  "streamlit",\n]\n[dependency-groups]\n'),
    ],
)
def test_structural_violations_are_denied(path: str, content: str) -> None:
    assert decide(path, content) == "deny", f"{path} should have been refused"


@pytest.mark.parametrize(
    ("path", "content"),
    [
        # Dev-only tooling in the roots that exist to hold it.
        ("viz/app.py", "import streamlit as st\n"),
        ("tests/unit/test_tracking_contract.py", "import mlflow\n"),
        ("pipelines/build.py", "from priceshape_ml import DAG\n"),
        ("pipelines/runner.py", "from priceshape_ml import run\n"),
        # Ordinary production code.
        ("src/core/components/ranker.py", "import numpy as np\n"),
        # Prose that merely mentions a forbidden package.
        ("src/core/config/hyperparameters.py", '"""viz/ imports mlflow."""\n'),
        ("src/core/config/hyperparameters.py", "class MlflowConfig:\n    uri: str\n"),
        # The correct way to declare a credential: empty, filled from the env.
        ("src/core/config/hyperparameters.py", '    api_key: str = ""\n'),
        # Root files that belong at the root.
        ("bootstrap.py", "x = 1\n"),
        ("docs/notes.md", "import mlflow everywhere\n"),
        # A dependency group is the right home for dev tooling.
        (
            "pyproject.toml",
            'dependencies = [\n  "pydantic",\n]\n[dependency-groups]\nt = ["mlflow"]\n',
        ),
    ],
)
def test_legitimate_edits_are_allowed(path: str, content: str) -> None:
    assert decide(path, content) == "allow", f"{path} should NOT have been blocked"


@pytest.mark.parametrize(
    ("path", "content"),
    [
        (".data.dvc", "outs:\n- md5: abc\n"),
        ("src/core/config/hyperparameters.py", '    api_key: str = "sk-live-abc"\n'),
    ],
)
def test_judgement_calls_ask_rather_than_block(path: str, content: str) -> None:
    """Rules with legitimate exceptions defer to the human instead of refusing."""
    assert decide(path, content) == "ask"


def test_edit_payloads_are_understood() -> None:
    """Edit carries new_string rather than content; both shapes must be read."""
    assert decide("src/core/components/x.py", "import mlflow\n", tool="Edit") == "deny"


def test_malformed_payload_fails_open() -> None:
    """A confused guard must let work through, never block it."""
    result = subprocess.run(
        [sys.executable, str(GUARD)], input="not json", capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0
    assert not result.stdout.strip()


def test_every_refusal_names_an_alternative() -> None:
    """A refusal that does not say what to do instead is a dead end."""
    payload = {
        "tool_name": "Write",
        "cwd": str(ROOT),
        "tool_input": {"file_path": str(ROOT / "main.py"), "content": ""},
    }
    result = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )
    reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "instead" in reason.lower()
    assert len(reason) > 120, "a one-line refusal does not teach the rule"
