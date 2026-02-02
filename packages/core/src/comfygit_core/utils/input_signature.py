"""Input signature utilities for node version resolution."""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from comfygit_core.models.workflow import NodeInput

from ..logging.logging_config import get_logger

logger = get_logger(__name__)


def normalize_registry_inputs(input_types_json: str) -> str:
    """Normalize input types from registry metadata.

    Args:
        input_types_json: JSON string like '{"required":{"mask":["MASK"],"scale":["FLOAT",{"default":1}]}}'

    Returns:
        Canonical input signature string
    """
    try:
        parsed = json.loads(input_types_json)
        normalized = {}

        # Process required and optional inputs
        for category in ["required", "optional"]:
            if category in parsed:
                for name, type_info in parsed[category].items():
                    # type_info patterns:
                    # - ["TYPE"] or ["TYPE", {...constraints}] for simple types
                    # - [[...options]] or [[...options], {...}] for COMBO/choice fields
                    if isinstance(type_info, list) and len(type_info) > 0:
                        first_elem = type_info[0]
                        # Check if first element is a list (COMBO type)
                        if isinstance(first_elem, list):
                            normalized[name] = "COMBO"
                        elif isinstance(first_elem, str):
                            normalized[name] = first_elem
                        else:
                            logger.warning(f"Unexpected first element type for {name}: {type(first_elem)}")
                            continue
                    elif isinstance(type_info, str):
                        normalized[name] = type_info
                    else:
                        logger.warning(f"Unexpected type_info format for {name}: {type_info}")
                        continue

        return _create_canonical_signature(normalized)

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"Failed to parse registry input types: {e}")
        return ""


def normalize_workflow_inputs(inputs: list[NodeInput]) -> str:
    """Normalize input types from workflow node definition.

    Args:
        inputs: List of NodeInput dataclass instances with name and type attributes

    Returns:
        Canonical input signature string
    """
    normalized = {}

    for input_def in inputs:
        # Handle NodeInput dataclass (has attributes) or dict (has keys)
        if hasattr(input_def, 'name') and hasattr(input_def, 'type'):
            # NodeInput dataclass
            name = input_def.name
            input_type = input_def.type
        elif isinstance(input_def, dict):
            # Legacy dict format (for backwards compatibility)
            name = input_def.get('name')
            input_type = input_def.get('type')
        else:
            logger.warning(f"Unexpected input format: {type(input_def)}")
            continue

        if name and input_type:
            normalized[name] = input_type

    return _create_canonical_signature(normalized)


def _create_canonical_signature(inputs: dict[str, str]) -> str:
    """Create canonical signature from normalized inputs.

    Args:
        inputs: Dictionary of {input_name: input_type}

    Returns:
        Canonical signature string
    """
    if not inputs:
        return ""

    # Sort by name for deterministic ordering
    sorted_inputs = sorted(inputs.items())

    # Create canonical string: "name1:TYPE1|name2:TYPE2"
    canonical = "|".join([f"{name}:{type_}" for name, type_ in sorted_inputs])

    return canonical


def hash_signature(signature: str) -> str:
    """Create short hash of input signature.

    Args:
        signature: Canonical signature string

    Returns:
        8-character hash
    """
    if not signature:
        return "_"  # Special marker for empty/unknown signatures

    return hashlib.sha1(signature.encode()).hexdigest()[:8]


def create_node_key(node_type: str, inputs_signature: str) -> str:
    """Create compound key for node lookup.

    Args:
        node_type: Node class type name
        inputs_signature: Canonical input signature or hash

    Returns:
        Compound key like "NodeType::hash1234"
    """
    if not inputs_signature or inputs_signature == "_":
        return f"{node_type}::_"

    # If signature is already a hash (8 chars), use it. Otherwise hash it.
    if len(inputs_signature) == 8 and all(c in '0123456789abcdef' for c in inputs_signature):
        hash_part = inputs_signature
    else:
        hash_part = hash_signature(inputs_signature)

    return f"{node_type}::{hash_part}"
