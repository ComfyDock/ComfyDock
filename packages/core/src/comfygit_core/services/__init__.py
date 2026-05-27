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
    "import_unmanaged_comfyui_environment": "unmanaged_environment_import",
    "detect_workflow_input_format": "workflow_input",
    "normalize_workflow_input": "workflow_input",
    "build_contract_prompt": "workflow_execution",
    "build_manifest_contract_prompt": "workflow_execution",
    "extract_contract_outputs": "workflow_execution",
    "ResolutionContext": "workflow_resolution_service",
    "WorkflowResolutionService": "workflow_resolution_service",
    "AnalysisReport": "workflow_analysis_service",
    "WorkflowAnalysisService": "workflow_analysis_service",
    "ModelSourceCandidate": "model_source_lookup",
    "ModelSourceLookupService": "model_source_lookup",
    "build_environment_readiness": "environment_readiness",
    "build_readiness_context": "environment_readiness",
    "build_readiness_from_context": "environment_readiness",
    "collect_model_source_warnings": "environment_readiness",
    "collect_node_provenance_warnings": "environment_readiness",
    "model_has_sources": "environment_readiness",
    "model_source_candidates": "environment_readiness",
    "node_criticality": "environment_readiness",
    "node_has_portable_provenance": "environment_readiness",
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
