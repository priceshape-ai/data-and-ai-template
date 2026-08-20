"""Score featurized records and emit the metrics MLflow records.

Whatever this node puts in `NodeResult.metrics` becomes `scorer.<key>` on the
MLflow run, so keep the key names stable across runs — a renamed metric reads as
a gap in the history rather than a rename.
"""

from __future__ import annotations

import logging

from data_and_ai_template.config import ScorerConfig
from data_and_ai_template.result import NodeResult

logger = logging.getLogger(__name__)


class Scorer:
    """Assigns a score per record and summarises the run."""

    def __init__(self, cfg: ScorerConfig) -> None:
        self.cfg = cfg

    def __call__(self, featurize: NodeResult) -> NodeResult:
        items = []
        for record in featurize.items:
            score = self._score(record.get("features", {}))
            items.append({**record, "score": score, "accepted": score >= self.cfg.threshold})

        n = len(items)
        accepted = sum(1 for i in items if i["accepted"])
        metrics = {
            "n_scored": float(n),
            "n_accepted": float(accepted),
            "accept_rate": (accepted / n) if n else 0.0,
            "mean_score": (sum(i["score"] for i in items) / n) if n else 0.0,
        }
        logger.info(
            "Scored %d records, %d accepted at threshold %.2f",
            n,
            accepted,
            self.cfg.threshold,
        )
        return NodeResult(items=items, metrics=metrics)

    @staticmethod
    def _score(features: dict[str, float]) -> float:
        """Stand-in for a real model. Replace wholesale."""
        mean_word_len = features.get("mean_word_len", 0.0)
        return min(mean_word_len / 10.0, 1.0)
