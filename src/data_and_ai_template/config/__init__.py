"""Typed configuration. `from data_and_ai_template.config import CONFIG`."""

from data_and_ai_template.config.constants import PROJECT_ROOT, discover_project_root
from data_and_ai_template.config.hyperparameters import (
    CONFIG,
    Config,
    Device,
    EmbeddingModel,
    FeaturizerConfig,
    KubeflowConfig,
    LoaderConfig,
    MlflowConfig,
    NodeResources,
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
    "KubeflowConfig",
    "LoaderConfig",
    "MlflowConfig",
    "NodeResources",
    "PathsConfig",
    "ScorerConfig",
    "ServingConfig",
    "discover_project_root",
]
