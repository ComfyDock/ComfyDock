"""Repository layer for persistence and data access."""

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, str] = {
    "migrate_path_separators": "migrate_paths",
    "ModelRepository": "model_repository",
    "NodeMappingsRepository": "node_mappings_repository",
    "WorkflowRepository": "workflow_repository",
    "WorkspaceConfigRepository": "workspace_config_repository",
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

