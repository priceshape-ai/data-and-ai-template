"""Structural checks: the layout and the import boundary are what they claim.

`test_dev_roots_are_importable` is the one that earns its keep — it is what proves
`dev-mode-dirs` in pyproject.toml is doing its job. Without that setting, the dev
roots outside src/ are silently unimportable and `uv run pipeline` fails with
ModuleNotFoundError.
"""

from __future__ import annotations

import importlib

import pytest


def test_package_imports() -> None:
    import core

    assert core.__version__


def test_config_singleton() -> None:
    from core.config import CONFIG

    assert CONFIG.environment
    assert CONFIG.paths.data_root.name == ".data"


@pytest.mark.parametrize(
    "module",
    [
        "pipelines.build",
        "pipelines.runner",
        "priceshape_ml",
    ],
)
def test_dev_roots_are_importable(module: str) -> None:
    """Proves `dev-mode-dirs = [".", "src"]` puts the repo root on sys.path."""
    assert importlib.import_module(module) is not None


@pytest.mark.parametrize(
    "directory",
    ["src", "pipelines", "tests", "docker", "docs"],
)
def test_expected_directories_exist(project_root, directory: str) -> None:
    """The parts every shape keeps. `viz/` and `deploy/` are shape-dependent."""
    assert (project_root / directory).is_dir(), f"missing directory: {directory}"


@pytest.mark.parametrize(
    "file",
    [
        "pyproject.toml",
        "README.md",
        "TEMPLATE_GUIDE.md",
        "CLAUDE.md",
        ".claude/settings.json",
        ".claude/hooks/architecture_guard.py",
        "Makefile",
        ".env.example",
        ".dvcignore",
        ".dockerignore",
        "pipelines/runner.py",
        "docker/Dockerfile",
    ],
)
def test_expected_files_exist(project_root, file: str) -> None:
    assert (project_root / file).is_file(), f"missing file: {file}"


def test_no_config_yaml(project_root) -> None:
    """Config is frozen dataclasses only; a stray YAML means two sources of truth."""
    for stray in ("configs/config.yaml", "params.yaml", "config.yaml"):
        assert not (project_root / stray).exists(), (
            f"{stray} is back — config belongs in the config package, as dataclasses"
        )


def test_data_dirs_are_not_git_tracked(project_root) -> None:
    """DVC refuses to manage a directory git tracks anything inside.

    `dvc add .data` fails with "output '.data' is already tracked by SCM" if even a
    .gitkeep is committed there, so this guards against someone re-adding a
    placeholder to make the layout visible.
    """
    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "--", ".data", ".models"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    tracked = result.stdout.strip()
    assert not tracked, (
        "git is tracking files inside a DVC output, which breaks `dvc add`:\n"
        f"{tracked}\nRemove them with: git rm -r --cached .data .models"
    )
