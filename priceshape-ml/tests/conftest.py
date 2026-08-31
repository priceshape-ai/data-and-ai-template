"""Shared fixtures."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# The engine reads exactly these attributes off whatever config it is handed. This
# stub is the contract, written down: if the engine ever reaches for something
# else, these tests fail rather than silently depending on a real project.


@dataclass(frozen=True)
class Paths:
    data_root: Path = Path(".data")
    models_root: Path = Path(".models")
    runs_root: Path = Path("runs")
    dag_cache: Path = Path(".dag_cache")


@dataclass(frozen=True)
class Mlflow:
    tracking_uri: str = ""
    experiment: str = "test"

    @property
    def enabled(self) -> bool:
        return bool(self.tracking_uri)


# Nested one level deeper than the rest on purpose: flatten_config has to reach
# through a node's sub-dataclass to produce `featurizer.tokenizer.max_length`, and
# a stub with no nesting would not notice if it stopped.
@dataclass(frozen=True)
class Tokenizer:
    max_length: int = 512
    truncation: bool = True


@dataclass(frozen=True)
class Featurizer:
    model_name: str = "BAAI/bge-m3"
    batch_size: int = 32
    tokenizer: Tokenizer = field(default_factory=Tokenizer)


@dataclass(frozen=True)
class Scorer:
    threshold: float = 0.5


@dataclass(frozen=True)
class StubConfig:
    """What a project's CONFIG looks like from the engine's side of the line."""

    log_level: str = "INFO"
    paths: Paths = field(default_factory=Paths)
    mlflow: Mlflow = field(default_factory=Mlflow)
    featurizer: Featurizer = field(default_factory=Featurizer)
    scorer: Scorer = field(default_factory=Scorer)


@dataclass
class NodeResult:
    """A concrete stand-in for whatever a real project returns from a node."""

    items: list = field(default_factory=list)
    test_items: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def splits(self) -> dict:
        out = {}
        if self.items:
            out["items"] = self.items
        if self.test_items:
            out["test"] = self.test_items
        return out


@pytest.fixture
def config() -> StubConfig:
    return StubConfig()


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
