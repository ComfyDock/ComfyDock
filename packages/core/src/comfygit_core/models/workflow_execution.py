"""Typed models for workflow contract prompt preparation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from comfygit_core.models.workflow_contract import WorkflowContractOutput

ComfyUIPrompt = dict[str, dict[str, Any]]
PromptBuildIssueSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class PromptAppliedInput:
    """A contract input that was applied to a ComfyUI API prompt."""

    name: str
    node_id: str
    input_key: str
    value: Any


@dataclass(frozen=True)
class PromptBuildIssue:
    """A structured issue found while preparing a contract prompt."""

    code: str
    message: str
    severity: PromptBuildIssueSeverity = "error"
    input_name: str | None = None
    node_id: str | None = None

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


@dataclass(frozen=True)
class ContractPromptBuildResult:
    """Result of patching a stored ComfyUI API prompt for a contract request."""

    workflow_name: str
    contract_name: str
    prompt: ComfyUIPrompt
    outputs: tuple[WorkflowContractOutput, ...]
    applied_inputs: tuple[PromptAppliedInput, ...] = ()
    issues: tuple[PromptBuildIssue, ...] = ()
    widget_input_map: Mapping[str, Mapping[int, str]] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(issue.is_error for issue in self.issues)

    @property
    def is_ready(self) -> bool:
        return not self.has_errors


@dataclass(frozen=True)
class ContractOutputArtifact:
    """One artifact reference returned by ComfyUI history."""

    filename: str | None = None
    subfolder: str | None = None
    type: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContractOutputResult:
    """A declared contract output resolved from ComfyUI history."""

    name: str
    type: str
    node_id: str
    selector: str | None = None
    artifacts: tuple[ContractOutputArtifact, ...] = ()
