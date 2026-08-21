"""Tests for the DAG engine.

Call counts are kept in a module-level counter rather than on the node instances.
That is not incidental: a node's cache key hashes `vars(fn)`, so a node that
increments a counter on `self` changes its own fingerprint and defeats its own
cache. `test_mutating_instance_state_invalidates_own_cache` pins that behaviour
down; every other test avoids tripping over it.
"""

from __future__ import annotations

from collections import Counter

import pytest

from pipelines.dag import DAG, ItemCache, hash_value
from project_name.result import NodeResult

CALLS: Counter[str] = Counter()


@pytest.fixture(autouse=True)
def _reset_calls() -> None:
    CALLS.clear()


class Source:
    """A node holding only its config, like a real component."""

    def __init__(self, value: int) -> None:
        self.cfg = {"value": value}

    def __call__(self) -> NodeResult:
        CALLS["source"] += 1
        return NodeResult(items=[{"v": self.cfg["value"]}], metrics={"v": 1.0})


class Doubler:
    def __init__(self) -> None:
        self.cfg: dict[str, int] = {}

    def __call__(self, source: NodeResult) -> NodeResult:
        CALLS["double"] += 1
        items = [{"v": item["v"] * 2} for item in source.items]
        return NodeResult(items=items, metrics={"n": float(len(items))})


class SelfMutating:
    """Deliberately does the thing the engine's docstring warns against."""

    def __init__(self) -> None:
        self.cfg: dict[str, int] = {}
        self.seen = 0

    def __call__(self) -> NodeResult:
        CALLS["mutating"] += 1
        self.seen += 1
        return NodeResult(items=[{"seen": self.seen}])


def _dag(tmp_path, **kwargs) -> DAG:
    return DAG(cache_dir=tmp_path / "cache", runs_dir=tmp_path / "runs", **kwargs)


def test_runs_nodes_in_dependency_order(tmp_path) -> None:
    dag = _dag(tmp_path)
    dag.add_node("source", Source(21))
    dag.add_node("double", Doubler(), depends_on="source")

    _, results = dag.run()

    assert results["double"].items == [{"v": 42}]


def test_add_node_rejects_duplicate_names(tmp_path) -> None:
    dag = _dag(tmp_path)
    dag.add_node("source", Source(1))
    with pytest.raises(ValueError, match="duplicate node name"):
        dag.add_node("source", Source(2))


def test_validate_rejects_unknown_dependency(tmp_path) -> None:
    dag = _dag(tmp_path)
    dag.add_node("double", Doubler(), depends_on="nope")
    with pytest.raises(ValueError, match="unknown node 'nope'"):
        dag.validate()


def test_validate_detects_cycle(tmp_path) -> None:
    dag = _dag(tmp_path)
    dag.add_node("a", Doubler(), depends_on="b")
    dag.add_node("b", Doubler(), depends_on="a")
    with pytest.raises(ValueError, match="cycle detected"):
        dag.validate()


def test_run_validates_before_doing_work(tmp_path) -> None:
    dag = _dag(tmp_path)
    dag.add_node("source", Source(1))
    dag.add_node("double", Doubler(), depends_on="typo")
    with pytest.raises(ValueError, match="unknown node"):
        dag.run()
    assert CALLS["source"] == 0, "no node should run when the graph is invalid"


def test_memory_cache_skips_recompute_within_a_process(tmp_path) -> None:
    dag = _dag(tmp_path)
    dag.add_node("source", Source(1))

    dag.run()
    dag.run()

    assert CALLS["source"] == 1


def test_disk_cache_survives_a_new_dag_instance(tmp_path) -> None:
    dag = _dag(tmp_path)
    dag.add_node("source", Source(7))
    dag.run()
    assert CALLS["source"] == 1

    # A fresh DAG and a fresh node instance: only the on-disk cache can help.
    dag2 = _dag(tmp_path)
    dag2.add_node("source", Source(7))
    _, results = dag2.run()

    assert CALLS["source"] == 1
    assert results["source"].items == [{"v": 7}]


def test_changed_config_invalidates_the_cache(tmp_path) -> None:
    dag = _dag(tmp_path)
    dag.add_node("source", Source(1))
    dag.run()

    dag2 = _dag(tmp_path)
    dag2.add_node("source", Source(2))
    _, results = dag2.run()

    assert CALLS["source"] == 2
    assert results["source"].items == [{"v": 2}]


def test_upstream_change_invalidates_downstream(tmp_path) -> None:
    dag = _dag(tmp_path)
    dag.add_node("source", Source(1))
    dag.add_node("double", Doubler(), depends_on="source")
    dag.run()
    assert CALLS["double"] == 1

    dag2 = _dag(tmp_path)
    dag2.add_node("source", Source(5))
    dag2.add_node("double", Doubler(), depends_on="source")
    _, results = dag2.run()

    assert CALLS["double"] == 2
    assert results["double"].items == [{"v": 10}]


def test_mutating_instance_state_invalidates_own_cache(tmp_path) -> None:
    """A node that writes to `self` changes its own fingerprint, every run.

    This is why components must hold their config and nothing else, and load
    models lazily inside `__call__`. The cache is not broken here — it is
    correctly noticing that the node is not the same node any more.
    """
    dag = _dag(tmp_path)
    dag.add_node("mutating", SelfMutating())

    dag.run()
    dag.run()

    assert CALLS["mutating"] == 2


def test_no_disk_cache_recomputes(tmp_path) -> None:
    dag = _dag(tmp_path, use_disk_cache=False)
    dag.add_node("source", Source(1))
    dag.run()

    dag2 = _dag(tmp_path, use_disk_cache=False)
    dag2.add_node("source", Source(1))
    dag2.run()

    assert CALLS["source"] == 2


def test_run_writes_graph_status_and_traces(tmp_path) -> None:
    dag = _dag(tmp_path)
    dag.add_node("source", Source(3))
    dag.add_node("double", Doubler(), depends_on="source")

    timestamp, _ = dag.run()
    run_dir = tmp_path / "runs" / timestamp

    assert (run_dir / "graph.json").is_file()
    assert (run_dir / "cache_keys.json").is_file()
    assert (run_dir / "source_items_trace.jsonl").is_file()
    assert (run_dir / "double_items_trace.jsonl").read_text().strip() == '{"v": 6}'


def test_cache_status_distinguishes_computed_from_cached(tmp_path) -> None:
    import json

    dag = _dag(tmp_path)
    dag.add_node("source", Source(1))
    timestamp, _ = dag.run()
    first = json.loads((tmp_path / "runs" / timestamp / "cache_status.json").read_text())
    assert first == {"source": "computed"}

    timestamp2, _ = dag.run()
    second = json.loads((tmp_path / "runs" / timestamp2 / "cache_status.json").read_text())
    assert second == {"source": "memory"}


def test_no_save_writes_no_run_artefacts(tmp_path) -> None:
    dag = _dag(tmp_path, save_runs=False)
    dag.add_node("source", Source(1))
    timestamp, _ = dag.run()
    assert not list((tmp_path / "runs" / timestamp).iterdir())


def test_graph_reports_nodes_and_edges(tmp_path) -> None:
    dag = _dag(tmp_path)
    dag.add_node("source", Source(1))
    dag.add_node("double", Doubler(), depends_on="source")

    assert dag.graph() == {
        "nodes": ["source", "double"],
        "edges": [{"from": "source", "to": "double"}],
    }


def test_kubeflow_backend_requires_config(tmp_path) -> None:
    dag = _dag(tmp_path)
    dag.add_node("source", Source(1))
    with pytest.raises(ValueError, match="requires kubeflow_config"):
        dag.run(backend="kubeflow")


def test_hash_value_handles_dataclasses_containing_paths() -> None:
    """Config dataclasses hold Path fields; hashing must not choke on them."""
    from project_name.config import PathsConfig

    assert hash_value(PathsConfig()) == hash_value(PathsConfig())


def test_hash_value_is_stable_and_discriminating() -> None:
    assert hash_value({"a": 1}) == hash_value({"a": 1})
    assert hash_value({"a": 1}) != hash_value({"a": 2})


class TestItemCache:
    def test_miss_then_hit(self, tmp_path) -> None:
        cache = ItemCache(cfg={"a": 1}, node_name="n", cache_dir=tmp_path)
        assert cache.get("x") is ItemCache.MISS
        cache.set("x", 99)
        assert cache.get("x") == 99

    def test_none_is_a_real_cached_value(self, tmp_path) -> None:
        """The MISS sentinel exists so a cached None is not mistaken for absent."""
        cache = ItemCache(cfg={"a": 1}, node_name="n", cache_dir=tmp_path)
        cache.set("x", None)
        assert cache.get("x") is None

    def test_config_change_invalidates(self, tmp_path) -> None:
        ItemCache(cfg={"a": 1}, node_name="n", cache_dir=tmp_path).set("x", 1)
        other = ItemCache(cfg={"a": 2}, node_name="n", cache_dir=tmp_path)
        assert other.get("x") is ItemCache.MISS

    def test_version_bump_invalidates(self, tmp_path) -> None:
        ItemCache(cfg={"a": 1}, node_name="n", cache_dir=tmp_path).set("x", 1)
        bumped = ItemCache(cfg={"a": 1}, node_name="n", cache_dir=tmp_path, version=2)
        assert bumped.get("x") is ItemCache.MISS

    def test_distinct_items_do_not_collide(self, tmp_path) -> None:
        cache = ItemCache(cfg={"a": 1}, node_name="n", cache_dir=tmp_path)
        cache.set("x", 1)
        cache.set("y", 2)
        assert (cache.get("x"), cache.get("y")) == (1, 2)
