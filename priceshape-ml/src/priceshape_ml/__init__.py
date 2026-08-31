"""The machinery every PriceShape Data & AI project shares.

A DAG that turns a graph of callables into a cached run, the reproducibility gate,
MLflow run logging, and the DVC sync. None of it knows anything about a
particular project: what the steps are and how they are configured arrives as
arguments, which is what lets one copy serve every repository.

A project uses it like this:

    from core.result import NodeResult     # your project's own
    from priceshape_ml import run

    class Scorer:
        def __init__(self, cfg): self.cfg = cfg
        def __call__(self, featurize: NodeResult) -> NodeResult:
            return NodeResult(items=..., metrics={"mean": 0.8})

and wires its own graph and config into `run` from `pipelines/runner.py`.

Fixing a bug here fixes it for every project at the next version bump, which is
the whole reason this is a package rather than a directory copied into each one.
"""

from __future__ import annotations

from priceshape_ml.dag import DAG, ItemCache, hash_value
from priceshape_ml.gitgate import DirtyRepoError, check_clean, git_metadata, is_git_repo
from priceshape_ml.result import NodeResultLike
from priceshape_ml.runner import run
from priceshape_ml.tracking import collect_metrics, flatten_config, log_run

__version__ = "0.2.1"

__all__ = [
    "DAG",
    "DirtyRepoError",
    "ItemCache",
    "NodeResultLike",
    "__version__",
    "check_clean",
    "collect_metrics",
    "flatten_config",
    "git_metadata",
    "hash_value",
    "is_git_repo",
    "log_run",
    "run",
]
