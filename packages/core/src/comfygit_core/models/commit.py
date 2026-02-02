"""Commit operation result models."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models.shared import ModelWithLocation

@dataclass
class ModelResolutionRequest:
    """Request for resolving ambiguous model matches."""
    workflow_name: str
    node_id: str
    node_type: str
    widget_index: int
    original_value: str
    candidates: list[ModelWithLocation]
