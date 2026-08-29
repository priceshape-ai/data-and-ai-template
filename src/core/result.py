"""The value every pipeline step returns.

The engine matches this structurally, against the `NodeResultLike` protocol in
`priceshape_ml` — it never imports this class and never constructs one. That is
what keeps the engine out of the production image while components, which do ship,
still return something it understands.

Add fields freely. The engine reads the four below and ignores everything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeResult:
    """One step's output.

    Attributes:
        items: Per-item results for the main split. Written to
            `runs/<ts>/<node>_items_trace.jsonl`, which is what the run explorer
            reads to show lineage row by row.
        test_items: Per-item results for a held-out split, if there is one.
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
