"""Tests for workflow input normalization."""

from __future__ import annotations

import pytest
from comfygit_core.services.workflow_input import (
    detect_workflow_input_format,
    normalize_workflow_input,
)


def test_normalize_ui_list_format() -> None:
    data = {
        "nodes": [
            {
                "id": 1,
                "type": "CheckpointLoaderSimple",
                "widgets_values": ["model.safetensors"],
            }
        ],
        "links": [],
    }

    workflow = normalize_workflow_input(data)

    assert detect_workflow_input_format(data) == "ui_list"
    assert len(workflow.nodes) == 1
    assert workflow.nodes["1"].type == "CheckpointLoaderSimple"


def test_normalize_ui_dict_format() -> None:
    data = {
        "nodes": {
            "1": {
                "id": "1",
                "type": "CLIPLoader",
                "widgets_values": ["clip.safetensors"],
            }
        },
        "links": [],
    }

    workflow = normalize_workflow_input(data)

    assert detect_workflow_input_format(data) == "ui_dict"
    assert len(workflow.nodes) == 1
    assert workflow.nodes["1"].type == "CLIPLoader"


def test_normalize_naked_api_format() -> None:
    data = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
        "2": {"class_type": "VAELoader", "inputs": {}},
    }

    workflow = normalize_workflow_input(data)

    assert detect_workflow_input_format(data) == "api"
    assert len(workflow.nodes) == 2
    assert workflow.nodes["1"].type == "CheckpointLoaderSimple"
    assert workflow.nodes["2"].type == "VAELoader"


def test_normalize_wrapped_api_format() -> None:
    data = {
        "prompt": {
            "1": {"class_type": "CLIPLoader", "inputs": {}},
            "2": {"class_type": "KSampler", "inputs": {}},
        }
    }

    workflow = normalize_workflow_input(data)

    assert detect_workflow_input_format(data) == "api_wrapped"
    assert len(workflow.nodes) == 2
    assert workflow.nodes["1"].type == "CLIPLoader"
    assert workflow.nodes["2"].type == "KSampler"


def test_normalize_subgraph_workflow_passthrough() -> None:
    data = {
        "nodes": [
            {
                "id": 1,
                "type": "SaveImage",
                "widgets_values": [],
            },
            {
                "id": 2,
                "type": "0a58ac1f-cb15-4e01-aab3-26292addb965",
                "widgets_values": [],
            },
        ],
        "definitions": {
            "subgraphs": [
                {
                    "id": "0a58ac1f-cb15-4e01-aab3-26292addb965",
                    "name": "Text2Img",
                    "nodes": [
                        {
                            "id": 3,
                            "type": "CheckpointLoaderSimple",
                            "widgets_values": ["model.safetensors"],
                        }
                    ],
                    "links": [],
                }
            ]
        },
    }

    workflow = normalize_workflow_input(data)

    assert detect_workflow_input_format(data) == "ui_list"
    assert len(workflow.nodes) == 2
    assert "1" in workflow.nodes
    assert "0a58ac1f-cb15-4e01-aab3-26292addb965:3" in workflow.nodes


def test_malformed_input_raises_helpful_error() -> None:
    with pytest.raises(ValueError, match="Unsupported workflow format"):
        normalize_workflow_input({"hello": "world"})
