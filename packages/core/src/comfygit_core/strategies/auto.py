"""Auto resolution strategies for workflow dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from comfygit_core.models.protocols import ModelResolutionStrategy, NodeResolutionStrategy

from ..models.workflow import (
    ModelResolutionContext,
    NodeResolutionContext,
    ResolvedModel,
    WorkflowNodeWidgetRef,
)

if TYPE_CHECKING:
    from ..models.workflow import ResolvedNodePackage


class AutoNodeStrategy(NodeResolutionStrategy):
    """Automatic node resolution - makes best effort choices without user input."""

    def resolve_unknown_node(
        self,
        node_type: str,
        possible: list[ResolvedNodePackage],
        context: NodeResolutionContext
    ) -> ResolvedNodePackage | None:
        """Pick the top suggestion by confidence, or first if tied.

        Args:
            node_type: The unknown node type
            possible: List of possible package matches
            context: Resolution context (unused in auto mode)

        Returns:
            ResolvedNodePackage or None if no candidates
        """
        if not possible:
            return None

        # Sort by confidence descending, then just pick first
        sorted_suggestions = sorted(
            possible, key=lambda s: s.match_confidence, reverse=True
        )

        return sorted_suggestions[0]

    def confirm_node_install(self, package: ResolvedNodePackage) -> bool:
        """Always confirm - we're making automated choices."""
        return True


class AutoModelStrategy(ModelResolutionStrategy):
    """Automatic model resolution - makes simple naive choices."""

    def resolve_model(
        self,
        reference: WorkflowNodeWidgetRef,
        candidates: list[ResolvedModel],
        context: ModelResolutionContext,
    ) -> ResolvedModel | None:
        """Pick the first candidate, or skip if none available.

        Args:
            reference: The model reference from workflow
            candidates: List of potential matches (may be empty for missing models)
            context: Resolution context with search function and workflow info

        Returns:
            First candidate as ResolvedModel, or None to skip
        """
        if not candidates:
            # No candidates - skip (don't mark as optional)
            return None

        # Return first candidate (already a ResolvedModel)
        return candidates[0]
