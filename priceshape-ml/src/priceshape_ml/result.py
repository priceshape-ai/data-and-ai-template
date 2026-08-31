"""What the engine needs a node's return value to look like.

A structural type, not a class to inherit from. The engine reads four attributes
off whatever a node returns and never constructs one itself, so requiring a
particular class would drag this package into the production image for no reason —
components return these, and components ship.

Each project therefore owns its own concrete `NodeResult` (see `core/result.py` in
the template) and is free to add fields to it. This is the same arrangement as the
config: the engine states what it reads, the project decides what it is.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class NodeResultLike(Protocol):
    """One node's output, as far as the engine is concerned.

    Attributes:
        items: Per-item results. Written to `runs/<ts>/<node>_items_trace.jsonl`.
        test_items: Per-item results for a held-out split, if there is one.
        metrics: Scalar metrics, logged to MLflow as `<node>.<key>`.
        meta: Anything else carried downstream. Neither logged nor traced.
    """

    items: list[Any]
    test_items: list[Any]
    metrics: dict[str, float]
    meta: dict[str, Any]

    def splits(self) -> dict[str, list[Any]]: ...
