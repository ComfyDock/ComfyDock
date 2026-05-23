"""Manager APIs for orchestrating environment operations."""

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, str] = {
    "EnvironmentGitOrchestrator": "environment_git_orchestrator",
    "EnvironmentModelManager": "environment_model_manager",
    "ExportImportManager": "export_import_manager",
    "GitManager": "git_manager",
    "ModelSymlinkManager": "model_symlink_manager",
    "NodeManager": "node_manager",
    "OverlayManager": "overlay_manager",
    "PyprojectManager": "pyproject_manager",
    "PyTorchBackendManager": "pytorch_backend_manager",
    "SystemNodeSymlinkManager": "system_node_symlink_manager",
    "UserContentSymlinkManager": "user_content_symlink_manager",
    "UVProjectManager": "uv_project_manager",
    "WorkflowManager": "workflow_manager",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
