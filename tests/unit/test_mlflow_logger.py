"""Tests for the MLflow logger's pure helpers.

These need no tracking server and no mlflow installation, which is the point of
keeping `log_run` a thin wrapper around functions that only transform data.
"""

from __future__ import annotations

from data_and_ai_template.config import CONFIG
from data_and_ai_template.result import NodeResult
from tracking.mlflow_logger import collect_metrics, flatten_config


class TestCollectMetrics:
    def test_prefixes_metrics_with_the_node_name(self) -> None:
        results = {"score": NodeResult(metrics={"accept_rate": 0.5})}
        assert collect_metrics(results) == {"score.accept_rate": 0.5}

    def test_skips_nodes_that_return_something_else(self) -> None:
        results = {"raw": {"not": "a NodeResult"}, "ok": NodeResult(metrics={"n": 1})}
        assert collect_metrics(results) == {"ok.n": 1.0}

    def test_skips_non_numeric_and_boolean_values(self) -> None:
        """Booleans are ints in Python; logging them as metrics is always a bug."""
        results = {"n": NodeResult(metrics={"good": 1, "flag": True, "text": "x"})}
        assert collect_metrics(results) == {"n.good": 1.0}

    def test_empty_for_no_results(self) -> None:
        assert collect_metrics({}) == {}


class TestFlattenConfig:
    def test_flattens_nested_dataclasses_to_dotted_keys(self) -> None:
        params = flatten_config(CONFIG)
        assert params["featurizer.model_name"] == CONFIG.featurizer.model_name
        assert params["scorer.threshold"] == str(CONFIG.scorer.threshold)

    def test_reaches_into_node_resources(self) -> None:
        params = flatten_config(CONFIG)
        assert (
            params["featurizer.resources.memory_request"]
            == CONFIG.featurizer.resources.memory_request
        )

    def test_drops_infrastructure_sections(self) -> None:
        """Paths and endpoints are not hyperparameters — including them would make
        the same experiment look different when run from another machine."""
        params = flatten_config(CONFIG)
        assert not [key for key in params if key.startswith("paths.")]
        assert not [key for key in params if key.startswith("kubeflow.")]
        assert not [key for key in params if key.startswith("mlflow.")]
        assert not [key for key in params if key.startswith("serving.")]

    def test_every_value_is_a_string(self) -> None:
        assert all(isinstance(v, str) for v in flatten_config(CONFIG).values())

    def test_returns_empty_for_a_non_dataclass(self) -> None:
        assert flatten_config({"not": "a dataclass"}) == {}
