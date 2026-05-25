"""Public workflow analysis and contract execution API."""

from .analyzers.workflow_dependency_parser import WorkflowDependencyParser
from .services.workflow_analysis_service import AnalysisReport, WorkflowAnalysisService
from .services.workflow_execution import (
    build_contract_prompt,
    build_manifest_contract_prompt,
    extract_contract_outputs,
)
from .services.workflow_input import detect_workflow_input_format, normalize_workflow_input
from .strategies.auto import AutoModelStrategy, AutoNodeStrategy
from .utils.input_signature import (
    create_node_key,
    normalize_registry_inputs,
    normalize_workflow_inputs,
)

__all__ = [
    "AnalysisReport",
    "AutoModelStrategy",
    "AutoNodeStrategy",
    "WorkflowDependencyParser",
    "WorkflowAnalysisService",
    "build_contract_prompt",
    "build_manifest_contract_prompt",
    "create_node_key",
    "detect_workflow_input_format",
    "extract_contract_outputs",
    "normalize_registry_inputs",
    "normalize_workflow_input",
    "normalize_workflow_inputs",
]
