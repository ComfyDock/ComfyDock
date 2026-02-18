"""Public model types for ComfyGit Core."""

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, str] = {
    "ComfyDockError": "exceptions",
    "CDWorkspaceError": "exceptions",
    "CDEnvironmentError": "exceptions",
    "CDNodeNotFoundError": "exceptions",
    "CDRegistryError": "exceptions",
    "NodeInfo": "shared",
    "ModelInfo": "shared",
    "ModelWithLocation": "shared",
    "NodePackage": "shared",
    "UpdateResult": "shared",
    "NodeRemovalResult": "shared",
    "ManagerStatus": "shared",
    "ManagerUpdateResult": "shared",
    "ModelSourceStatus": "shared",
    "ModelSourceResult": "shared",
    "OverlayConfig": "overlay",
    "SyncResult": "sync",
    "APICredentials": "workspace_config",
    "ModelDirectory": "workspace_config",
    "WorkspaceConfig": "workspace_config",
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
