"""Pipeline entrypoint: `uv run pipeline`.

The whole run in order: check the tree is reproducible, build the graph, execute
it on the chosen backend, record the run in MLflow, and print the command to
inspect it.

Development only. This module is absent from the production image, which runs
`uv run serve` instead.
"""

from __future__ import annotations

import argparse
import logging
import sys

from pipelines.build import build_pipeline
from pipelines.dag import DAG
from pipelines.gitgate import DirtyRepoError, check_clean, git_metadata
from project_name.config import CONFIG

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ML pipeline.")
    parser.add_argument(
        "--backend",
        choices=("auto", "local", "kubeflow"),
        default="auto",
        help="auto (default) picks kubeflow when KUBEFLOW_ENDPOINT is set.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Run despite uncommitted or unpushed changes. The MLflow run is "
        "tagged git.dirty=true and is not reproducible from its commit.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore the on-disk node cache and recompute every node.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not write run artefacts under runs/.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=CONFIG.log_level, format="%(levelname)s %(name)s: %(message)s")

    try:
        check_clean(allow_dirty=args.allow_dirty)
    except DirtyRepoError as exc:
        # A usage error, not a crash: print the instruction, skip the traceback.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    backend = args.backend
    if backend == "auto":
        backend = "kubeflow" if CONFIG.kubeflow.enabled else "local"

    dag = DAG(
        cache_dir=CONFIG.paths.dag_cache,
        runs_dir=CONFIG.paths.runs_root,
        save_runs=not args.no_save,
        use_disk_cache=not args.no_cache,
        pipeline_name=CONFIG.mlflow.experiment,
    )
    build_pipeline(dag, CONFIG)

    logger.info(
        "Running %d nodes on the %s backend (cache: %s)",
        len(dag.nodes),
        backend,
        dag.cache_dir,
    )
    timestamp, results = dag.run(
        backend=backend,
        kubeflow_config=CONFIG.kubeflow if backend == "kubeflow" else None,
    )

    _record(timestamp, results, backend)

    if backend == "local":
        print(f"\nInspect this run:\n    make viz RUN={timestamp}")
    return 0


def _record(timestamp: str, results: dict, backend: str) -> None:
    """Log the run to MLflow, if the tracking group is installed and configured.

    Imported lazily and guarded: the pipeline must still run for someone who
    synced without the `tracking` group, and a tracking outage should not lose a
    completed run's results.
    """
    if not CONFIG.mlflow.enabled:
        logger.info("MLFLOW_TRACKING_URI is unset — skipping run logging.")
        return
    try:
        from tracking.mlflow_logger import log_run
    except ImportError:
        logger.warning(
            "mlflow is not installed — skipping run logging. "
            "Install it with: uv sync --group tracking"
        )
        return

    tags = {"backend": backend, **git_metadata()}
    log_run(
        timestamp=timestamp,
        results=results,
        config=CONFIG,
        tags=tags,
        artifacts_dir=CONFIG.paths.runs_root / timestamp,
    )


if __name__ == "__main__":
    raise SystemExit(main())
