"""Turn raw records into features.

The example implementation is deliberately dependency-free so a fresh clone runs
without downloading a model. In a real project this is where
`sentence-transformers` or a remote embedding call goes — load it lazily in
`__call__`, so constructing the node stays cheap and the DAG's cache fingerprint
stays small.
"""

from __future__ import annotations

import logging

from data_and_ai_template.config import FeaturizerConfig
from data_and_ai_template.result import NodeResult

logger = logging.getLogger(__name__)


class Featurizer:
    """Adds a feature vector to each record.

    Depends on the `load` node, so its parameter is named `load`. The DAG passes
    upstream results by node name, which is why the signature has to match the
    wiring in `pipelines/build.py`.
    """

    def __init__(self, cfg: FeaturizerConfig) -> None:
        self.cfg = cfg

    def __call__(self, load: NodeResult) -> NodeResult:
        # Real projects load the model here, not in __init__:
        #   from sentence_transformers import SentenceTransformer
        #   model = SentenceTransformer(self.cfg.model_name, device=...)
        items = []
        for record in load.items:
            text = str(record.get(self.cfg.text_field, ""))
            items.append({**record, "features": self._features(text)})

        logger.info(
            "Featurized %d records with %s (batch_size=%d)",
            len(items),
            self.cfg.model_name,
            self.cfg.batch_size,
        )
        return NodeResult(
            items=items,
            metrics={"n_featurized": float(len(items))},
            meta={"model_name": self.cfg.model_name},
        )

    @staticmethod
    def _features(text: str) -> dict[str, float]:
        """Stand-in for a real embedding. Replace wholesale."""
        words = text.split()
        return {
            "n_chars": float(len(text)),
            "n_words": float(len(words)),
            "mean_word_len": (sum(len(w) for w in words) / len(words) if words else 0.0),
        }
