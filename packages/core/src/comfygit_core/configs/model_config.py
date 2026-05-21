"""Model configuration loader and utilities."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from ..logging.logging_config import get_logger
from .comfyui_models import COMFYUI_MODELS_CONFIG, MULTI_MODEL_WIDGET_CONFIGS

logger = get_logger(__name__)


@dataclass(frozen=True)
class ModelLoaderWidgetMapping:
    """Model selector widget metadata for a ComfyUI loader node."""

    widget_name: str | None
    widget_index: int | None
    directories: list[str]
    source: str = "static"


@dataclass
class ModelConfig:
    """ComfyUI model configuration."""

    version: str
    default_extensions: list[str]
    standard_directories: list[str]
    directory_overrides: dict[str, dict[str, Any]]
    node_directory_mappings: dict[str, list[str]]
    node_widget_indices: dict[str, int]
    node_model_loader_widgets: dict[str, list[ModelLoaderWidgetMapping]] = field(default_factory=dict)

    @classmethod
    def load(
        cls, config_path: Path | None = None, cec_path: Path | None = None
    ) -> ModelConfig:
        """Load model configuration, optionally with environment-specific overrides.

        Args:
            config_path: Path to explicit config file (for testing)
            cec_path: Path to environment's .cec directory. If provided and
                      comfyui_folder_paths.json exists, merges dynamic folder
                      mappings into the configuration.

        Returns:
            ModelConfig instance
        """
        # Load base config (static or explicit)
        data: dict[str, Any]
        if config_path is None:
            data = cast(dict[str, Any], copy.deepcopy(COMFYUI_MODELS_CONFIG))
        else:
            if not config_path.exists():
                raise FileNotFoundError(f"Model config file not found: {config_path}")
            try:
                with open(config_path, encoding='utf-8') as f:
                    data = cast(dict[str, Any], json.load(f))
            except Exception as e:
                logger.error(f"Failed to load model config from {config_path}: {e}")
                raise

        # Apply environment-specific folder mappings if available
        folder_data: dict[str, Any] | None = None
        if cec_path:
            folder_paths_file = cec_path / "comfyui_folder_paths.json"
            if folder_paths_file.exists():
                try:
                    with open(folder_paths_file, encoding='utf-8') as f:
                        folder_data = json.load(f)

                    # Merge folder_mappings into node_directory_mappings
                    data = cls._merge_folder_mappings(data, folder_data)
                    logger.debug(
                        f"Loaded dynamic folder mappings from {folder_paths_file.name}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to load folder mappings: {e}")

            model_loaders_file = cec_path / "comfyui_model_loaders.json"
            if model_loaders_file.exists():
                try:
                    with open(model_loaders_file, encoding='utf-8') as f:
                        loader_data = json.load(f)

                    data = cls._merge_model_loader_mappings(data, loader_data)
                    if folder_data:
                        data = cls._merge_folder_mappings(data, folder_data)
                    logger.debug(
                        f"Loaded generated model loader mappings from {model_loaders_file.name}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to load model loader mappings: {e}")

        loader_widgets = cls._build_model_loader_widgets(data)

        return cls(
            version=data.get("version", "unknown"),
            default_extensions=data.get("default_extensions", []),
            standard_directories=data.get("standard_directories", []),
            directory_overrides=data.get("directory_overrides", {}),
            node_directory_mappings=data.get("node_directory_mappings", {}),
            node_widget_indices=data.get("node_widget_indices", {}),
            node_model_loader_widgets=loader_widgets,
        )

    @staticmethod
    def _append_unique(items: list[str], value: str) -> None:
        if value and value not in items:
            items.append(value)

    @staticmethod
    def _build_folder_group_index(folder_mappings: dict[str, list[str]]) -> dict[str, list[str]]:
        dir_to_group: dict[str, list[str]] = {}
        for folder_key, directories in folder_mappings.items():
            dir_group: list[str] = []
            ModelConfig._append_unique(dir_group, folder_key)
            for directory in directories:
                ModelConfig._append_unique(dir_group, directory)
            for dir_name in dir_group:
                if dir_name not in dir_to_group:
                    dir_to_group[dir_name] = list(dir_group)
        return dir_to_group

    @staticmethod
    def _expand_directories(directories: list[str], dir_to_group: dict[str, list[str]]) -> list[str]:
        expanded_dirs: list[str] = []
        for dir_name in directories:
            related_dirs = dir_to_group.get(dir_name, [dir_name])
            for related_dir in related_dirs:
                ModelConfig._append_unique(expanded_dirs, related_dir)
        return expanded_dirs

    @staticmethod
    def _merge_folder_mappings(base_config: dict, folder_data: dict) -> dict:
        """Merge extracted folder mappings into base config.

        The folder_data contains:
        - folder_mappings: {folder_key: [dir1, dir2, ...]}
        - legacy_aliases: {old_key: new_key}

        We update node_directory_mappings to expand each directory to include
        all related directories from folder_mappings.

        For example, if CLIPLoader currently maps to ["clip"], and
        folder_mappings["text_encoders"] = ["text_encoders", "clip"],
        then CLIPLoader should get ["text_encoders", "clip"] because
        "clip" appears in that folder mapping.

        Args:
            base_config: The base model config dictionary
            folder_data: The extracted folder_paths data

        Returns:
            New config dict with expanded node_directory_mappings
        """
        config = copy.deepcopy(base_config)
        folder_mappings = folder_data.get("folder_mappings", {})

        # Build reverse index: directory -> all directories in same folder group
        dir_to_group = ModelConfig._build_folder_group_index(folder_mappings)

        # Treat active ComfyUI folder keys and aliases as standard directories.
        standard_directories = list(config.get("standard_directories", []))
        for folder_key, directories in folder_mappings.items():
            ModelConfig._append_unique(standard_directories, folder_key)
            for directory in directories:
                ModelConfig._append_unique(standard_directories, directory)
        config["standard_directories"] = standard_directories

        # Update node_directory_mappings to use all valid directories
        node_mappings = dict(config.get("node_directory_mappings", {}))

        for node_type, current_dirs in node_mappings.items():
            # Expand each directory to include all related directories
            node_mappings[node_type] = ModelConfig._expand_directories(
                current_dirs,
                dir_to_group,
            )

        config["node_directory_mappings"] = node_mappings

        loader_widgets = copy.deepcopy(config.get("model_loader_widgets", {}))
        for widgets in loader_widgets.values():
            for widget in widgets:
                directories = widget.get("directories", [])
                widget["directories"] = ModelConfig._expand_directories(
                    directories,
                    dir_to_group,
                )
        config["model_loader_widgets"] = loader_widgets
        return config

    @staticmethod
    def _merge_model_loader_mappings(base_config: dict, loader_data: dict) -> dict:
        """Merge generated model loader widget metadata into base config."""
        config = copy.deepcopy(base_config)
        generated_loaders = loader_data.get("model_loaders", {})
        if not isinstance(generated_loaders, dict):
            return config

        node_mappings = dict(config.get("node_directory_mappings", {}))
        widget_indices = dict(config.get("node_widget_indices", {}))
        loader_widgets = copy.deepcopy(config.get("model_loader_widgets", {}))

        for node_type, widgets in generated_loaders.items():
            if not isinstance(widgets, list):
                continue

            normalized_widgets = []
            node_directories: list[str] = []
            for widget in widgets:
                if not isinstance(widget, dict):
                    continue
                directories = [
                    directory
                    for directory in widget.get("directories", [])
                    if isinstance(directory, str) and directory
                ]
                if not directories:
                    continue

                for directory in directories:
                    ModelConfig._append_unique(node_directories, directory)

                widget_index = widget.get("widget_index")
                normalized_widgets.append({
                    "widget_name": widget.get("widget_name"),
                    "widget_index": widget_index if isinstance(widget_index, int) else None,
                    "directories": directories,
                    "source": widget.get("source", "generated"),
                })

            if not normalized_widgets:
                continue

            loader_widgets[node_type] = normalized_widgets
            existing_dirs = list(node_mappings.get(node_type, []))
            for directory in node_directories:
                ModelConfig._append_unique(existing_dirs, directory)
            node_mappings[node_type] = existing_dirs

            first_index = next(
                (
                    widget["widget_index"]
                    for widget in normalized_widgets
                    if widget["widget_index"] is not None
                ),
                None,
            )
            if first_index is not None:
                widget_indices[node_type] = first_index

        config["node_directory_mappings"] = node_mappings
        config["node_widget_indices"] = widget_indices
        config["model_loader_widgets"] = loader_widgets
        return config

    @staticmethod
    def _build_model_loader_widgets(data: dict) -> dict[str, list[ModelLoaderWidgetMapping]]:
        """Build model loader widget metadata with static fallback mappings."""
        configured_widgets = copy.deepcopy(data.get("model_loader_widgets", {}))
        node_mappings = data.get("node_directory_mappings", {})
        node_widget_indices = data.get("node_widget_indices", {})

        for node_type, directories in node_mappings.items():
            if node_type in configured_widgets:
                continue

            if node_type in MULTI_MODEL_WIDGET_CONFIGS:
                configured_widgets[node_type] = [
                    {
                        "widget_name": None,
                        "widget_index": widget_index,
                        "directories": directories,
                        "source": "static",
                    }
                    for widget_index in MULTI_MODEL_WIDGET_CONFIGS[node_type]
                ]
            else:
                configured_widgets[node_type] = [{
                    "widget_name": None,
                    "widget_index": node_widget_indices.get(node_type, 0),
                    "directories": directories,
                    "source": "static",
                }]

        result: dict[str, list[ModelLoaderWidgetMapping]] = {}
        for node_type, widgets in configured_widgets.items():
            result[node_type] = []
            for widget in widgets:
                if not isinstance(widget, dict):
                    continue
                directories = [
                    directory
                    for directory in widget.get("directories", [])
                    if isinstance(directory, str) and directory
                ]
                if not directories:
                    continue
                widget_index = widget.get("widget_index")
                result[node_type].append(
                    ModelLoaderWidgetMapping(
                        widget_name=widget.get("widget_name"),
                        widget_index=widget_index if isinstance(widget_index, int) else None,
                        directories=directories,
                        source=widget.get("source", "static"),
                    )
                )

        return result

    def get_extensions_for_directory(self, directory: str) -> list[str]:
        """Get file extensions for a specific directory.

        Args:
            directory: Directory name (e.g., "checkpoints")

        Returns:
            List of supported extensions for this directory
        """
        if directory in self.directory_overrides:
            override = self.directory_overrides[directory]
            if "extensions" in override:
                return override["extensions"]

        return self.default_extensions

    def is_standard_directory(self, directory: str) -> bool:
        """Check if a directory is a standard ComfyUI directory.

        Args:
            directory: Directory name to check

        Returns:
            True if it's a standard directory, False for custom
        """
        return directory in self.standard_directories

    def is_model_file(self, file_path: Path) -> bool:
        """Check if a file is a potential model file based on extension.

        Args:
            file_path: Path to file to check

        Returns:
            True if file has a model extension
        """
        extension = file_path.suffix.lower()

        # Get directory from path to check for specific extensions
        parts = file_path.parts
        for part in parts:
            if self.is_standard_directory(part):
                return extension in self.get_extensions_for_directory(part)

        # Default to checking against default extensions
        return extension in self.default_extensions

    def get_directories_for_node(self, node_type: str) -> list[str]:
        """Get model directories for a node type.

        Args:
            node_type: ComfyUI node type (e.g., "LoraLoader")

        Returns:
            List of directories this node type loads from
        """
        return self.node_directory_mappings.get(node_type, [])

    def get_widget_index_for_node(self, node_type: str) -> int:
        """Get widget index containing model path for a node type.

        Args:
            node_type: ComfyUI node type

        Returns:
            Index in widgets_values containing the model path (defaults to 0)
        """
        return self.node_widget_indices.get(node_type, 0)

    def get_model_loader_widgets(self, node_type: str) -> list[ModelLoaderWidgetMapping]:
        """Get model selector widgets for a node type."""
        return self.node_model_loader_widgets.get(node_type, [])

    def is_model_loader_node(self, node_type: str) -> bool:
        """Check if a node type is a known model loader.

        Args:
            node_type: ComfyUI node type

        Returns:
            True if node type loads models
        """
        return node_type in self.node_directory_mappings

    def reconstruct_model_path(self, node_type: str, widget_value: str) -> list[str]:
        """Reconstruct full model paths from node type and widget value.

        Args:
            node_type: ComfyUI node type
            widget_value: Value from node's widgets_values

        Returns:
            List of possible full relative paths
        """
        directories = self.get_directories_for_node(node_type)
        if not directories:
            return []

        return [f"{directory}/{widget_value}" for directory in directories]
