"""Build ComfyUI API prompts from stored workflow execution contract artifacts."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from comfygit_core.models.manifest import EnvironmentManifestSnapshot
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


def build_contract_prompt(
    workflow_name: str,
    api_prompt_data: dict[str, Any],
    contract: NamedWorkflowContract,
    input_values: Mapping[str, Any] | None = None,
    *,
    contract_name: str = "default",
) -> ContractPromptBuildResult:
    """Patch a stored ComfyUI API prompt for a named workflow contract.

    `api_prompt_data` must already be in ComfyUI API prompt shape. Core does
    not convert UI-format workflows into API prompts.
    """

    prompt = _normalize_api_prompt_data(api_prompt_data)
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

        if prompt_node is None:
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

        input_key = _contract_input_key(contract_input)
        if input_key is None:
            issues.append(
                PromptBuildIssue(
                    code="missing_api_input_binding",
                    message=(
                        f"Contract input '{contract_input.name}' does not declare "
                        f"a stored ComfyUI API input key."
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
        if not isinstance(prompt_node_inputs, dict):
            prompt_node_inputs = {}
            prompt_node["inputs"] = prompt_node_inputs
        if input_key not in prompt_node_inputs:
            issues.append(
                PromptBuildIssue(
                    code="missing_api_input",
                    message=(
                        f"Contract input '{contract_input.name}' maps to API input "
                        f"'{input_key}', but node '{node_id}' does not contain that input."
                    ),
                    input_name=contract_input.name,
                    node_id=node_id,
                )
            )
            continue
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
    )


def build_manifest_contract_prompt(
    manifest: EnvironmentManifestSnapshot,
    manifest_dir: Path,
    workflow_name: str,
    input_values: Mapping[str, Any] | None = None,
    *,
    contract_name: str | None = None,
) -> ContractPromptBuildResult:
    """Load a stored API prompt from a manifest snapshot and prepare a contract prompt."""

    workflow_entry = manifest.workflows.get(workflow_name)
    if workflow_entry is None:
        raise ValueError(f"Workflow '{workflow_name}' is not tracked in the manifest.")
    if workflow_entry.execution_contract is None:
        raise ValueError(f"Workflow '{workflow_name}' does not declare an execution contract.")

    execution_contract = workflow_entry.execution_contract
    if not execution_contract.api_prompt_file:
        raise ValueError(
            f"Workflow '{workflow_name}' contract does not declare a captured API prompt file. "
            "Re-save the contract in ComfyGit Manager."
        )
    selected_contract_name = contract_name or execution_contract.default_contract
    contract = execution_contract.contracts.get(selected_contract_name)
    if contract is None:
        raise ValueError(
            f"Workflow '{workflow_name}' does not declare contract '{selected_contract_name}'."
        )

    api_prompt_path = _resolve_manifest_artifact_path(
        manifest_dir,
        execution_contract.api_prompt_file,
    )
    if not api_prompt_path.exists():
        raise ValueError(
            f"Workflow '{workflow_name}' contract API prompt file is missing: "
            f"{execution_contract.api_prompt_file}. Re-save the contract in ComfyGit Manager."
        )
    with api_prompt_path.open(encoding="utf-8") as handle:
        api_prompt_data = json.load(handle)

    return build_contract_prompt(
        workflow_name,
        api_prompt_data,
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


def _contract_input_key(contract_input: WorkflowContractInput) -> str | None:
    return contract_input.field_key


def _normalize_api_prompt_data(data: dict[str, Any]) -> ComfyUIPrompt:
    """Return a deep-copied ComfyUI API prompt from supported stored shapes."""
    candidate: Any = data
    if isinstance(data, dict):
        if isinstance(data.get("output"), dict):
            candidate = data["output"]
        elif isinstance(data.get("prompt"), dict):
            candidate = data["prompt"]

    if not isinstance(candidate, dict):
        raise ValueError("Stored API prompt must be a JSON object.")

    prompt: ComfyUIPrompt = {}
    for node_id, node_data in candidate.items():
        if not isinstance(node_data, dict):
            raise ValueError(f"Stored API prompt node '{node_id}' must be an object.")
        node_payload = copy.deepcopy(node_data)
        inputs = node_payload.get("inputs")
        if inputs is None:
            node_payload["inputs"] = {}
        elif not isinstance(inputs, dict):
            raise ValueError(f"Stored API prompt node '{node_id}' has non-object inputs.")
        prompt[str(node_id)] = node_payload
    return prompt


def _resolve_manifest_artifact_path(manifest_dir: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Contract API prompt path must be relative to the manifest: {relative_path}")
    return manifest_dir / path


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
