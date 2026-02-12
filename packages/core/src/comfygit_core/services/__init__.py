"""Service layer for lookup, download, and import analysis workflows."""

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, str] = {
    "ParsedHuggingFaceUrl": "huggingface_url",
    "parse_huggingface_url": "huggingface_url",
    "ModelAnalysis": "import_analyzer",
    "NodeAnalysis": "import_analyzer",
    "WorkflowAnalysis": "import_analyzer",
    "ImportAnalysis": "import_analyzer",
    "ImportAnalyzer": "import_analyzer",
    "DownloadRequest": "model_downloader",
    "DownloadResult": "model_downloader",
    "ModelDownloader": "model_downloader",
    "NodeLookupService": "node_lookup_service",
    "RegistryDataManager": "registry_data_manager",
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

