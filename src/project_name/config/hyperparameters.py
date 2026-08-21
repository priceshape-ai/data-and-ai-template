"""Typed configuration: frozen dataclasses, and nothing else.

Named `hyperparameters.py` to match `taxonomy-engine` and `ai-productsmatcher`, and
like theirs it holds the infrastructure sections too — paths, MLflow, Kubeflow,
serving — alongside the actual hyperparameters. The distinction is not lost: only
the hyperparameter sections reach MLflow as params, because
`tracking/mlflow_logger.py` drops the rest via `_SKIP_SECTIONS`. An endpoint URL is
not a hyperparameter, and logging it would make one experiment run from two
machines look like two different configurations.

There is no config YAML in this project, on purpose. Hyperparameters live here as
`@dataclass(frozen=True)` with `Literal` types, which means a typo in a model name
is a type error rather than a runtime surprise three stages into a pipeline, and
the values are navigable from the code that uses them.

Each node config carries its own `NodeResources`. That is what lets one DAG
definition compile to both a local run (where resources are ignored) and a
Kubeflow pipeline (where they become the pod's resource requests) — see
`pipelines/dag.py`.

`load_dotenv()` is called here, before CONFIG is built, rather than in the
entrypoint. CONFIG is a module-level singleton, so any entrypoint that imports it
before loading .env would silently get defaults; owning the load here makes
`from project_name.config import CONFIG` safe from anywhere. It is a no-op when
there is no .env file, which is the case in production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from project_name.config.constants import PROJECT_ROOT

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


# ── Literal types: the set of values that are actually allowed ────────────────

EmbeddingModel = Literal[
    "BAAI/bge-m3",
    "BAAI/bge-large-en-v1.5",
    "all-MiniLM-L6-v2",
    "all-mpnet-base-v2",
    "paraphrase-multilingual-MiniLM-L12-v2",
]

Device = Literal["cpu", "cuda", "mps"]


# ── Infrastructure ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NodeResources:
    """A Kubeflow pod resource request for one DAG node. Ignored on local runs."""

    cpu_request: str = "1"
    memory_request: str = "4G"
    accelerator_type: str = ""  # e.g. "nvidia.com/gpu"; empty means CPU-only
    accelerator_limit: int = 1
    node_pool: str = ""  # node-pool label value; empty means any node


@dataclass(frozen=True)
class PathsConfig:
    """Every filesystem location the project uses. Nothing hard-codes a path."""

    data_root: Path = field(default_factory=lambda: PROJECT_ROOT / ".data")
    models_root: Path = field(default_factory=lambda: PROJECT_ROOT / ".models")
    artifacts_root: Path = field(default_factory=lambda: PROJECT_ROOT / "artifacts")
    runs_root: Path = field(default_factory=lambda: PROJECT_ROOT / "runs")
    dag_cache: Path = field(default_factory=lambda: PROJECT_ROOT / ".dag_cache")


@dataclass(frozen=True)
class MlflowConfig:
    """MLflow client settings. An empty tracking_uri disables run logging."""

    tracking_uri: str = field(default_factory=lambda: _env("MLFLOW_TRACKING_URI"))
    experiment: str = field(default_factory=lambda: _env("MLFLOW_EXPERIMENT", "project-name"))

    @property
    def enabled(self) -> bool:
        return bool(self.tracking_uri)


@dataclass(frozen=True)
class KubeflowConfig:
    """KFP submission settings. An empty endpoint means run locally."""

    endpoint: str = field(default_factory=lambda: _env("KUBEFLOW_ENDPOINT"))
    experiment_name: str = field(
        default_factory=lambda: _env("KUBEFLOW_EXPERIMENT", "project-name")
    )
    s3_bucket: str = field(default_factory=lambda: _env("KUBEFLOW_S3_BUCKET", "project-name"))
    s3_endpoint: str = field(default_factory=lambda: _env("KUBEFLOW_S3_ENDPOINT"))
    base_image: str = field(default_factory=lambda: _env("KUBEFLOW_BASE_IMAGE", "python:3.12-slim"))

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)


@dataclass(frozen=True)
class ServingConfig:
    """Settings the production API reads. The only section production touches."""

    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    model_name: EmbeddingModel = "BAAI/bge-m3"
    device: Device = "cpu"


# ── Node configs ──────────────────────────────────────────────────────────────
# One per DAG node. Replace these with the project's real stages; the two below
# are what the example pipeline in pipelines/build.py wires together.


@dataclass(frozen=True)
class LoaderConfig:
    """Reads the source dataset off disk."""

    source: str = "raw/dataset.jsonl"
    limit: int | None = None
    resources: NodeResources = field(
        default_factory=lambda: NodeResources(cpu_request="1", memory_request="2G")
    )


@dataclass(frozen=True)
class FeaturizerConfig:
    """Turns raw records into features. GPU-bound in a real project."""

    model_name: EmbeddingModel = "BAAI/bge-m3"
    batch_size: int = 32
    text_field: str = "title"
    resources: NodeResources = field(
        default_factory=lambda: NodeResources(cpu_request="4", memory_request="16G")
    )


@dataclass(frozen=True)
class ScorerConfig:
    """Scores features and produces the metrics MLflow records."""

    threshold: float = 0.5
    resources: NodeResources = field(default_factory=NodeResources)


# ── Top level ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Config:
    environment: str = field(default_factory=lambda: _env("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    paths: PathsConfig = field(default_factory=PathsConfig)
    mlflow: MlflowConfig = field(default_factory=MlflowConfig)
    kubeflow: KubeflowConfig = field(default_factory=KubeflowConfig)
    serving: ServingConfig = field(default_factory=ServingConfig)

    loader: LoaderConfig = field(default_factory=LoaderConfig)
    featurizer: FeaturizerConfig = field(default_factory=FeaturizerConfig)
    scorer: ScorerConfig = field(default_factory=ScorerConfig)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


CONFIG = Config()
