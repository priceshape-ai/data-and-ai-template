"""FastAPI application — the production entrypoint (`uv run serve`).

The model loads on a background thread during startup rather than blocking it, so
the port binds immediately and `/healthz` can answer 503 "still loading" instead
of the container looking dead to Kubernetes while multi-gigabyte weights arrive.
The readiness probe in deploy/manifests/deployment.yaml relies on that
distinction.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from data_and_ai_template import __version__
from data_and_ai_template.config import CONFIG
from data_and_ai_template.serving.inference import PREDICTOR

logger = logging.getLogger(__name__)


class PredictRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=256)


class Prediction(BaseModel):
    text: str
    score: float


class PredictResponse(BaseModel):
    predictions: list[Prediction]
    model_name: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=CONFIG.log_level, format="%(levelname)s %(name)s: %(message)s")
    thread = threading.Thread(target=PREDICTOR.load, name="model-load", daemon=True)
    thread.start()
    logger.info("%s v%s starting in %s", app.title, __version__, CONFIG.environment)
    yield
    logger.info("Shutting down")


app = FastAPI(title="data-and-ai-template", version=__version__, lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    """Readiness. 503 until the model is loaded, 200 after."""
    if not PREDICTOR.ready:
        raise HTTPException(status_code=503, detail="model loading")
    return {"status": "ok", "version": __version__}


@app.get("/livez")
def livez() -> dict[str, str]:
    """Liveness. 200 as soon as the process is up, regardless of the model.

    Kept separate from /healthz on purpose: pointing a liveness probe at a
    readiness endpoint makes Kubernetes restart the pod part-way through a slow
    model load, forever.
    """
    return {"status": "alive"}


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest) -> PredictResponse:
    if not PREDICTOR.ready:
        raise HTTPException(status_code=503, detail="model loading")
    try:
        results = PREDICTOR.predict(request.texts)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return PredictResponse(
        predictions=[Prediction(**r) for r in results],
        model_name=CONFIG.serving.model_name,
    )


def run() -> None:
    """Console-script entrypoint: `uv run serve`."""
    import uvicorn

    uvicorn.run(
        "data_and_ai_template.serving.app:app",
        host=CONFIG.serving.host,
        port=CONFIG.serving.port,
        log_level=CONFIG.log_level.lower(),
    )
