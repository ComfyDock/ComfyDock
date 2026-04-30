"""Tests for workflow contract prompt preparation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomlkit

from comfygit_core.managers.pyproject_manager import PyprojectManager
from comfygit_core.models.workflow_contract import (
    NamedWorkflowContract,
    WorkflowContractInput,
    WorkflowContractOutput,
    WorkflowExecutionContract,
)
from comfygit_core.services.workflow_execution import (
    build_contract_prompt,
    build_manifest_contract_prompt,
    extract_contract_outputs,
    workflow_to_api_prompt,
)
from comfygit_core.services.workflow_input import normalize_workflow_input


def _txt2img_workflow() -> dict:
    return {
        "nodes": [
            {
                "id": 4,
                "type": "CheckpointLoaderSimple",
                "inputs": [
                    {"name": "ckpt_name", "type": "COMBO", "widget": {"name": "ckpt_name"}},
                ],
                "outputs": [
                    {"name": "MODEL", "type": "MODEL", "links": [1], "slot_index": 0},
                    {"name": "CLIP", "type": "CLIP", "links": [3], "slot_index": 1},
                    {"name": "VAE", "type": "VAE", "links": [8], "slot_index": 2},
                ],
                "widgets_values": ["model.safetensors"],
            },
            {
                "id": 3,
                "type": "KSampler",
                "inputs": [
                    {"name": "model", "type": "MODEL", "link": 1},
                    {"name": "seed", "type": "INT", "widget": {"name": "seed"}},
                    {"name": "steps", "type": "INT", "widget": {"name": "steps"}},
                    {"name": "cfg", "type": "FLOAT", "widget": {"name": "cfg"}},
                    {"name": "sampler_name", "type": "COMBO", "widget": {"name": "sampler_name"}},
                ],
                "outputs": [{"name": "LATENT", "type": "LATENT", "links": [7], "slot_index": 0}],
                "widgets_values": [733306923873351, "randomize", 20, 8, "euler"],
            },
            {
                "id": 9,
                "type": "SaveImage",
                "inputs": [
                    {"name": "images", "type": "IMAGE", "link": 7},
                    {"name": "filename_prefix", "type": "STRING", "widget": {"name": "filename_prefix"}},
                ],
                "outputs": [],
                "widgets_values": ["ComfyGit"],
            },
            {
                "id": 11,
                "type": "MarkdownNote",
                "widgets_values": ["This is editor-only help text."],
            },
        ],
        "links": [
            [1, 4, 0, 3, 0, "MODEL"],
            [7, 3, 0, 9, 0, "IMAGE"],
        ],
    }


def _contract(*, required_prompt: bool = True) -> NamedWorkflowContract:
    return NamedWorkflowContract(
        inputs=[
            WorkflowContractInput(
                name="seed",
                type="number",
                node_id="3",
                required=True,
                widget_idx=0,
                default=733306923873351,
            ),
            WorkflowContractInput(
                name="steps",
                type="number",
                node_id="3",
                required=True,
                widget_idx=2,
                default=20,
            ),
            WorkflowContractInput(
                name="cfg",
                type="number",
                node_id="3",
                required=True,
                widget_idx=3,
                default=8,
            ),
            WorkflowContractInput(
                name="prompt",
                type="string",
                node_id="6",
                required=required_prompt,
                widget_idx=0,
            ),
        ],
        outputs=[
            WorkflowContractOutput(
                name="image",
                type="image",
                node_id="9",
                selector="primary",
            )
        ],
    )


def test_workflow_to_api_prompt_resolves_links_and_skips_ui_only_widgets() -> None:
    workflow = normalize_workflow_input(_txt2img_workflow())

    prompt, widget_map = workflow_to_api_prompt(workflow)

    assert "11" not in prompt
    assert prompt["3"]["inputs"]["model"] == ["4", 0]
    assert prompt["3"]["inputs"]["seed"] == 733306923873351
    assert prompt["3"]["inputs"]["steps"] == 20
    assert prompt["3"]["inputs"]["cfg"] == 8
    assert prompt["3"]["inputs"]["sampler_name"] == "euler"
    assert widget_map["3"] == {
        0: "seed",
        2: "steps",
        3: "cfg",
        4: "sampler_name",
    }


def test_build_contract_prompt_applies_values_by_original_widget_index() -> None:
    workflow_data = _txt2img_workflow()
    workflow_data["nodes"].append(
        {
            "id": 6,
            "type": "CLIPTextEncode",
            "inputs": [{"name": "text", "type": "STRING", "widget": {"name": "text"}}],
            "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [], "slot_index": 0}],
            "widgets_values": ["old prompt"],
        }
    )

    result = build_contract_prompt(
        "simple",
        workflow_data,
        _contract(),
        {"prompt": "new prompt", "steps": "30", "cfg": "7.5"},
    )

    assert result.is_ready
    assert result.prompt["6"]["inputs"]["text"] == "new prompt"
    assert result.prompt["3"]["inputs"]["steps"] == 30
    assert result.prompt["3"]["inputs"]["cfg"] == 7.5
    assert [item.name for item in result.applied_inputs] == ["seed", "steps", "cfg", "prompt"]


def test_build_contract_prompt_reports_missing_required_input_without_default() -> None:
    workflow_data = _txt2img_workflow()
    workflow_data["nodes"].append(
        {
            "id": 6,
            "type": "CLIPTextEncode",
            "inputs": [{"name": "text", "type": "STRING", "widget": {"name": "text"}}],
            "outputs": [],
            "widgets_values": ["old prompt"],
        }
    )

    result = build_contract_prompt("simple", workflow_data, _contract(), {})

    assert not result.is_ready
    assert [issue.code for issue in result.issues] == ["missing_required_input"]


def test_build_contract_prompt_warns_for_unknown_inputs() -> None:
    result = build_contract_prompt(
        "simple",
        _txt2img_workflow(),
        NamedWorkflowContract(),
        {"extra": "ignored"},
    )

    assert result.is_ready
    assert result.issues[0].code == "unknown_contract_input"
    assert result.issues[0].severity == "warning"


def test_build_manifest_contract_prompt_loads_workflow_from_snapshot(tmp_path: Path) -> None:
    workflow_dir = tmp_path / "workflows"
    workflow_dir.mkdir()
    workflow_path = workflow_dir / "simple.json"
    workflow_data = _txt2img_workflow()
    workflow_data["nodes"].append(
        {
            "id": 6,
            "type": "CLIPTextEncode",
            "inputs": [{"name": "text", "type": "STRING", "widget": {"name": "text"}}],
            "outputs": [],
            "widgets_values": ["old prompt"],
        }
    )
    workflow_path.write_text(json.dumps(workflow_data), encoding="utf-8")

    pyproject_path = tmp_path / "pyproject.toml"
    with pyproject_path.open("w", encoding="utf-8") as handle:
        tomlkit.dump(
            {
                "project": {
                    "name": "demo",
                    "version": "0.1.0",
                    "requires-python": ">=3.11",
                    "dependencies": [],
                },
                "tool": {
                    "comfygit": {
                        "comfyui_version": "v0.3.60",
                        "python_version": "3.11",
                    }
                },
            },
            handle,
        )
    manager = PyprojectManager(pyproject_path)
    manager.workflows.add_workflow("simple")
    manager.workflows.set_execution_contract(
        "simple",
        WorkflowExecutionContract(contracts={"default": _contract()}),
    )

    result = build_manifest_contract_prompt(
        manager.get_manifest_snapshot(),
        tmp_path,
        "simple",
        {"prompt": "manifest prompt"},
    )

    assert result.is_ready
    assert result.prompt["6"]["inputs"]["text"] == "manifest prompt"


def test_build_manifest_contract_prompt_rejects_unknown_workflow(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    with pyproject_path.open("w", encoding="utf-8") as handle:
        tomlkit.dump(
            {
                "project": {
                    "name": "demo",
                    "version": "0.1.0",
                    "requires-python": ">=3.11",
                    "dependencies": [],
                },
                "tool": {
                    "comfygit": {
                        "comfyui_version": "v0.3.60",
                        "python_version": "3.11",
                    }
                },
            },
            handle,
        )
    manager = PyprojectManager(pyproject_path)

    with pytest.raises(ValueError, match="not tracked"):
        build_manifest_contract_prompt(manager.get_manifest_snapshot(), tmp_path, "missing", {})


def test_extract_contract_outputs_from_comfyui_history() -> None:
    contract = _contract()
    history_entry = {
        "outputs": {
            "9": {
                "images": [
                    {
                        "filename": "ComfyGit_00001_.png",
                        "subfolder": "",
                        "type": "output",
                    }
                ]
            }
        }
    }

    outputs = extract_contract_outputs(contract.outputs, history_entry)

    assert len(outputs) == 1
    assert outputs[0].name == "image"
    assert outputs[0].node_id == "9"
    assert outputs[0].artifacts[0].filename == "ComfyGit_00001_.png"
