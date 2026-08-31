"""Typed configuration. `from core.config import CONFIG`."""

from core.config.constants import PROJECT_ROOT, discover_project_root
from core.config.hyperparameters import (
    CONFIG,
    Config,
    Device,
    EmbeddingModel,
    FeaturizerConfig,
    LoaderConfig,
    MlflowConfig,
    PathsConfig,
    ScorerConfig,
    ServingConfig,
)

__all__ = [
    "CONFIG",
    "PROJECT_ROOT",
    "Config",
    "Device",
    "EmbeddingModel",
    "FeaturizerConfig",
    "LoaderConfig",
    "MlflowConfig",
    "PathsConfig",
    "ScorerConfig",
    "ServingConfig",
    "discover_project_root",
]
