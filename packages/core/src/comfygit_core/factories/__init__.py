"""Factories for workspace, environment, and UV manager construction."""

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, str] = {
    "EnvironmentFactory": "environment_factory",
    "WorkspaceFactory": "workspace_factory",
    "create_uv_for_environment": "uv_factory",
    "get_uv_cache_paths": "uv_factory",
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

