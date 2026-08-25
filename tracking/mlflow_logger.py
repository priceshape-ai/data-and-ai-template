"""Record a completed pipeline run in MLflow.

Two properties worth keeping as this grows:

**It is a pure function of its arguments.** Provenance tags are passed in, not
gathered here — `pipelines/gitgate.py` owns the git introspection. So this module
never shells out, and a test can assert exactly what would be logged.

**It never raises.** A tracking-server outage must not destroy a pipeline run that
already finished and already wrote its results to disk. Every failure downgrades
to a warning; the caller's exit status is unaffected.
"""

from __future__ import annotations

import dataclasses
import logging
import os
from pathlib import Path
from typing import Any

from project_name.result import NodeResult

logger = logging.getLogger(__name__)

# MLflow's client defaults to 7 retries with exponential backoff, so an
# unreachable tracking server stalls a finished pipeline for minutes before the
# failure is even reported — off the VPN, that reads as a hang. These bounds cost
# a few seconds instead. setdefault, so an operator can still raise them.
_HTTP_DEFAULTS = {
    "MLFLOW_HTTP_REQUEST_MAX_RETRIES": "2",
    "MLFLOW_HTTP_REQUEST_TIMEOUT": "10",
    "MLFLOW_HTTP_REQUEST_BACKOFF_FACTOR": "1",
}

# MLflow rejects over-long param values. Truncate rather than lose the whole run.
_MAX_PARAM_LEN = 500

# Machine-specific or already-captured sections: logging them adds noise and makes
# two identical runs on different machines look different.
_SKIP_SECTIONS = frozenset({"paths", "mlflow", "kubeflow", "serving"})


def log_run(
    timestamp: str,
    results: dict[str, Any],
    config: Any,
    tags: dict[str, str] | None = None,
    artifacts_dir: Path | str | None = None,
) -> str | None:
    """Log one run. Returns the MLflow run id, or None if nothing was logged.

    Args:
        timestamp: Run name — the same stamp the DAG used for `runs/<ts>/`, so a
            run in MLflow can be traced back to its artefacts on disk.
        results: `{node_name: NodeResult}`. Metrics are logged as
            `<node_name>.<metric>`; nodes returning anything else are skipped.
        config: The `Config` whose hyperparameters get logged as params.
        tags: Provenance tags, e.g. the git metadata and the backend used.
        artifacts_dir: Directory to upload wholesale — normally `runs/<ts>/`,
            which holds the graph, the cache status and the per-node traces.
    """
    for name, value in _HTTP_DEFAULTS.items():
        os.environ.setdefault(name, value)

    try:
        import mlflow
    except ImportError:
        logger.warning(
            "mlflow is not installed — run not logged. Install it with: uv sync --group tracking"
        )
        return None

    try:
        mlflow.set_tracking_uri(config.mlflow.tracking_uri)
        mlflow.set_experiment(config.mlflow.experiment)

        with mlflow.start_run(run_name=timestamp) as run:
            if tags:
                mlflow.set_tags(tags)

            params = flatten_config(config)
            if params:
                mlflow.log_params(params)

            metrics = collect_metrics(results)
            if metrics:
                mlflow.log_metrics(metrics)

            if artifacts_dir is not None and Path(artifacts_dir).is_dir():
                mlflow.log_artifacts(str(artifacts_dir))

            logger.info(
                "Logged run %s (%d params, %d metrics) → %s",
                timestamp,
                len(params),
                len(metrics),
                config.mlflow.tracking_uri,
            )
            return str(run.info.run_id)

    except Exception as exc:
        # Deliberately broad: the run itself succeeded, and losing its record is
        # strictly better than losing its results. The summary goes to WARNING and
        # the traceback to DEBUG — an unreachable tracking server is a normal
        # operational event and should not read like a crash.
        summary = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        logger.warning(
            "MLflow logging failed (%s) — the run completed and its results are "
            "under runs/. Re-run with LOG_LEVEL=DEBUG for the traceback.",
            summary,
        )
        # A rejected credential is the one failure here with an obvious fix, and
        # the raw status code does not suggest it.
        lowered = summary.lower()
        auth_markers = (
            "401",
            "403",
            "unauthenticated",
            "permission_denied",
            "unauthorized",
            "forbidden",
        )
        if any(marker in lowered for marker in auth_markers):
            logger.warning(
                "That looks like an authentication failure. Set "
                "MLFLOW_TRACKING_USERNAME and MLFLOW_TRACKING_PASSWORD in .env "
                "(or MLFLOW_TRACKING_TOKEN) — see .env.example."
            )
        logger.debug("MLflow failure traceback", exc_info=True)
        return None


def collect_metrics(results: dict[str, Any]) -> dict[str, float]:
    """Flatten `{node: NodeResult}` into `{"<node>.<metric>": value}`."""
    metrics: dict[str, float] = {}
    for node_name, result in results.items():
        if not isinstance(result, NodeResult):
            continue
        for key, value in result.metrics.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            metrics[f"{node_name}.{key}"] = float(value)
    return metrics


def flatten_config(config: Any) -> dict[str, str]:
    """Flatten the config dataclass tree into dotted MLflow params.

    Infrastructure sections are dropped: an endpoint URL or a filesystem path is
    not a hyperparameter, and including it would make the same experiment run
    from two machines look like two different configurations.
    """
    if not dataclasses.is_dataclass(config) or isinstance(config, type):
        return {}

    flat: dict[str, str] = {}

    def walk(prefix: str, value: Any) -> None:
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            for f in dataclasses.fields(value):
                walk(f"{prefix}.{f.name}" if prefix else f.name, getattr(value, f.name))
            return
        if isinstance(value, dict):
            for key, item in value.items():
                walk(f"{prefix}.{key}", item)
            return
        text = str(value)
        flat[prefix] = text if len(text) <= _MAX_PARAM_LEN else text[: _MAX_PARAM_LEN - 1] + "…"

    for f in dataclasses.fields(config):
        if f.name in _SKIP_SECTIONS:
            continue
        walk(f.name, getattr(config, f.name))

    return flat
