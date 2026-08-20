"""Tests for the reproducibility gate.

The most important case is `test_passes_outside_a_git_repo`: the gate must step
aside where it cannot answer, because Kubeflow pods and Docker builds have no
`.git` and a gate that hard-fails there is a gate that stops production.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pipelines.gitgate import DirtyRepoError, check_clean, git_metadata, is_git_repo


def _run(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither CI nor a developer's escape hatch should leak into these tests."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PIPELINE_ALLOW_DIRTY", raising=False)


class TestIsGitRepo:
    def test_true_inside_a_repo(self, git_repo: Path) -> None:
        assert is_git_repo(git_repo)

    def test_false_outside(self, tmp_path: Path) -> None:
        assert not is_git_repo(tmp_path)


class TestCheckClean:
    def test_passes_outside_a_git_repo(self, tmp_path: Path) -> None:
        """No .git means the question is unanswerable, not failed."""
        check_clean(cwd=tmp_path)

    def test_rejects_an_uncommitted_change(self, git_repo: Path) -> None:
        (git_repo / "new.txt").write_text("uncommitted\n")
        with pytest.raises(DirtyRepoError, match="Uncommitted changes"):
            check_clean(cwd=git_repo)

    def test_rejects_a_modified_tracked_file(self, git_repo: Path) -> None:
        (git_repo / "README.md").write_text("edited\n")
        with pytest.raises(DirtyRepoError, match="Uncommitted changes"):
            check_clean(cwd=git_repo)

    def test_rejects_a_branch_with_no_upstream(self, git_repo: Path) -> None:
        with pytest.raises(DirtyRepoError, match="no upstream"):
            check_clean(cwd=git_repo)

    def test_names_the_push_command_in_the_error(self, git_repo: Path) -> None:
        with pytest.raises(DirtyRepoError, match=r"git push -u origin main"):
            check_clean(cwd=git_repo)

    def test_rejects_unpushed_commits(self, pushed_repo: Path) -> None:
        # Clean tree, upstream set, but one commit exists only on this machine.
        (pushed_repo / "later.txt").write_text("later\n")
        _run(pushed_repo, "add", "later.txt")
        _run(pushed_repo, "commit", "-m", "later")

        with pytest.raises(DirtyRepoError, match="Unpushed commits"):
            check_clean(cwd=pushed_repo)

    def test_passes_when_clean_and_pushed(self, pushed_repo: Path) -> None:
        check_clean(cwd=pushed_repo)

    def test_allow_dirty_argument_skips_the_gate(self, git_repo: Path) -> None:
        (git_repo / "new.txt").write_text("uncommitted\n")
        check_clean(allow_dirty=True, cwd=git_repo)

    def test_allow_dirty_env_var_skips_the_gate(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PIPELINE_ALLOW_DIRTY", "1")
        (git_repo / "new.txt").write_text("uncommitted\n")
        check_clean(cwd=git_repo)

    def test_ci_skips_the_gate(self, git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CI", "true")
        (git_repo / "new.txt").write_text("uncommitted\n")
        check_clean(cwd=git_repo)


class TestGitMetadata:
    def test_empty_outside_a_repo(self, tmp_path: Path) -> None:
        assert git_metadata(cwd=tmp_path) == {}

    def test_reports_commit_branch_and_clean_state(self, git_repo: Path) -> None:
        meta = git_metadata(cwd=git_repo)
        assert meta["git.branch"] == "main"
        assert len(meta["git.commit"]) == 40
        assert meta["git.dirty"] == "false"

    def test_reports_dirty(self, git_repo: Path) -> None:
        (git_repo / "new.txt").write_text("uncommitted\n")
        assert git_metadata(cwd=git_repo)["git.dirty"] == "true"
