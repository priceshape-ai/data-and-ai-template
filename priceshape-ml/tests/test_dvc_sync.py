"""Where `dvc_sync` decides the project is — the one thing it must not get wrong.

Every dvc subcommand in that module runs with `cwd=repo_root()`, so if the root is
wrong nothing works and the failure surfaces as "No .dvc/ directory" — which reads
like a project needing `dvc init` rather than a bug in the engine.

There was no test file here at all, which is exactly why the regression below
shipped: `repo_root()` returned `Path(__file__).parent.parent`, correct while this
module lived at `<repo>/engine/` and wrong the moment the engine became an installed
package, where it resolved to `site-packages/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from priceshape_ml import dvc_sync


def _project(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (path / ".git").mkdir(exist_ok=True)
    return path


class TestRepoRoot:
    def test_comes_from_the_working_directory_not_the_installed_package(
        self, tmp_path, monkeypatch
    ) -> None:
        """The regression. This assertion fails against the old implementation."""
        project = _project(tmp_path / "churn-predictor")
        monkeypatch.chdir(project)
        monkeypatch.delenv("PROJECT_ROOT", raising=False)

        root = dvc_sync.repo_root()

        assert root == project.resolve()
        assert "site-packages" not in str(root)
        # And explicitly: not derived from where this module happens to live.
        assert root != Path(dvc_sync.__file__).resolve().parent.parent

    def test_found_from_a_subdirectory(self, tmp_path, monkeypatch) -> None:
        project = _project(tmp_path / "proj")
        deep = project / "src" / "core" / "components"
        deep.mkdir(parents=True)
        monkeypatch.chdir(deep)
        monkeypatch.delenv("PROJECT_ROOT", raising=False)

        assert dvc_sync.repo_root() == project.resolve()

    def test_dvc_beats_a_nested_distribution(self, tmp_path, monkeypatch) -> None:
        """`priceshape-ml/` inside the template has its own pyproject.toml.

        Walking up for the first marker of any kind would stop there. `.dvc` is
        searched for across the whole chain first, so the real root still wins.
        """
        project = _project(tmp_path / "template")
        (project / ".dvc").mkdir()
        nested = project / "priceshape-ml"
        nested.mkdir()
        (nested / "pyproject.toml").write_text("[project]\nname = 'engine'\n")
        monkeypatch.chdir(nested)
        monkeypatch.delenv("PROJECT_ROOT", raising=False)

        assert dvc_sync.repo_root() == project.resolve()

    def test_never_escapes_the_repository(self, tmp_path, monkeypatch) -> None:
        """A `.dvc` in some ancestor outside the repo must not be selected."""
        (tmp_path / ".dvc").mkdir()
        project = _project(tmp_path / "inner")
        monkeypatch.chdir(project)
        monkeypatch.delenv("PROJECT_ROOT", raising=False)

        assert dvc_sync.repo_root() == project.resolve()

    def test_project_root_env_var_wins(self, tmp_path, monkeypatch) -> None:
        """The Dockerfile sets PROJECT_ROOT; the template's config honours it too."""
        elsewhere = _project(tmp_path / "elsewhere")
        monkeypatch.chdir(_project(tmp_path / "cwd-project"))
        monkeypatch.setenv("PROJECT_ROOT", str(elsewhere))

        assert dvc_sync.repo_root() == elsewhere.resolve()

    def test_falls_back_to_cwd_with_no_markers(self, tmp_path, monkeypatch) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        monkeypatch.chdir(bare)
        monkeypatch.delenv("PROJECT_ROOT", raising=False)

        assert dvc_sync.repo_root() == bare.resolve()


class TestMissingDvcDirectory:
    def test_exits_non_zero_and_names_the_path(self, tmp_path, monkeypatch, capsys) -> None:
        project = _project(tmp_path / "proj")
        monkeypatch.chdir(project)
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        monkeypatch.setattr(sys, "argv", ["dvc_sync"])

        assert dvc_sync.main() == 1

        err = capsys.readouterr().err
        assert str(project.resolve()) in err, "the message must say where it looked"
        assert "PROJECT_ROOT" in err

    def test_add_mode_reports_the_same_way(self, tmp_path, monkeypatch, capsys) -> None:
        project = _project(tmp_path / "proj")
        monkeypatch.chdir(project)
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        monkeypatch.setattr(sys, "argv", ["dvc_sync", "--add"])

        assert dvc_sync.main() == 1
        assert str(project.resolve()) in capsys.readouterr().err
