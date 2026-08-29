"""Model loading and prediction for the serving path.

Deliberately separate from `app.py`: the HTTP layer and the model layer fail for
different reasons and are worth testing apart. `app.py` owns request validation
and status codes; this file owns the model.

Weights are not baked into the image — they are synced from S3 or mounted at
`CONFIG.paths.models_root` at startup, so a model swap is a restart rather than a
rebuild.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from core.config import CONFIG

logger = logging.getLogger(__name__)


class Predictor:
    """Loads the model once, lazily, and predicts.

    Loading is deferred so the process can start and answer `/healthz` with a
    503 while the weights are still arriving — a container that blocks on a
    multi-gigabyte download before binding its port looks dead to Kubernetes and
    gets killed by the liveness probe.
    """

    def __init__(self) -> None:
        self._model: Any | None = None
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Load the model. Safe to call more than once and from several threads."""
        with self._lock:
            if self._model is not None:
                return
            path = CONFIG.paths.models_root
            logger.info(
                "Loading model %s on %s from %s",
                CONFIG.serving.model_name,
                CONFIG.serving.device,
                path,
            )
            # Real projects load here, e.g.:
            #   from sentence_transformers import SentenceTransformer
            #   self._model = SentenceTransformer(
            #       CONFIG.serving.model_name, device=CONFIG.serving.device,
            #       cache_folder=str(path),
            #   )
            self._model = _EchoModel()
            logger.info("Model ready")

    def predict(self, texts: list[str]) -> list[dict[str, Any]]:
        """Score a batch. Raises RuntimeError if the model is not loaded yet."""
        if self._model is None:
            raise RuntimeError("model not loaded")
        return [self._model.score(t) for t in texts]


class _EchoModel:
    """Placeholder so the template serves real responses. Replace wholesale."""

    @staticmethod
    def score(text: str) -> dict[str, Any]:
        words = text.split()
        mean_word_len = sum(len(w) for w in words) / len(words) if words else 0.0
        return {"text": text, "score": min(mean_word_len / 10.0, 1.0)}


PREDICTOR = Predictor()
