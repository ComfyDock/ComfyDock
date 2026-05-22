"""Public workflow analysis and contract execution API."""

from .services.workflow_analysis_service import AnalysisReport, WorkflowAnalysisService
from .services.workflow_execution import (
    build_contract_prompt,
    build_manifest_contract_prompt,
    extract_contract_outputs,
)
from .services.workflow_input import detect_workflow_input_format, normalize_workflow_input

__all__ = [
    "AnalysisReport",
    "WorkflowAnalysisService",
    "build_contract_prompt",
    "build_manifest_contract_prompt",
    "detect_workflow_input_format",
    "extract_contract_outputs",
    "normalize_workflow_input",
]
