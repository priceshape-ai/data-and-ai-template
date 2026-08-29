"""Refuse to run a pipeline that could not be reproduced afterwards.

Every MLflow run is tagged with a commit SHA. A SHA is only useful if the tree
actually matched it, so before doing any work the runner checks that the working
tree is clean and that the commit has been pushed — otherwise the run's recorded
provenance points at code nobody else can obtain.

Three conditions relax the gate, because in each case the check is either
impossible or meaningless:

- **No git repository.** Kubeflow pods, `docker build` and some CI checkouts have
  no `.git`. The gate cannot answer the question, so it steps aside rather than
  failing. (This is the one that matters most: a gate that hard-fails wherever it
  cannot run is a gate that stops production.)
- **`CI=true`.** CI checks out a specific commit by definition.
- **`--allow-dirty` / `PIPELINE_ALLOW_DIRTY=1`.** A deliberate scratch run. The
  run still happens; it is tagged `git.dirty=true` so the record is honest.

Unlike the version this was ported from, nothing is exempt from the dirty check.
Excluding the config directory sounds convenient, but the config *is* the
experiment — an uncommitted hyperparameter change is exactly the thing that makes
a SHA a lie.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class DirtyRepoError(RuntimeError):
    """The working tree is not in a state a run could be reproduced from."""


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False, cwd=cwd)


def is_git_repo(cwd: Path | None = None) -> bool:
    result = _git("rev-parse", "--git-dir", cwd=cwd)
    return result.returncode == 0


def git_metadata(cwd: Path | None = None) -> dict[str, str]:
    """Provenance tags for the MLflow run. Empty dict outside a repository.

    Git introspection lives here rather than in `priceshape_ml/tracking.py` so that the MLflow
    logger stays a pure function of its arguments — it records the tags it is
    handed and never shells out.
    """
    if not is_git_repo(cwd):
        return {}

    commit = _git("rev-parse", "HEAD", cwd=cwd)
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    status = _git("status", "--porcelain", cwd=cwd)

    meta = {"git.dirty": "true" if status.stdout.strip() else "false"}
    if commit.returncode == 0:
        meta["git.commit"] = commit.stdout.strip()
    if branch.returncode == 0:
        meta["git.branch"] = branch.stdout.strip()
    return meta


def check_clean(allow_dirty: bool = False, cwd: Path | None = None) -> None:
    """Raise `DirtyRepoError` unless this tree could reproduce a run.

    Args:
        allow_dirty: Skip the checks. Combined with `PIPELINE_ALLOW_DIRTY`.
        cwd: Directory to inspect. Defaults to the current one.

    Raises:
        DirtyRepoError: With a message naming exactly what to do about it.
    """
    if allow_dirty or os.getenv("PIPELINE_ALLOW_DIRTY") == "1":
        logger.warning(
            "Git gate skipped — this run will be tagged git.dirty and is not "
            "reproducible from its commit."
        )
        return

    if os.getenv("CI") == "true":
        logger.info("Git gate skipped: CI already runs from a fixed commit.")
        return

    if not is_git_repo(cwd):
        logger.info("Git gate skipped: not a git repository.")
        return

    status = _git("status", "--porcelain", cwd=cwd)
    if status.stdout.strip():
        raise DirtyRepoError(
            "Uncommitted changes. Commit or stash them, or pass --allow-dirty:\n"
            + status.stdout.rstrip()
        )

    upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", cwd=cwd)
    if upstream.returncode != 0:
        branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd).stdout.strip()
        raise DirtyRepoError(
            f"Branch {branch!r} has no upstream, so its commit is only on this "
            f"machine. Push it first:\n    git push -u origin {branch}"
        )

    ahead = _git("log", "@{u}..HEAD", "--oneline", cwd=cwd)
    if ahead.stdout.strip():
        raise DirtyRepoError(
            "Unpushed commits — push before running so the recorded SHA is "
            "fetchable:\n" + ahead.stdout.rstrip()
        )
