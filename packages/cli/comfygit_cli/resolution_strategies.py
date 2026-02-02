"""Model resolution strategies for CLI interaction."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from comfygit_core.models.commit import ModelResolutionRequest
    from comfygit_core.models.shared import ModelWithLocation


class InteractiveModelResolver:
    """Handles interactive model resolution for CLI."""

    def resolve_ambiguous_models(
        self,
        requests: list[ModelResolutionRequest]
    ) -> dict[str, ModelWithLocation]:
        """Interactively resolve ambiguous models.

        Args:
            requests: List of models needing resolution

        Returns:
            Dict mapping request key to selected model
        """
        resolutions = {}

        if not requests:
            return resolutions

        print(f"\n🤔 Found {len(requests)} models requiring confirmation:")

        for req in requests:
            print(f"\nWorkflow: {req.workflow_name}")
            print(f"Node: {req.node_type} (ID: {req.node_id})")
            print(f"Looking for: {req.original_value}")
            print(f"Found {len(req.candidates)} potential matches:")

            for i, model in enumerate(req.candidates, 1):
                size_gb = model.file_size / (1024**3)
                print(f"  {i}. {model.relative_path}")
                print(f"     Size: {size_gb:.1f} GB | Hash: {model.hash}")

            print("  0. Skip this model")

            while True:
                choice = input(f"Select [1-{len(req.candidates)}] or 0: ").strip()

                if choice == "0":
                    break  # Skip this model

                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(req.candidates):
                        # Create unique key for request
                        req_key = f"{req.workflow_name}:{req.node_id}:{req.widget_index}"
                        resolutions[req_key] = req.candidates[idx]
                        print(f"✓ Selected: {req.candidates[idx].filename}")
                        break

                print("Invalid choice, please try again.")

        return resolutions


class AutomaticModelResolver:
    """Automatically resolves models (for --no-interactive mode)."""

    def resolve_ambiguous_models(
        self,
        requests: list[ModelResolutionRequest]
    ) -> dict[str, ModelWithLocation]:
        """Auto-resolve by picking first match or skipping.

        Args:
            requests: List of models needing resolution

        Returns:
            Dict mapping request key to selected model
        """
        resolutions = {}

        for req in requests:
            if req.candidates:
                # Pick first candidate automatically
                req_key = f"{req.workflow_name}:{req.node_id}:{req.widget_index}"
                resolutions[req_key] = req.candidates[0]

        return resolutions
