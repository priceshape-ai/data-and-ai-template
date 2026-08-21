"""The example pipeline runs end to end, on a fresh clone with no data.

This is the test that keeps the template honest: a generated repository has no
`.data/` until someone runs `dvc pull`, and it should still produce a run.
"""

from __future__ import annotations

import dataclasses

from data_and_ai_template.config import CONFIG
from data_and_ai_template.result import NodeResult
from pipelines.build import build_pipeline
from pipelines.dag import DAG
from tracking.mlflow_logger import collect_metrics


def _dag(tmp_path) -> DAG:
    return DAG(cache_dir=tmp_path / "cache", runs_dir=tmp_path / "runs")


def test_pipeline_runs_and_produces_scored_records(tmp_path) -> None:
    dag = _dag(tmp_path)
    nodes = build_pipeline(dag, CONFIG)

    timestamp, results = dag.run()

    assert set(nodes) == {"load", "featurize", "score"}
    scored = results["score"]
    assert isinstance(scored, NodeResult)
    assert scored.items, "the built-in sample should produce records"
    assert all("score" in item for item in scored.items)
    assert timestamp


def test_wiring_matches_component_signatures(tmp_path) -> None:
    """A node's dependency names must match its callable's parameter names.

    If they drift, the DAG raises TypeError on the first run. Asserting it here
    means the failure shows up in CI rather than in someone's first pipeline run.
    """
    dag = _dag(tmp_path)
    build_pipeline(dag, CONFIG)
    dag.validate()

    _, results = dag.run()
    assert len(results) == len(dag.nodes)


def test_run_metrics_are_loggable(tmp_path) -> None:
    dag = _dag(tmp_path)
    build_pipeline(dag, CONFIG)
    _, results = dag.run()

    metrics = collect_metrics(results)
    assert "score.accept_rate" in metrics
    assert "load.n_records" in metrics


def test_reads_a_real_dataset_when_one_is_present(tmp_path, monkeypatch) -> None:
    """The loader prefers .data/ over the built-in sample."""
    import json

    from data_and_ai_template.data.loader import DatasetLoader

    data_root = tmp_path / "data"
    (data_root / "raw").mkdir(parents=True)
    records = [{"id": 9, "title": "a genuinely long product title", "label": "x"}]
    (data_root / "raw" / "dataset.jsonl").write_text("\n".join(json.dumps(r) for r in records))

    # CONFIG is frozen, so the module reference is what gets swapped, not a field.
    patched = dataclasses.replace(
        CONFIG, paths=dataclasses.replace(CONFIG.paths, data_root=data_root)
    )
    monkeypatch.setattr("data_and_ai_template.data.loader.CONFIG", patched)

    result = DatasetLoader(CONFIG.loader)()
    assert result.items == records


def test_limit_truncates_the_dataset() -> None:
    from data_and_ai_template.config import LoaderConfig
    from data_and_ai_template.data.loader import DatasetLoader

    result = DatasetLoader(LoaderConfig(limit=2))()
    assert len(result.items) == 2
