"""Build ComfyUI API prompts from workflow execution contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from comfygit_core.models.manifest import EnvironmentManifestSnapshot
from comfygit_core.models.workflow import Workflow, WorkflowNode
from comfygit_core.models.workflow_contract import (
    NamedWorkflowContract,
    WorkflowContractInput,
)
from comfygit_core.models.workflow_execution import (
    ComfyUIPrompt,
    ContractPromptBuildResult,
    ContractOutputArtifact,
    ContractOutputResult,
    PromptAppliedInput,
    PromptBuildIssue,
)
from comfygit_core.services.workflow_input import normalize_workflow_input


_VISUAL_NOTE_NODE_TYPES = {
    "Note",
    "MarkdownNote",
    "Note Plus (mtb)",
}


def workflow_to_api_prompt(workflow: Workflow) -> tuple[ComfyUIPrompt, Mapping[str, Mapping[int, str]]]:
    """Convert a parsed UI workflow to a ComfyUI API prompt.

    The returned widget map links original `widgets_values` indexes to API input
    keys. Contract inputs authored in Manager use the original widget index, so
    callers must use this map when applying contract values.
    """

    link_lookup = {
        link.id: [str(link.source_node_id), link.source_slot]
        for link in workflow.links
    }

    prompt: ComfyUIPrompt = {}
    widget_input_maps: dict[str, Mapping[int, str]] = {}

    for node_id, node in workflow.nodes.items():
        if _is_visual_note_node(node):
            continue

        api_inputs, widget_map = _node_api_inputs(node, link_lookup)
        prompt[str(node_id)] = {
            "class_type": node.type,
            "inputs": api_inputs,
        }
        widget_input_maps[str(node_id)] = MappingProxyType(widget_map)

    return prompt, MappingProxyType(widget_input_maps)


def build_contract_prompt(
    workflow_name: str,
    workflow_data: dict[str, Any],
    contract: NamedWorkflowContract,
    input_values: Mapping[str, Any] | None = None,
    *,
    contract_name: str = "default",
) -> ContractPromptBuildResult:
    """Prepare a ComfyUI API prompt for a named workflow contract."""

    workflow = normalize_workflow_input(workflow_data)
    prompt, widget_input_map = workflow_to_api_prompt(workflow)

    issues: list[PromptBuildIssue] = []
    applied_inputs: list[PromptAppliedInput] = []
    provided_inputs = dict(input_values or {})

    known_input_names = {item.name for item in contract.inputs}
    for provided_name in provided_inputs:
        if provided_name not in known_input_names:
            issues.append(
                PromptBuildIssue(
                    code="unknown_contract_input",
                    message=f"Input '{provided_name}' is not defined by contract '{contract_name}'.",
                    severity="warning",
                    input_name=provided_name,
                )
            )

    for contract_input in contract.inputs:
        node_id = str(contract_input.node_id)
        prompt_node = prompt.get(node_id)
        workflow_node = workflow.nodes.get(node_id)

        if prompt_node is None or workflow_node is None:
            issues.append(
                PromptBuildIssue(
                    code="missing_node",
                    message=(
                        f"Contract input '{contract_input.name}' references missing "
                        f"workflow node '{node_id}'."
                    ),
                    input_name=contract_input.name,
                    node_id=node_id,
                )
            )
            continue

        input_key = _contract_input_key(contract_input, workflow_node, widget_input_map)
        if input_key is None:
            issues.append(
                PromptBuildIssue(
                    code="missing_widget_binding",
                    message=(
                        f"Contract input '{contract_input.name}' does not map to "
                        f"a ComfyUI API input on node '{node_id}'."
                    ),
                    input_name=contract_input.name,
                    node_id=node_id,
                )
            )
            continue

        value, value_issues, should_apply = _resolve_contract_value(
            contract_input,
            provided_inputs,
            contract_name=contract_name,
        )
        issues.extend(value_issues)
        if not should_apply:
            continue

        prompt_node_inputs = prompt_node.setdefault("inputs", {})
        prompt_node_inputs[input_key] = value
        applied_inputs.append(
            PromptAppliedInput(
                name=contract_input.name,
                node_id=node_id,
                input_key=input_key,
                value=value,
            )
        )

    return ContractPromptBuildResult(
        workflow_name=workflow_name,
        contract_name=contract_name,
        prompt=prompt,
        outputs=tuple(contract.outputs),
        applied_inputs=tuple(applied_inputs),
        issues=tuple(issues),
        widget_input_map=widget_input_map,
    )


def build_manifest_contract_prompt(
    manifest: EnvironmentManifestSnapshot,
    manifest_dir: Path,
    workflow_name: str,
    input_values: Mapping[str, Any] | None = None,
    *,
    contract_name: str | None = None,
) -> ContractPromptBuildResult:
    """Load a workflow from a manifest snapshot and prepare a contract prompt."""

    workflow_entry = manifest.workflows.get(workflow_name)
    if workflow_entry is None:
        raise ValueError(f"Workflow '{workflow_name}' is not tracked in the manifest.")
    if workflow_entry.path is None:
        raise ValueError(f"Workflow '{workflow_name}' does not declare a workflow path.")
    if workflow_entry.execution_contract is None:
        raise ValueError(f"Workflow '{workflow_name}' does not declare an execution contract.")

    execution_contract = workflow_entry.execution_contract
    selected_contract_name = contract_name or execution_contract.default_contract
    contract = execution_contract.contracts.get(selected_contract_name)
    if contract is None:
        raise ValueError(
            f"Workflow '{workflow_name}' does not declare contract '{selected_contract_name}'."
        )

    workflow_path = manifest_dir / workflow_entry.path
    with workflow_path.open(encoding="utf-8") as handle:
        workflow_data = json.load(handle)

    return build_contract_prompt(
        workflow_name,
        workflow_data,
        contract,
        input_values,
        contract_name=selected_contract_name,
    )


def extract_contract_outputs(
    outputs: list[Any] | tuple[Any, ...],
    history_entry: Mapping[str, Any],
) -> tuple[ContractOutputResult, ...]:
    """Extract declared contract outputs from a ComfyUI history entry."""

    history_outputs = history_entry.get("outputs", {})
    if not isinstance(history_outputs, Mapping):
        history_outputs = {}

    results: list[ContractOutputResult] = []
    for output in outputs:
        node_id = str(output.node_id)
        node_outputs = history_outputs.get(node_id, {})
        if not isinstance(node_outputs, Mapping):
            node_outputs = {}

        artifacts = _extract_output_artifacts(str(output.type), node_outputs)
        results.append(
            ContractOutputResult(
                name=str(output.name),
                type=str(output.type),
                node_id=node_id,
                selector=output.selector,
                artifacts=tuple(artifacts),
            )
        )

    return tuple(results)


def _is_visual_note_node(node: WorkflowNode) -> bool:
    has_links = any(input_item.link is not None for input_item in node.inputs)
    has_output_links = any(output.links for output in node.outputs)
    return node.type in _VISUAL_NOTE_NODE_TYPES and not has_links and not has_output_links


def _extract_output_artifacts(
    output_type: str,
    node_outputs: Mapping[str, Any],
) -> list[ContractOutputArtifact]:
    output_keys = _history_output_keys(output_type)
    artifacts: list[ContractOutputArtifact] = []

    for key in output_keys:
        value = node_outputs.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, Mapping):
                artifacts.append(
                    ContractOutputArtifact(
                        filename=str(item["filename"]) if item.get("filename") is not None else None,
                        subfolder=(
                            str(item["subfolder"])
                            if item.get("subfolder") is not None
                            else None
                        ),
                        type=str(item["type"]) if item.get("type") is not None else None,
                        raw=item,
                    )
                )
            else:
                artifacts.append(ContractOutputArtifact(raw={"value": item}))

    return artifacts


def _history_output_keys(output_type: str) -> tuple[str, ...]:
    normalized_type = output_type.lower()
    if normalized_type == "image":
        return ("images",)
    if normalized_type == "video":
        return ("videos", "gifs")
    if normalized_type == "audio":
        return ("audio", "audios")
    if normalized_type == "file":
        return ("files",)
    return ("images", "videos", "gifs", "audio", "audios", "files")


def _node_api_inputs(
    node: WorkflowNode,
    link_lookup: Mapping[int, list[Any]],
) -> tuple[dict[str, Any], dict[int, str]]:
    inputs: dict[str, Any] = {}
    widget_input_map: dict[int, str] = {}
    widget_value_index = 0

    for input_item in node.inputs:
        if input_item.link is not None:
            linked_value = link_lookup.get(input_item.link)
            if linked_value is not None:
                inputs[input_item.name] = linked_value
            continue

        if not input_item.widget:
            continue

        matched_index = _next_matching_widget_index(
            node.widgets_values,
            start=widget_value_index,
            input_type=input_item.type,
        )
        if matched_index is None:
            continue

        inputs[input_item.name] = node.widgets_values[matched_index]
        widget_input_map[matched_index] = input_item.name
        widget_value_index = matched_index + 1

    return inputs, widget_input_map


def _next_matching_widget_index(
    values: list[Any],
    *,
    start: int,
    input_type: str,
) -> int | None:
    for index in range(start, len(values)):
        if _widget_value_matches_input_type(values[index], input_type):
            return index
    return None


def _widget_value_matches_input_type(value: Any, input_type: str) -> bool:
    normalized_type = input_type.upper()
    if value is None:
        return True
    if normalized_type in {"INT", "INTEGER"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if normalized_type in {"FLOAT", "NUMBER"}:
        return isinstance(value, int | float) and not isinstance(value, bool)
    if normalized_type in {"BOOLEAN", "BOOL"}:
        return isinstance(value, bool)
    if normalized_type in {"STRING", "COMBO"}:
        return isinstance(value, str)
    return True


def _contract_input_key(
    contract_input: WorkflowContractInput,
    workflow_node: WorkflowNode,
    widget_input_map: Mapping[str, Mapping[int, str]],
) -> str | None:
    if contract_input.field_key:
        return contract_input.field_key

    node_widget_map = widget_input_map.get(str(contract_input.node_id), {})
    if contract_input.widget_idx is not None:
        input_key = node_widget_map.get(contract_input.widget_idx)
        if input_key:
            return input_key

    return _workflow_node_widget_input_key(workflow_node, contract_input)


def _workflow_node_widget_input_key(
    workflow_node: WorkflowNode,
    contract_input: WorkflowContractInput,
) -> str | None:
    for input_item in workflow_node.inputs:
        if not input_item.widget:
            continue
        widget_name = input_item.widget.get("name") if isinstance(input_item.widget, dict) else None
        if widget_name == contract_input.name or input_item.name == contract_input.name:
            return input_item.name
    return None


def _resolve_contract_value(
    contract_input: WorkflowContractInput,
    provided_inputs: Mapping[str, Any],
    *,
    contract_name: str,
) -> tuple[Any, list[PromptBuildIssue], bool]:
    issues: list[PromptBuildIssue] = []
    has_provided_value = contract_input.name in provided_inputs

    if has_provided_value:
        raw_value = provided_inputs[contract_input.name]
    elif contract_input.default is not None:
        raw_value = contract_input.default
    elif contract_input.required:
        issues.append(
            PromptBuildIssue(
                code="missing_required_input",
                message=(
                    f"Required input '{contract_input.name}' is missing for "
                    f"contract '{contract_name}'."
                ),
                input_name=contract_input.name,
                node_id=str(contract_input.node_id),
            )
        )
        return None, issues, False
    else:
        return None, issues, False

    try:
        value = _coerce_contract_value(raw_value, contract_input.type)
    except (TypeError, ValueError) as exc:
        issues.append(
            PromptBuildIssue(
                code="coercion_failed",
                message=f"Input '{contract_input.name}' could not be coerced: {exc}",
                input_name=contract_input.name,
                node_id=str(contract_input.node_id),
            )
        )
        return None, issues, False

    if contract_input.enum_values and value not in contract_input.enum_values:
        issues.append(
            PromptBuildIssue(
                code="enum_value_invalid",
                message=(
                    f"Input '{contract_input.name}' must be one of "
                    f"{contract_input.enum_values}."
                ),
                input_name=contract_input.name,
                node_id=str(contract_input.node_id),
            )
        )
        return None, issues, False

    if contract_input.is_numeric and isinstance(value, int | float):
        if contract_input.min is not None and value < contract_input.min:
            issues.append(
                PromptBuildIssue(
                    code="below_min",
                    message=f"Input '{contract_input.name}' is below the minimum value.",
                    input_name=contract_input.name,
                    node_id=str(contract_input.node_id),
                )
            )
            return None, issues, False
        if contract_input.max is not None and value > contract_input.max:
            issues.append(
                PromptBuildIssue(
                    code="above_max",
                    message=f"Input '{contract_input.name}' is above the maximum value.",
                    input_name=contract_input.name,
                    node_id=str(contract_input.node_id),
                )
            )
            return None, issues, False

    return value, issues, True


def _coerce_contract_value(value: Any, input_type: str) -> Any:
    normalized_type = input_type.lower()
    if normalized_type == "string":
        return "" if value is None else str(value)
    if normalized_type == "integer":
        if isinstance(value, bool):
            raise TypeError("boolean is not an integer")
        return int(value)
    if normalized_type == "number":
        if isinstance(value, bool):
            raise TypeError("boolean is not a number")
        if isinstance(value, int | float):
            return value
        text = str(value).strip()
        if "." not in text and "e" not in text.lower():
            return int(text)
        parsed = float(text)
        return int(parsed) if parsed.is_integer() else parsed
    if normalized_type == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{value!r} is not a boolean")
    return value
