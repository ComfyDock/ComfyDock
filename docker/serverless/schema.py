"""
Workflow schema parsing utilities for the Async API worker system.

This module handles:
- Parsing workflow JSON to extract API schema
- Finding API-enabled inputs/outputs
- Injecting dynamic values into workflows

This module intentionally has no ComfyUI dependencies so it can be
tested standalone and used in both worker and orchestrator contexts.
"""

from __future__ import annotations

import copy
from typing import Any


class ContainsAnyDict(dict):
    """
    A dict that returns True for any __contains__ check.

    Used to allow arbitrary dynamic inputs in ComfyUI schemas.
    When used as optional_inputs, this allows the node to accept
    any input name without pre-registration.
    """

    def __contains__(self, key: object) -> bool:
        return True


# Node class types for API inputs
API_INPUT_TYPES = {
    "APIStringInput": "STRING",
    "APIIntInput": "INT",
    "APIFloatInput": "FLOAT",
    "APISeedInput": "INT",
    "APIComboInput": "STRING",
    "APIImageInput": "IMAGE",
    "APIVideoInput": "VIDEO",
}


def _is_ui_format(workflow: dict) -> bool:
    """Check if workflow is in UI format (has 'nodes' array) vs API format."""
    return "nodes" in workflow and isinstance(workflow["nodes"], list)


def _normalize_to_api_format(workflow: dict) -> dict:
    """
    Convert UI format workflow to API-like format for parsing.

    UI format has:
    - nodes: [{id, type, widgets_values, ...}, ...]
    - links: [[link_id, from_node, from_slot, to_node, to_slot, type], ...]

    API format has:
    - {node_id: {class_type, inputs: {...}}, ...}
    """
    if not _is_ui_format(workflow):
        return workflow

    # Build link lookup: link_id -> (from_node_id, from_slot)
    link_lookup = {}
    for link in workflow.get("links", []):
        if len(link) >= 3:
            link_id, from_node, from_slot = link[0], link[1], link[2]
            link_lookup[link_id] = (from_node, from_slot)

    result = {}
    for node in workflow.get("nodes", []):
        node_id = str(node.get("id"))
        node_type = node.get("type", "")
        widgets = node.get("widgets_values", [])

        # Build inputs dict from widgets_values based on node type
        inputs = {}

        if node_type == "WorkflowAPIConfig":
            # widgets_values: [workflow_name, description, version]
            if len(widgets) >= 1:
                inputs["workflow_name"] = widgets[0]
            if len(widgets) >= 2:
                inputs["description"] = widgets[1]
            if len(widgets) >= 3:
                inputs["version"] = widgets[2]

        elif node_type == "APIImageInput":
            # widgets_values: [image_filename, name, description]
            # Must be before general API_INPUT_TYPES check
            if len(widgets) >= 1:
                inputs["image"] = widgets[0]
            if len(widgets) >= 2:
                inputs["name"] = widgets[1]
            if len(widgets) >= 3:
                inputs["description"] = widgets[2]

        elif node_type == "APIVideoInput":
            # widgets_values: [video_filename, name, description]
            # Must be before general API_INPUT_TYPES check
            if len(widgets) >= 1:
                inputs["video"] = widgets[0]
            if len(widgets) >= 2:
                inputs["name"] = widgets[1]
            if len(widgets) >= 3:
                inputs["description"] = widgets[2]

        elif node_type in API_INPUT_TYPES:
            # widgets_values: [value, name, input_key, description]
            # Handles APIStringInput, APIIntInput, APIFloatInput, etc.
            if len(widgets) >= 1:
                inputs["value"] = widgets[0]
            if len(widgets) >= 2:
                inputs["name"] = widgets[1]
            if len(widgets) >= 3:
                inputs["input_key"] = widgets[2]
            if len(widgets) >= 4:
                inputs["description"] = widgets[3]

        elif node_type == "WorkerImageOutput":
            # widgets_values: [output_name, description]
            if len(widgets) >= 1:
                inputs["output_name"] = widgets[0]
            if len(widgets) >= 2:
                inputs["description"] = widgets[1]

        elif node_type == "WorkerVideoOutput":
            # widgets_values: [output_name, description]
            if len(widgets) >= 1:
                inputs["output_name"] = widgets[0]
            if len(widgets) >= 2:
                inputs["description"] = widgets[1]

        elif node_type == "SaveImage":
            # Check inputs for image connection
            for inp in node.get("inputs", []):
                if inp.get("name") == "images" and inp.get("link") is not None:
                    link_id = inp["link"]
                    if link_id in link_lookup:
                        from_node, from_slot = link_lookup[link_id]
                        inputs["images"] = [from_node, from_slot]

        elif node_type == "SaveVideo":
            # Check inputs for video connection
            for inp in node.get("inputs", []):
                if inp.get("name") == "video" and inp.get("link") is not None:
                    link_id = inp["link"]
                    if link_id in link_lookup:
                        from_node, from_slot = link_lookup[link_id]
                        inputs["video"] = [from_node, from_slot]

        elif node_type == "VHS_VideoCombine":
            # Check inputs for images (video frames) connection
            for inp in node.get("inputs", []):
                if inp.get("name") == "images" and inp.get("link") is not None:
                    link_id = inp["link"]
                    if link_id in link_lookup:
                        from_node, from_slot = link_lookup[link_id]
                        inputs["images"] = [from_node, from_slot]

        result[node_id] = {
            "class_type": node_type,
            "inputs": inputs,
        }

    return result


def find_downstream_save_node(workflow: dict, start_node_id: str) -> str | None:
    """
    Find SaveImage node connected downstream from given node.

    Args:
        workflow: The workflow JSON dict (API format)
        start_node_id: Node ID to search from

    Returns:
        Node ID of connected SaveImage, or None if not found
    """
    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue
        if node_data.get("class_type") == "SaveImage":
            inputs = node_data.get("inputs", {})
            images_input = inputs.get("images")
            # ComfyUI encodes connections as [node_id, output_slot]
            if isinstance(images_input, list) and len(images_input) >= 1:
                if str(images_input[0]) == str(start_node_id):
                    return node_id
    return None


def find_downstream_video_save_node(workflow: dict, start_node_id: str) -> str | None:
    """
    Find SaveVideo or VHS_VideoCombine node connected downstream from given node.

    Args:
        workflow: The workflow JSON dict (API format)
        start_node_id: Node ID to search from

    Returns:
        Node ID of connected video save node, or None if not found
    """
    video_save_types = {"SaveVideo", "VHS_VideoCombine"}

    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue
        if node_data.get("class_type") in video_save_types:
            inputs = node_data.get("inputs", {})
            # SaveVideo uses 'video' input, VHS uses 'images'
            video_input = inputs.get("video") or inputs.get("images")
            if isinstance(video_input, list) and len(video_input) >= 1:
                if str(video_input[0]) == str(start_node_id):
                    return node_id
    return None


def parse_workflow_schema(workflow: dict) -> dict | None:
    """
    Parse a workflow JSON and extract API schema if it contains WorkflowAPIConfig.

    Supports both UI format (from ComfyUI Save) and API format (from Export API).

    Returns None if workflow is not API-enabled (no WorkflowAPIConfig node).

    Args:
        workflow: The workflow JSON dict (UI or API format)

    Returns:
        Schema dict with name, description, version, inputs, outputs
        or None if not API-enabled
    """
    if not workflow:
        return None

    # Normalize to API format for consistent parsing
    normalized = _normalize_to_api_format(workflow)

    # Find WorkflowAPIConfig node
    config_node = None
    for node_id, node_data in normalized.items():
        if not isinstance(node_data, dict):
            continue
        if node_data.get("class_type") == "WorkflowAPIConfig":
            config_node = node_data
            break

    if not config_node:
        return None

    inputs_data = config_node.get("inputs", {})
    schema: dict[str, Any] = {
        "name": inputs_data.get("workflow_name", "unnamed"),
        "description": inputs_data.get("description", ""),
        "version": inputs_data.get("version", "1.0.0"),
        "inputs": [],
        "outputs": [],
    }

    # Find all API input nodes
    for node_id, node_data in normalized.items():
        if not isinstance(node_data, dict):
            continue

        class_type = node_data.get("class_type", "")
        if class_type in API_INPUT_TYPES:
            node_inputs = node_data.get("inputs", {})

            schema["inputs"].append({
                "node_id": node_id,
                "name": node_inputs.get("name", f"input_{node_id}"),
                "description": node_inputs.get("description", ""),
                "type": API_INPUT_TYPES[class_type],
                "default": node_inputs.get("value"),
                "input_key": node_inputs.get("input_key", "value"),
            })

    # Find all API output nodes
    for node_id, node_data in normalized.items():
        if not isinstance(node_data, dict):
            continue

        if node_data.get("class_type") == "WorkerImageOutput":
            node_inputs = node_data.get("inputs", {})

            # Find connected SaveImage node
            save_node_id = find_downstream_save_node(normalized, node_id)

            schema["outputs"].append({
                "node_id": node_id,
                "save_node_id": save_node_id,
                "name": node_inputs.get("output_name", f"output_{node_id}"),
                "description": node_inputs.get("description", ""),
                "type": "IMAGE",
            })

        elif node_data.get("class_type") == "WorkerVideoOutput":
            node_inputs = node_data.get("inputs", {})

            # Find connected SaveVideo or VHS_VideoCombine node
            save_node_id = find_downstream_video_save_node(normalized, node_id)

            schema["outputs"].append({
                "node_id": node_id,
                "save_node_id": save_node_id,
                "name": node_inputs.get("output_name", f"output_{node_id}"),
                "description": node_inputs.get("description", ""),
                "type": "VIDEO",
            })

    return schema


def convert_ui_to_api_format(workflow: dict, object_info: dict) -> dict:
    """
    Convert a UI format workflow to API format for execution.

    UI format (from ComfyUI Save) has nodes array and links array.
    API format (for /prompt) has node_id keys with class_type and inputs.

    This implementation mirrors ComfyUI's graphToPrompt logic but works with
    static JSON instead of live graph objects.

    Args:
        workflow: UI format workflow dict
        object_info: Node definitions from /object_info endpoint

    Returns:
        API format workflow ready for /prompt submission
    """
    if not _is_ui_format(workflow):
        return workflow  # Already API format

    ui_node_ids = [str(n.get("id")) for n in workflow.get("nodes", [])]
    print(f"[UI→API] Converting {len(ui_node_ids)} UI nodes: {sorted(ui_node_ids, key=lambda x: int(x) if x.isdigit() else 0)}")

    # Build link lookup: link_id -> (from_node_id, from_slot)
    link_lookup = {}
    for link in workflow.get("links", []):
        if link and len(link) >= 3:
            link_id, from_node, from_slot = link[0], link[1], link[2]
            link_lookup[link_id] = (from_node, from_slot)

    # Separate muted (mode=2) and bypassed (mode=4) nodes
    # - Muted: fully disabled, connections are broken
    # - Bypassed: pass-through, connections should be rewired
    muted_node_ids = set()  # mode=2 (NEVER)
    bypassed_node_ids = set()  # mode=4 (BYPASS)
    node_lookup = {}  # id -> node dict

    for node in workflow.get("nodes", []):
        node_id = str(node.get("id"))
        node_lookup[node_id] = node
        node_mode = node.get("mode", 0)
        if node_mode == 2:
            muted_node_ids.add(node_id)
        elif node_mode == 4:
            bypassed_node_ids.add(node_id)

    # Combined set for skipping nodes
    skip_node_ids = muted_node_ids | bypassed_node_ids

    if muted_node_ids:
        print(f"[UI→API] Found {len(muted_node_ids)} muted nodes to skip: {sorted(muted_node_ids)}")
    if bypassed_node_ids:
        print(f"[UI→API] Found {len(bypassed_node_ids)} bypassed nodes (will rewire): {sorted(bypassed_node_ids)}")

    # Build bypass pass-through mapping for bypassed nodes
    # Maps (node_id, output_slot) -> (upstream_node_id, upstream_slot) or None
    # This traces through bypassed nodes to find the actual source
    def resolve_bypass_chain(node_id: str, output_slot: int) -> tuple[str, int] | None:
        """Follow bypass chain to find the actual source node/slot."""
        visited = set()
        current_id = node_id
        current_slot = output_slot

        while current_id in bypassed_node_ids:
            if current_id in visited:
                return None  # Cycle detected
            visited.add(current_id)

            node = node_lookup.get(current_id)
            if not node:
                return None

            # Find the input that corresponds to this output slot
            # For bypass, we assume first matching-type input passes to output
            # ComfyUI's actual logic is more complex, but this covers common cases
            node_inputs = node.get("inputs", [])
            node_outputs = node.get("outputs", [])

            if current_slot >= len(node_outputs):
                return None

            output_type = node_outputs[current_slot].get("type")

            # Find first input with matching type
            upstream_found = False
            for inp in node_inputs:
                if inp.get("type") == output_type:
                    link_id = inp.get("link")
                    if link_id is not None and link_id in link_lookup:
                        upstream_node, upstream_slot = link_lookup[link_id]
                        current_id = str(upstream_node)
                        current_slot = upstream_slot
                        upstream_found = True
                        break

            if not upstream_found:
                # No matching input - this bypass has nothing to pass through
                return None

        # current_id is now a non-bypassed node
        if current_id in muted_node_ids:
            return None  # Muted nodes don't pass through
        return (current_id, current_slot)

    # Primitive types that have widgets (not socket-only)
    # Everything else is a custom type and is socket-only
    # COMBO can appear as a string type name or as an inline list of options
    WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}

    result = {}

    for node in workflow.get("nodes", []):
        node_id = str(node.get("id"))
        node_type = node.get("type", "")
        widgets_values = node.get("widgets_values") or []

        # Skip muted/bypassed nodes - they won't be in the result
        if node_id in skip_node_ids:
            print(f"[UI→API] Skipping {'muted' if node_id in muted_node_ids else 'bypassed'} node {node_id} ({node_type})")
            continue

        # Get node definition from object_info
        node_def = object_info.get(node_type, {})
        input_defs = node_def.get("input", {})
        required = input_defs.get("required", {})
        optional = input_defs.get("optional", {})

        # Build inputs dict
        inputs = {}

        # Build set of connected input names from node's inputs array
        # Handle muted/bypassed nodes appropriately
        connected_inputs = set()
        for inp in node.get("inputs", []):
            inp_name = inp.get("name")
            link_id = inp.get("link")
            if inp_name and link_id is not None and link_id in link_lookup:
                from_node, from_slot = link_lookup[link_id]
                from_node_str = str(from_node)

                # Handle connections from muted nodes (broken - skip)
                if from_node_str in muted_node_ids:
                    print(f"[UI→API] Ignoring link from muted node {from_node_str} to {node_id}.{inp_name}")
                    continue

                # Handle connections from bypassed nodes (rewire through)
                if from_node_str in bypassed_node_ids:
                    resolved = resolve_bypass_chain(from_node_str, from_slot)
                    if resolved is None:
                        print(f"[UI→API] Bypass chain from {from_node_str} has no pass-through for {node_id}.{inp_name}")
                        continue
                    from_node_str, from_slot = resolved
                    print(f"[UI→API] Rewired bypass: {node_id}.{inp_name} now from [{from_node_str}, {from_slot}]")

                # API format uses string node IDs
                inputs[inp_name] = [from_node_str, from_slot]
                connected_inputs.add(inp_name)

        # Determine input ordering
        # Use input_order if available (from newer node definitions)
        input_order = node_def.get("input_order", {})
        ordered_required = input_order.get("required", list(required.keys()))
        ordered_optional = input_order.get("optional", list(optional.keys()))

        # Build ordered list of (name, spec) tuples
        all_inputs = []
        for name in ordered_required:
            if name in required:
                all_inputs.append((name, required[name]))
        for name in ordered_optional:
            if name in optional:
                all_inputs.append((name, optional[name]))
        # Add any remaining inputs not in input_order
        for name, spec in required.items():
            if name not in ordered_required:
                all_inputs.append((name, spec))
        for name, spec in optional.items():
            if name not in ordered_optional:
                all_inputs.append((name, spec))

        # Map widgets_values to input names
        # widgets_values array is ordered by widget creation order, which
        # should match the input definition order.
        widget_idx = 0

        # Debug: show conversion details for nodes with multiple widgets or API nodes
        is_api_node = node_type in API_INPUT_TYPES or node_type in ("WorkerImageOutput", "WorkerVideoOutput", "SaveVideo")
        debug_node = len(widgets_values) > 5 or is_api_node

        if debug_node:
            print(f"[UI→API] Node {node_id} ({node_type}): {len(widgets_values)} widget values, {len(all_inputs)} inputs")
            print(f"[UI→API]   widgets_values: {widgets_values}")
            print(f"[UI→API]   input_order provided: {bool(input_order)}")

        for name, spec in all_inputs:
            # Determine the type of this input
            type_name = None
            spec_opts = {}
            if isinstance(spec, (list, tuple)) and len(spec) > 0:
                type_name = spec[0]
                if len(spec) > 1 and isinstance(spec[1], dict):
                    spec_opts = spec[1]

            # Determine if this input has a widget or is socket-only
            # Widget types: primitives (INT, FLOAT, STRING, BOOLEAN) or combos (list of options)
            # Socket-only: custom types (anything else) or forceInput=true
            is_socket_type = True  # Default to socket
            if isinstance(type_name, list):
                # Combo (list of options) - has widget
                is_socket_type = False
            elif isinstance(type_name, str) and type_name.upper() in WIDGET_TYPES:
                # Primitive type - has widget
                is_socket_type = False

            # forceInput overrides to make it socket-only
            if spec_opts.get("forceInput"):
                is_socket_type = True

            if is_socket_type:
                # Socket types don't consume widget values
                if debug_node:
                    print(f"[UI→API]   {name}: socket type ({type_name}), skipped")
                continue

            # This input has a widget - consume from widgets_values
            if widget_idx < len(widgets_values):
                value = widgets_values[widget_idx]
                if debug_node:
                    print(f"[UI→API]   {name}: widget[{widget_idx}] = {repr(value)} (type: {type_name})")
                widget_idx += 1

                # Only set if not connected (connections override widget values)
                if name not in connected_inputs:
                    inputs[name] = value
                elif debug_node:
                    print(f"[UI→API]     ^ SKIPPED (connected)")
            else:
                if debug_node:
                    print(f"[UI→API]   {name}: NO WIDGET VALUE (idx {widget_idx} >= {len(widgets_values)})")

            # Check if this input has control_after_generate (adds extra widget)
            # ComfyUI also auto-adds this for inputs named 'seed' or 'noise_seed'
            has_control_widget = (
                spec_opts.get("control_after_generate") or
                name in ("seed", "noise_seed")
            )
            if has_control_widget and widget_idx < len(widgets_values):
                if debug_node:
                    print(f"[UI→API]   {name}: +control widget[{widget_idx}] = {repr(widgets_values[widget_idx])}")
                # Skip the control_after_generate widget value
                widget_idx += 1

        # Debug: show final mapping for complex nodes
        if len(widgets_values) > 5:
            print(f"[UI→API]   Final inputs: {inputs}")
            if widget_idx != len(widgets_values):
                print(f"[UI→API]   WARNING: Used {widget_idx} of {len(widgets_values)} widget values!")

        result[node_id] = {
            "class_type": node_type,
            "inputs": inputs,
        }

    return result


def inject_inputs_with_schema(
    workflow: dict,
    schema: dict,
    dynamic_inputs: dict[str, Any]
) -> dict:
    """
    Inject input values into workflow using schema mappings.

    Uses the schema's input definitions to find the correct node_id
    and input_key for each named dynamic input. Also converts values
    to the correct type based on the schema (INT, FLOAT, STRING).

    Supports both UI format and API format workflows:
    - UI format: Updates widgets_values array in the nodes array
    - API format: Updates inputs dict at node_id key

    For API input nodes (APIStringInput, APISeedInput, etc.), the value
    is always injected into the 'value' field (or widgets_values[0] for UI).

    Args:
        workflow: The workflow JSON dict (UI or API format)
        schema: Schema dict from parse_workflow_schema
        dynamic_inputs: Dict of {input_name: value}

    Returns:
        Modified copy of workflow with injected values
    """
    result = copy.deepcopy(workflow)
    is_ui = _is_ui_format(result)

    # Build lookup from input name to (node_id, input_key, type)
    input_lookup = {}
    for input_def in schema.get("inputs", []):
        input_lookup[input_def["name"]] = (
            input_def["node_id"],
            input_def.get("input_key", "value"),
            input_def.get("type", "STRING")
        )

    # For UI format, build a lookup from node ID to index in nodes array
    ui_node_lookup = {}
    if is_ui:
        for idx, node in enumerate(result.get("nodes", [])):
            ui_node_lookup[str(node.get("id"))] = idx

    # Inject each dynamic input
    for input_name, value in dynamic_inputs.items():
        if input_name not in input_lookup:
            # Skip inputs not in schema
            continue

        node_id, input_key, input_type = input_lookup[input_name]

        # Convert value to the correct type based on schema
        if input_type == "INT":
            # Convert to integer (handles float values from JS)
            try:
                value = int(round(value)) if isinstance(value, (int, float)) else int(value)
            except (ValueError, TypeError):
                pass  # Keep original value if conversion fails
        elif input_type == "FLOAT":
            try:
                value = float(value)
            except (ValueError, TypeError):
                pass
        elif input_type == "STRING":
            value = str(value) if value is not None else ""

        if is_ui:
            # UI format: find node in nodes array and update widgets_values
            if node_id in ui_node_lookup:
                node_idx = ui_node_lookup[node_id]
                node = result["nodes"][node_idx]
                node_type = node.get("type", "")

                # For API input nodes, value is at widgets_values[0]
                if node_type in API_INPUT_TYPES:
                    if "widgets_values" not in node:
                        node["widgets_values"] = [value]
                    elif len(node["widgets_values"]) > 0:
                        node["widgets_values"][0] = value
                    else:
                        node["widgets_values"].append(value)
                else:
                    # For other nodes, we'd need widget ordering info
                    # which isn't available without object_info
                    pass
        else:
            # API format: update inputs dict at node_id key
            if node_id in result and isinstance(result[node_id], dict):
                if "inputs" not in result[node_id]:
                    result[node_id]["inputs"] = {}

                # For API input nodes, inject into the correct field
                node_class = result[node_id].get("class_type", "")
                if node_class == "APIImageInput":
                    # APIImageInput uses "image" field
                    result[node_id]["inputs"]["image"] = value
                elif node_class == "APIVideoInput":
                    # APIVideoInput uses "video" field
                    result[node_id]["inputs"]["video"] = value
                elif node_class in API_INPUT_TYPES:
                    # Other API input nodes use "value" field
                    result[node_id]["inputs"]["value"] = value
                else:
                    # For regular nodes, use the input_key
                    result[node_id]["inputs"][input_key] = value

    return result


# Node types that are UI-only and should be stripped
# Note: Reroute and PrimitiveNode are NOT stripped because they carry
# connection/value data that the worker needs. Proper inlining would
# require complex graph traversal.
UI_ONLY_NODES = {
    "Note",
    "MarkdownNote",
}

# Output node types that should be kept even without downstream connections
OUTPUT_NODES = {
    "SaveImage",
    "PreviewImage",
    "SaveAnimatedWEBP",
    "SaveAnimatedPNG",
    "VHS_VideoCombine",
    "SaveVideo",
}


def strip_orphan_nodes(workflow: dict) -> dict:
    """
    Remove nodes that aren't part of the execution graph.

    Filters out:
    - UI-only nodes (Note, MarkdownNote, etc.)
    - Orphan nodes with no downstream connections

    Keeps:
    - Output nodes (SaveImage, PreviewImage, etc.)
    - Nodes that feed into other nodes
    - API config nodes (WorkflowAPIConfig)
    """
    print(f"[StripOrphans] Input workflow has {len([k for k in workflow.keys() if isinstance(workflow.get(k), dict)])} nodes")

    # Find all node IDs that are referenced as inputs by other nodes
    referenced_nodes = set()
    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue
        inputs = node_data.get("inputs", {})
        for input_value in inputs.values():
            # Links are [node_id, output_index] arrays
            if isinstance(input_value, list) and len(input_value) == 2:
                ref_node_id = str(input_value[0])
                referenced_nodes.add(ref_node_id)

    print(f"[StripOrphans] Found {len(referenced_nodes)} referenced nodes")

    result = {}
    stripped = []
    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue

        class_type = node_data.get("class_type", "")

        # Skip UI-only nodes
        if class_type in UI_ONLY_NODES:
            stripped.append(f"{node_id}({class_type}:ui-only)")
            continue

        # Keep output nodes
        if class_type in OUTPUT_NODES:
            result[node_id] = node_data
            continue

        # Keep API config node
        if class_type == "WorkflowAPIConfig":
            result[node_id] = node_data
            continue

        # Keep nodes that are referenced by other nodes
        if node_id in referenced_nodes:
            result[node_id] = node_data
        else:
            stripped.append(f"{node_id}({class_type}:orphan)")

    if stripped:
        print(f"[StripOrphans] Stripped {len(stripped)} nodes: {stripped[:10]}{'...' if len(stripped) > 10 else ''}")
    print(f"[StripOrphans] Output workflow has {len(result)} nodes")

    return result
