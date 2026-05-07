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
)


def _txt2img_api_prompt() -> dict:
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "seed": 733306923873351,
                "steps": 20,
                "cfg": 8,
                "sampler_name": "euler",
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {
                "ckpt_name": "model.safetensors",
            },
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "old prompt",
            },
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["3", 0],
                "filename_prefix": "ComfyGit",
            },
        },
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
                field_key="seed",
                default=733306923873351,
            ),
            WorkflowContractInput(
                name="steps",
                type="number",
                node_id="3",
                required=True,
                widget_idx=2,
                field_key="steps",
                default=20,
            ),
            WorkflowContractInput(
                name="cfg",
                type="number",
                node_id="3",
                required=True,
                widget_idx=3,
                field_key="cfg",
                default=8,
            ),
            WorkflowContractInput(
                name="prompt",
                type="string",
                node_id="6",
                required=required_prompt,
                widget_idx=0,
                field_key="text",
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


def test_build_contract_prompt_applies_values_by_api_input_key() -> None:
    result = build_contract_prompt(
        "simple",
        _txt2img_api_prompt(),
        _contract(),
        {"prompt": "new prompt", "steps": "30", "cfg": "7.5"},
    )

    assert result.is_ready
    assert result.prompt["6"]["inputs"]["text"] == "new prompt"
    assert result.prompt["3"]["inputs"]["steps"] == 30
    assert result.prompt["3"]["inputs"]["cfg"] == 7.5
    assert [item.name for item in result.applied_inputs] == ["seed", "steps", "cfg", "prompt"]


def test_build_contract_prompt_uses_concrete_api_binding_for_subgraph_input() -> None:
    api_prompt = {
        "170:151": {
            "class_type": "TextEncodeQwenImageEditPlus",
            "inputs": {"prompt": "old prompt"},
        },
        "170:169": {
            "class_type": "KSampler",
            "inputs": {"seed": 4},
        },
    }
    contract = NamedWorkflowContract(
        inputs=[
            WorkflowContractInput(
                name="prompt",
                type="string",
                node_id="170",
                widget_idx=0,
                field_key="prompt",
                api_node_id="170:151",
                api_field_key="prompt",
                required=True,
            ),
            WorkflowContractInput(
                name="seed",
                type="integer",
                node_id="170",
                widget_idx=6,
                field_key="seed",
                api_node_id="170:169",
                api_field_key="seed",
                required=True,
                default=4,
            ),
        ]
    )

    result = build_contract_prompt(
        "subgraph",
        api_prompt,
        contract,
        {"prompt": "new prompt", "seed": 123},
    )

    assert result.is_ready
    assert result.prompt["170:151"]["inputs"]["prompt"] == "new prompt"
    assert result.prompt["170:169"]["inputs"]["seed"] == 123
    assert [(item.name, item.node_id, item.input_key) for item in result.applied_inputs] == [
        ("prompt", "170:151", "prompt"),
        ("seed", "170:169", "seed"),
    ]


def test_build_contract_prompt_reports_missing_required_input_without_default() -> None:
    result = build_contract_prompt("simple", _txt2img_api_prompt(), _contract(), {})

    assert not result.is_ready
    assert [issue.code for issue in result.issues] == ["missing_required_input"]


def test_build_contract_prompt_warns_for_unknown_inputs() -> None:
    result = build_contract_prompt(
        "simple",
        _txt2img_api_prompt(),
        NamedWorkflowContract(),
        {"extra": "ignored"},
    )

    assert result.is_ready
    assert result.issues[0].code == "unknown_contract_input"
    assert result.issues[0].severity == "warning"


def test_build_manifest_contract_prompt_loads_workflow_from_snapshot(tmp_path: Path) -> None:
    api_dir = tmp_path / "workflow_api"
    api_dir.mkdir()
    api_path = api_dir / "simple.api.json"
    api_path.write_text(json.dumps(_txt2img_api_prompt()), encoding="utf-8")

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
        WorkflowExecutionContract(
            contracts={"default": _contract()},
            api_prompt_file="workflow_api/simple.api.json",
            api_prompt_source="comfyui_frontend",
        ),
    )

    result = build_manifest_contract_prompt(
        manager.get_manifest_snapshot(),
        tmp_path,
        "simple",
        {"prompt": "manifest prompt"},
    )

    assert result.is_ready
    assert result.prompt["6"]["inputs"]["text"] == "manifest prompt"


def test_build_manifest_contract_prompt_requires_stored_api_prompt(tmp_path: Path) -> None:
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

    with pytest.raises(ValueError, match="captured API prompt"):
        build_manifest_contract_prompt(
            manager.get_manifest_snapshot(),
            tmp_path,
            "simple",
            {"prompt": "manifest prompt"},
        )


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


def test_extract_video_contract_outputs_from_comfyui_images_history_key() -> None:
    contract = NamedWorkflowContract(
        outputs=[
            WorkflowContractOutput(
                name="save_video",
                type="video",
                node_id="341",
                selector="primary",
            )
        ]
    )
    history_entry = {
        "outputs": {
            "341": {
                "images": [
                    {
                        "filename": "LTX_2.3_ia2v_00005_.mp4",
                        "subfolder": "video",
                        "type": "output",
                    }
                ],
                "animated": [True],
            }
        }
    }

    outputs = extract_contract_outputs(contract.outputs, history_entry)

    assert len(outputs) == 1
    assert outputs[0].name == "save_video"
    assert outputs[0].type == "video"
    assert outputs[0].artifacts[0].filename == "LTX_2.3_ia2v_00005_.mp4"
    assert outputs[0].artifacts[0].subfolder == "video"
