"""Typed configuration: frozen dataclasses, and nothing else.

Named `hyperparameters.py` to match `taxonomy-engine` and `ai-productsmatcher`, and
like theirs it holds the infrastructure sections too — paths, MLflow, serving —
alongside the actual hyperparameters. The distinction is not lost: only
the hyperparameter sections reach MLflow as params, because
`priceshape_ml` drops the rest via `_SKIP_SECTIONS`. An endpoint URL is
not a hyperparameter, and logging it would make one experiment run from two
machines look like two different configurations.

There is no config YAML in this project, on purpose. Hyperparameters live here as
`@dataclass(frozen=True)` with `Literal` types, which means a typo in a model name
is a type error rather than a runtime surprise three stages into a pipeline, and
the values are navigable from the code that uses them.

`load_dotenv()` is called here, before CONFIG is built, rather than in the
entrypoint. CONFIG is a module-level singleton, so any entrypoint that imports it
before loading .env would silently get defaults; owning the load here makes
`from core.config import CONFIG` safe from anywhere. It is a no-op when
there is no .env file, which is the case in production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from core.config.constants import PROJECT_ROOT

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


@dataclass(frozen=True)
class FeaturizerConfig:
    """Turns raw records into features. GPU-bound in a real project."""

    model_name: EmbeddingModel = "BAAI/bge-m3"
    batch_size: int = 32
    text_field: str = "title"


@dataclass(frozen=True)
class ScorerConfig:
    """Scores features and produces the metrics MLflow records."""

    threshold: float = 0.5


# ── Top level ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Config:
    environment: str = field(default_factory=lambda: _env("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    paths: PathsConfig = field(default_factory=PathsConfig)
    mlflow: MlflowConfig = field(default_factory=MlflowConfig)
    serving: ServingConfig = field(default_factory=ServingConfig)

    loader: LoaderConfig = field(default_factory=LoaderConfig)
    featurizer: FeaturizerConfig = field(default_factory=FeaturizerConfig)
    scorer: ScorerConfig = field(default_factory=ScorerConfig)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


CONFIG = Config()
