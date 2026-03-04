"""Workflow input normalization utilities."""

from __future__ import annotations

from typing import Any, Literal

from ..models.workflow import Workflow

WorkflowInputFormat = Literal["ui_list", "ui_dict", "api", "api_wrapped"]


def _is_api_node_dict(data: Any) -> bool:
    """Return True when data looks like ComfyUI API prompt node mapping."""
    if not isinstance(data, dict) or not data:
        return False

    for node_id, node_data in data.items():
        if not isinstance(node_id, str) or not node_id.isdigit():
            return False
        if not isinstance(node_data, dict):
            return False
        if "class_type" not in node_data:
            return False

    return True


def detect_workflow_input_format(data: dict) -> WorkflowInputFormat:
    """Detect supported workflow input format."""
    nodes = data.get("nodes")
    if isinstance(nodes, list):
        return "ui_list"
    if isinstance(nodes, dict):
        return "ui_dict"

    prompt = data.get("prompt")
    if _is_api_node_dict(prompt):
        return "api_wrapped"

    if _is_api_node_dict(data):
        return "api"

    raise ValueError(
        "Unsupported workflow format. Expected ComfyUI UI format "
        "with 'nodes', API prompt wrapper {'prompt': {...}}, "
        "or naked API format {\"1\": {\"class_type\": ...}}."
    )


def _normalize_api_prompt_nodes(nodes: dict[str, dict[str, Any]]) -> dict:
    """Convert API prompt nodes into a Workflow.from_json-compatible structure."""
    normalized_nodes: dict[str, dict[str, Any]] = {}

    for node_id, node_data in nodes.items():
        normalized_node = dict(node_data)
        normalized_node["id"] = node_id
        normalized_node["type"] = node_data.get("class_type", "")
        normalized_nodes[node_id] = normalized_node

    return {
        "nodes": normalized_nodes,
        "links": [],
    }


def normalize_workflow_input(data: dict) -> Workflow:
    """Detect workflow format and normalize to internal Workflow model."""
    input_format = detect_workflow_input_format(data)

    if input_format in ("ui_list", "ui_dict"):
        return Workflow.from_json(data)

    if input_format == "api_wrapped":
        prompt = data.get("prompt", {})
        assert isinstance(prompt, dict)
        return Workflow.from_json(_normalize_api_prompt_nodes(prompt))

    # input_format == "api"
    return Workflow.from_json(_normalize_api_prompt_nodes(data))
