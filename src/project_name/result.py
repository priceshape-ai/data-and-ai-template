"""The value every DAG node returns.

A single shared shape is what lets the generic machinery work without knowing
anything about a particular project: `pipelines/dag.py` writes a JSONL trace for
any node returning per-item results, and `tracking/mlflow_logger.py` records
whatever lands in `metrics`. A node that returns something else still runs — it
just gets no trace and no metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeResult:
    """One node's output.

    Attributes:
        items: Per-item results for the train/main split. Written to
            `runs/<ts>/<node>_items_trace.jsonl` so the Streamlit explorer can
            show lineage row by row.
        test_items: Per-item results for the held-out split, if there is one.
        metrics: Scalar metrics. These are what reach MLflow, as
            `<node_name>.<key>`, so keys should be stable across runs.
        meta: Anything else worth carrying downstream. Not logged, not traced.
    """

    items: list[Any] = field(default_factory=list)
    test_items: list[Any] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def splits(self) -> dict[str, list[Any]]:
        """The non-empty per-item splits, keyed by name."""
        out: dict[str, list[Any]] = {}
        if self.items:
            out["items"] = self.items
        if self.test_items:
            out["test"] = self.test_items
        return out
