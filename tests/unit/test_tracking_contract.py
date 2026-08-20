"""The two guarantees `log_run` makes to its caller.

Both exist because of one failure: a pipeline finishes, writes its results to disk,
and then the tracking server turns out to be unreachable. Neither the results nor
the developer's afternoon should be lost to that.
"""

from __future__ import annotations

import builtins
import dataclasses
import os

import pytest

from data_and_ai_template.config import CONFIG
from tracking import mlflow_logger
from tracking.mlflow_logger import log_run


def _config_with_uri(uri: str):
    return dataclasses.replace(CONFIG, mlflow=dataclasses.replace(CONFIG.mlflow, tracking_uri=uri))


def test_never_raises_when_the_server_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Port 1 refuses connections everywhere, so this exercises the real client."""
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_TIMEOUT", "1")

    result = log_run(timestamp="t", results={}, config=_config_with_uri("http://127.0.0.1:1"))
    assert result is None


def test_never_raises_when_mlflow_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Someone who synced without the tracking group still gets a working pipeline."""
    real_import = builtins.__import__

    def fail_on_mlflow(name: str, *args: object, **kwargs: object):
        if name == "mlflow":
            raise ImportError("simulated: tracking group not installed")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fail_on_mlflow)

    assert log_run(timestamp="t", results={}, config=CONFIG) is None


def test_bounds_mlflow_http_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """MLflow's own default is 7 retries with backoff, which reads as a hang."""
    for name in mlflow_logger._HTTP_DEFAULTS:
        monkeypatch.delenv(name, raising=False)

    log_run(timestamp="t", results={}, config=_config_with_uri(""))

    assert os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] == "2"


def test_does_not_override_an_explicit_retry_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound is a default, not a policy — an operator can still raise it."""
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "9")

    log_run(timestamp="t", results={}, config=_config_with_uri(""))

    assert os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] == "9"
