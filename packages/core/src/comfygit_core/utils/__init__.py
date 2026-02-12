"""Utility modules for low-level helpers and system integration."""

from importlib import import_module
from types import ModuleType

_SUBMODULES = {
    "dependency_parser",
    "dependency_probe",
    "filesystem",
    "git",
    "pytorch",
    "pytorch_prober",
    "retry",
    "symlink_utils",
    "uv_error_handler",
    "version",
}

__all__ = sorted(_SUBMODULES)


def __getattr__(name: str) -> ModuleType:
    if name not in _SUBMODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{name}")
    globals()[name] = module
    return module


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

