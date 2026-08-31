"""DAG engine: build a graph of callables, execute it, cache what it computed.

A node is any callable. Its keyword parameters are named after the nodes it
depends on, and the engine passes upstream results by name. That is the whole
contract — components stay plain objects that know nothing about caching or
MLflow.

**Caching.** A node's cache key is a hash of its `__call__` bytecode, its instance
state (`vars(fn)`), and its upstream nodes' cache keys. So editing a component's
body, changing a hyperparameter on its config, or invalidating anything upstream
all invalidate it, transitively, without anyone maintaining a stage list. Results
are cached in memory for the process and on disk under `.dag_cache/` across runs.

Because instance state is part of the key, keep node instances cheap and
JSON-representable: hold the config, load models lazily inside `__call__`.

**Execution is in-process.** One graph, one way to run it. There is no remote
backend and no scheduler here: a node is a callable, and running the graph calls
them in dependency order.
"""

from __future__ import annotations

import datetime
import hashlib
import inspect
import json
import logging
import pickle
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RunResult = tuple[str, dict[str, Any]]

_MISS = object()
"""Sentinel for "not in cache", distinct from a cached value of None."""


def hash_value(value: Any) -> str:
    """Stable 12-char digest of a dataclass or any JSON-dumpable value."""
    payload = asdict(value) if is_dataclass(value) and not isinstance(value, type) else value
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[
        :12
    ]


class ItemCache:
    """Per-item disk cache, for nodes whose work is expensive *per record*.

    A node-level cache is all-or-nothing: change one record and the whole node
    recomputes. For nodes that make a network or LLM call per item, that is the
    difference between seconds and hours, so those nodes cache per item instead:

        cache = ItemCache(cfg=self.cfg, node_name="enhance")
        result = cache.get(text)
        if result is ItemCache.MISS:
            result = expensive(text)
            cache.set(text, result)

    Bump `version` to invalidate every entry after changing the logic in a way
    the config does not capture.
    """

    MISS = _MISS

    def __init__(
        self,
        cfg: Any,
        node_name: str,
        extra: Any = None,
        cache_dir: str | Path = ".dag_cache",
        version: int = 0,
    ) -> None:
        ctx: dict[str, Any] = {
            "cfg": hash_value(cfg),
            "extra": hash_value(extra) if extra is not None else None,
        }
        if version:
            ctx["version"] = version
        self._ctx_hash = hashlib.sha256(json.dumps(ctx, sort_keys=True).encode()).hexdigest()[:12]
        self._dir = Path(cache_dir) / "items" / node_name
        self._dir.mkdir(parents=True, exist_ok=True)

    def _key(self, item: Any) -> str:
        return hashlib.sha256(
            json.dumps({"ctx": self._ctx_hash, "item": hash_value(item)}, sort_keys=True).encode()
        ).hexdigest()[:12]

    def get(self, item: Any) -> Any:
        path = self._dir / f"{self._key(item)}.pkl"
        if not path.exists():
            return _MISS
        with path.open("rb") as f:
            return pickle.load(f)

    def set(self, item: Any, result: Any) -> None:
        with (self._dir / f"{self._key(item)}.pkl").open("wb") as f:
            pickle.dump(result, f)


@dataclass
class Node:
    name: str
    fn: Callable[..., Any]
    depends_on: list[str] = field(default_factory=list)


class DAG:
    def __init__(
        self,
        cache_dir: str | Path = ".dag_cache",
        runs_dir: str | Path = "runs",
        save_runs: bool = True,
        use_disk_cache: bool = True,
        pipeline_name: str = "project-name",
    ) -> None:
        self.nodes: dict[str, Node] = {}
        self.cache: dict[str, tuple[str, Any]] = {}
        self.cache_dir = Path(cache_dir)
        self.runs_dir = Path(runs_dir)
        self.save_runs = save_runs
        self.use_disk_cache = use_disk_cache
        self.pipeline_name = pipeline_name
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ── definition ────────────────────────────────────────────────────────────

    def add_node(
        self,
        name: str,
        fn: Callable[..., Any],
        depends_on: str | list[str] | None = None,
    ) -> str:
        """Register a node and return its name, so calls can be chained as wiring."""
        if name in self.nodes:
            raise ValueError(f"duplicate node name: {name!r}")
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        self.nodes[name] = Node(name, fn, list(depends_on or []))
        return name

    def validate(self) -> None:
        """Fail before doing any work if the graph is malformed.

        Catches the two mistakes that are otherwise found halfway through a long
        run: a dependency on a node that was never added (usually a typo), and a
        cycle.
        """
        for node in self.nodes.values():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    raise ValueError(f"node {node.name!r} depends on unknown node {dep!r}")
        self._topo_order()

    # ── execution ─────────────────────────────────────────────────────────────

    def run(self) -> RunResult:
        """Execute the graph. Returns `(timestamp, {node_name: result})`.

        Validates first, so a malformed graph fails before any node runs rather
        than halfway through a long one.
        """
        self.validate()
        return self._run()

    def _run(self) -> RunResult:
        ts = _timestamp()
        run_dir = self.runs_dir / ts
        run_dir.mkdir(parents=True, exist_ok=True)

        cache_status: dict[str, str] = {}
        cache_keys: dict[str, str] = {}

        for name in self._topo_order():
            node = self.nodes[name]
            key = self._cache_key(node)
            cache_keys[name] = key

            if name in self.cache and self.cache[name][0] == key:
                logger.info("[cache hit: memory]  %-24s key=%s", name, key)
                cache_status[name] = "memory"
                continue

            if self.use_disk_cache:
                cached = self._load_from_disk(name, key)
                if cached is not _MISS:
                    self.cache[name] = (key, cached)
                    logger.info("[cache hit: disk]    %-24s key=%s", name, key)
                    cache_status[name] = "disk"
                    continue

            inputs = {dep: self.cache[dep][1] for dep in node.depends_on}
            result = node.fn(**inputs)
            self.cache[name] = (key, result)
            if self.use_disk_cache:
                self._save_to_disk(name, key, result)
            logger.info("[computed]           %-24s key=%s", name, key)
            cache_status[name] = "computed"

        if self.save_runs:
            self._save_run(run_dir, cache_status, cache_keys)
        return ts, {name: value for name, (_, value) in self.cache.items()}

    # ── caching internals ─────────────────────────────────────────────────────

    def _disk_path(self, node_name: str, key: str) -> Path:
        node_dir = self.cache_dir / node_name
        node_dir.mkdir(parents=True, exist_ok=True)
        return node_dir / f"{key}.pkl"

    def _load_from_disk(self, node_name: str, key: str) -> Any:
        path = self._disk_path(node_name, key)
        if not path.exists():
            return _MISS
        with path.open("rb") as f:
            return pickle.load(f)

    def _save_to_disk(self, node_name: str, key: str, result: Any) -> None:
        with self._disk_path(node_name, key).open("wb") as f:
            pickle.dump(result, f)

    def _cache_key(self, node: Node) -> str:
        # A plain function carries __code__ directly; a callable instance carries it
        # on its __call__. Going through an Any-typed local keeps both paths in one
        # expression without mypy objecting to __call__ on a Callable.
        fn: Any = node.fn
        code = getattr(fn, "__code__", None) or fn.__call__.__code__
        state = (
            {}
            if inspect.isfunction(node.fn)
            else {k: hash_value(v) for k, v in vars(node.fn).items()}
        )
        fingerprint = {
            "code": code.co_code.hex(),
            "state": state,
            "upstream": [self.cache[dep][0] for dep in node.depends_on],
        }
        return hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()[:12]

    def _topo_order(self) -> list[str]:
        dependents: dict[str, list[str]] = {name: [] for name in self.nodes}
        in_degree = {name: len(node.depends_on) for name, node in self.nodes.items()}
        for node in self.nodes.values():
            for dep in node.depends_on:
                dependents[dep].append(node.name)

        ready = sorted(n for n, d in in_degree.items() if d == 0)
        order: list[str] = []
        while ready:
            current = ready.pop(0)
            order.append(current)
            for dependent in dependents[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    ready.append(dependent)

        if len(order) != len(self.nodes):
            stuck = sorted(set(self.nodes) - set(order))
            raise ValueError(f"cycle detected in DAG, involving: {', '.join(stuck)}")
        return order

    # ── run artefacts ─────────────────────────────────────────────────────────

    def graph(self) -> dict[str, Any]:
        """The graph as nodes and edges — what viz/app.py renders."""
        return {
            "nodes": list(self.nodes),
            "edges": [
                {"from": dep, "to": node.name}
                for node in self.nodes.values()
                for dep in node.depends_on
            ],
        }

    def _save_run(
        self, run_dir: Path, cache_status: dict[str, str], cache_keys: dict[str, str]
    ) -> None:
        (run_dir / "graph.json").write_text(json.dumps(self.graph(), indent=2))
        (run_dir / "cache_status.json").write_text(json.dumps(cache_status, indent=2))
        (run_dir / "cache_keys.json").write_text(json.dumps(cache_keys, indent=2))
        self._write_traces(run_dir)

    def _write_traces(self, run_dir: Path) -> None:
        """Write one JSONL trace per node that produced per-item results."""
        from priceshape_ml.result import NodeResultLike

        for name, (_, result) in self.cache.items():
            if not isinstance(result, NodeResultLike):
                continue
            for split, items in result.splits().items():
                path = run_dir / f"{name}_{split}_trace.jsonl"
                with path.open("w") as f:
                    for item in items:
                        f.write(json.dumps(_jsonable(item)) + "\n")
                logger.info("[trace]              %-24s → %s", name, path.name)


def _timestamp() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H-%M-%S")


def _jsonable(obj: Any) -> Any:
    """Best-effort conversion to something json.dumps accepts."""
    import dataclasses

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _jsonable(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    # numpy is optional: only projects that use it pay for the import.
    try:
        import numpy as np

        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    return str(obj)
