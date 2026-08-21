"""End-to-end tests for the serving API through a real ASGI client."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from project_name.serving.app import app
from project_name.serving.inference import Predictor


@pytest.fixture
def client():
    # Entering the context manager runs the lifespan, which kicks off the model
    # load — the same sequence uvicorn performs.
    with TestClient(app) as test_client:
        yield test_client


def test_livez_is_up_immediately(client) -> None:
    response = client.get("/livez")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_healthz_reports_ok_once_loaded(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_predict_returns_one_prediction_per_input(client) -> None:
    response = client.post("/predict", json={"texts": ["hello world", "another one"]})
    assert response.status_code == 200

    body = response.json()
    assert [p["text"] for p in body["predictions"]] == ["hello world", "another one"]
    assert all(0.0 <= p["score"] <= 1.0 for p in body["predictions"])


def test_predict_rejects_an_empty_batch(client) -> None:
    assert client.post("/predict", json={"texts": []}).status_code == 422


def test_predict_rejects_a_missing_field(client) -> None:
    assert client.post("/predict", json={}).status_code == 422


class TestPredictor:
    """The 503-before-loaded path, tested directly rather than over HTTP.

    Going through the app would mean racing the background load thread; a fresh
    Predictor gives the same guarantee deterministically.
    """

    def test_not_ready_before_load(self) -> None:
        assert not Predictor().ready

    def test_predict_raises_before_load(self) -> None:
        with pytest.raises(RuntimeError, match="model not loaded"):
            Predictor().predict(["x"])

    def test_ready_after_load(self) -> None:
        predictor = Predictor()
        predictor.load()
        assert predictor.ready

    def test_load_is_idempotent(self) -> None:
        predictor = Predictor()
        predictor.load()
        first = predictor._model
        predictor.load()
        assert predictor._model is first
