"""Typed inputs and results for headless environment materialization."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ModelMaterializationStrategy = Literal["all", "required", "skip"]
MaterializeSourceType = Literal["bundle", "directory", "git"]


@dataclass(frozen=True)
class MaterializeOptions:
    """Options for hydrating a portable ComfyGit environment into runtime state."""

    source: str | Path
    name: str
    workspace_path: Path | None = None
    branch: str | None = None
    models_dir: Path | None = None
    model_strategy: ModelMaterializationStrategy = "skip"
    torch_backend: str = "auto"
    no_manager: bool = True
    set_active: bool = False
    replace: bool = False
    fail_on_sync_errors: bool = True
    create_import_commit: bool = False


@dataclass(frozen=True)
class MaterializeResult:
    """Result of a successful materialization operation."""

    environment_name: str
    workspace_path: Path
    environment_path: Path
    cec_path: Path
    comfyui_path: Path
    source_type: MaterializeSourceType
    model_strategy: ModelMaterializationStrategy
    torch_backend: str | None
