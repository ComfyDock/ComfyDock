"""ComfyGit Core public API."""

from importlib import import_module
from importlib.metadata import version
from typing import Any

try:
    __version__ = version("comfygit-core")
except Exception:
    __version__ = "unknown"

_EXPORTS: dict[str, str] = {
    "Environment": "core.environment",
    "Workspace": "core.workspace",
}

__all__ = ["Environment", "Workspace", "__version__"]


def __getattr__(name: str) -> Any:
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_path}")
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
