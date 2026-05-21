"""Configuration and reference data for ComfyGit Core."""

from .comfyui_builtin_nodes import COMFYUI_BUILTIN_NODES
from .comfyui_models import COMFYUI_MODELS_CONFIG, MULTI_MODEL_WIDGET_CONFIGS
from .model_config import ModelConfig, ModelLoaderWidgetMapping
from .package_config import PackageConfigManager

__all__ = [
    "COMFYUI_BUILTIN_NODES",
    "COMFYUI_MODELS_CONFIG",
    "MULTI_MODEL_WIDGET_CONFIGS",
    "ModelConfig",
    "ModelLoaderWidgetMapping",
    "PackageConfigManager",
]
