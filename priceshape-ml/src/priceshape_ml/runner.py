"""The run, start to finish — check the tree, build the graph, execute, record.

This is the half of a pipeline run that is the same in every project. The half
that is not — which steps there are, and what they are configured with — arrives
as arguments, which is what lets this live in a shared package at all.

A project wires the two together in six lines:

    from priceshape_ml import run
    from core.config import CONFIG
    from pipelines.build import build_pipeline

    def main() -> int:
        return run(build_pipeline, CONFIG)

Development only: nothing here is in a production image, which serves instead.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any, Protocol

from priceshape_ml.dag import DAG
from priceshape_ml.gitgate import DirtyRepoError, check_clean, git_metadata

logger = logging.getLogger(__name__)


class GraphBuilder(Protocol):
    """Adds this project's nodes to a DAG. `pipelines/build.py` implements it."""

    def __call__(self, dag: DAG, config: Any) -> dict[str, str]: ...


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ML pipeline.")
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


def run(build: GraphBuilder, config: Any, argv: list[str] | None = None) -> int:
    """Run `build`'s graph under `config`. Returns a process exit code.

    `config` is duck-typed rather than a declared class: the engine reads only
    `log_level`, `paths` and `mlflow` off it, and a project is free to hang anything
    else it likes beside those.
    """
    args = parse_args(argv)
    logging.basicConfig(level=config.log_level, format="%(levelname)s %(name)s: %(message)s")

    try:
        check_clean(allow_dirty=args.allow_dirty)
    except DirtyRepoError as exc:
        # A usage error, not a crash: print the instruction, skip the traceback.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    dag = DAG(
        cache_dir=config.paths.dag_cache,
        runs_dir=config.paths.runs_root,
        save_runs=not args.no_save,
        use_disk_cache=not args.no_cache,
        pipeline_name=config.mlflow.experiment,
    )
    build(dag, config)

    logger.info("Running %d nodes (cache: %s)", len(dag.nodes), dag.cache_dir)
    timestamp, results = dag.run()

    _record(timestamp, results, config)

    print(f"\nInspect this run:\n    make viz RUN={timestamp}")
    return 0


def _record(timestamp: str, results: dict, config: Any) -> None:
    """Log the run to MLflow, if the tracking group is installed and configured.

    Imported lazily and guarded: the pipeline must still run for someone who
    synced without the `tracking` group, and a tracking outage should not lose a
    completed run's results.
    """
    if not config.mlflow.enabled:
        logger.info("MLFLOW_TRACKING_URI is unset — skipping run logging.")
        return
    try:
        from priceshape_ml.tracking import log_run
    except ImportError:
        logger.warning(
            "mlflow is not installed — skipping run logging. "
            "Install it with: uv sync --group tracking"
        )
        return

    tags = git_metadata()
    log_run(
        timestamp=timestamp,
        results=results,
        config=config,
        tags=tags,
        artifacts_dir=config.paths.runs_root / timestamp,
    )


if __name__ == "__main__":  # pragma: no cover - a library, not an entry point
    raise SystemExit(
        "priceshape_ml.runner is a library. Your project's pipelines/runner.py "
        "supplies the graph and config:\n"
        "    from priceshape_ml import run\n"
        "    return run(build_pipeline, CONFIG)"
    )
