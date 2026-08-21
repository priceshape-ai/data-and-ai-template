"""Shared fixtures."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from project_name.config import PROJECT_ROOT


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """An initialised repository with one commit and no remote.

    Used by the git-gate tests. Identity is set locally so the fixture works on a
    machine with no global git config, such as a CI runner.
    """

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True)

    run("init", "-b", "main")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    (tmp_path / "README.md").write_text("initial\n")
    run("add", "README.md")
    run("commit", "-m", "initial")
    return tmp_path


@pytest.fixture
def pushed_repo(git_repo: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`git_repo` with an upstream, so the gate's push checks have something to check.

    The bare remote is created through `tmp_path_factory` so it lands *beside*
    the repository rather than inside it — a remote in the working tree shows up
    as an untracked directory and the tree is no longer clean.
    """
    remote = tmp_path_factory.mktemp("remote") / "origin.git"

    def run(*args: str, cwd: Path = git_repo) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

    run("init", "--bare", str(remote))
    run("remote", "add", "origin", str(remote))
    run("push", "-u", "origin", "main")
    return git_repo
