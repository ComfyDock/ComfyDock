"""Analysis utilities for node, workflow, git, and status inspection."""

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, str] = {
    "flatten_nodes": "config_comparison",
    "extract_nodes_section": "config_comparison",
    "extract_models_section": "config_comparison",
    "compare_node_configs": "config_comparison",
    "compare_constraint_configs": "config_comparison",
    "NodeDependencies": "custom_node_scanner",
    "CustomNodeScanner": "custom_node_scanner",
    "GitChangeParser": "git_change_parser",
    "ModelProcessResult": "model_scanner",
    "ScanResult": "model_scanner",
    "ModelScanProgress": "model_scanner",
    "ModelScanner": "model_scanner",
    "NodeClassifierResultMulti": "node_classifier",
    "NodeClassifier": "node_classifier",
    "get_node_git_info": "node_git_analyzer",
    "RefDiffAnalyzer": "ref_diff_analyzer",
    "StatusScanner": "status_scanner",
    "detect_unmanaged_comfyui_path": "unmanaged_comfyui_analyzer",
    "scan_unmanaged_comfyui": "unmanaged_comfyui_analyzer",
    "WorkflowDependencyParser": "workflow_dependency_parser",
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
