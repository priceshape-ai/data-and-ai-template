"""Project root discovery.

Resolves the project root by walking up for a marker, so paths behave the same
from a notebook, a pytest run, a CLI invocation and a container.
"""

from __future__ import annotations

import os
from pathlib import Path

# pyproject.toml is present in a source checkout; .git covers the case where the
# working directory is a subdirectory of one. In the production image neither
# exists, which is why PROJECT_ROOT falls back to the environment variable the
# Dockerfile sets.
_MARKERS = ("pyproject.toml", ".git")


def discover_project_root(start: Path | None = None) -> Path:
    """Walk up from `start` (default: cwd) to the first directory holding a marker."""
    if from_env := os.getenv("PROJECT_ROOT"):
        return Path(from_env)

    origin = Path(start) if start else Path.cwd()
    for candidate in (origin, *origin.parents):
        if any((candidate / marker).exists() for marker in _MARKERS):
            return candidate
    return origin


PROJECT_ROOT: Path = discover_project_root()
