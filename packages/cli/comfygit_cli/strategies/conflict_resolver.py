"""Conflict resolution strategies for pull/merge operations.

Based on the Atomic Semantic Merge architecture:
- Only WORKFLOW conflicts are shown to users (nodes/deps are derived)
- NO skip option - every conflict must be resolved
- pyproject.toml conflicts are not shown (it's derived state)
"""

from typing import Literal

from comfygit_core.models import (
    RefDiff,
    WorkflowConflict,
)

# Only two valid resolutions - no "skip"
Resolution = Literal["take_base", "take_target"]


class InteractiveConflictResolver:
    """CLI interactive conflict resolver - NO skip option.

    Prompts user for each WORKFLOW conflict detected before a merge/pull.
    Node and dependency conflicts are not shown as they are derived from
    workflow resolutions.
    """

    def resolve_workflow(self, conflict: WorkflowConflict) -> Resolution:
        """Prompt user to resolve a workflow conflict."""
        print(f"\n  Workflow: {conflict.identifier}.json")
        print(f"    Your version:   {(conflict.base_hash or 'unknown')[:8]}...")
        print(f"    Their version:  {(conflict.target_hash or 'unknown')[:8]}...")
        print()

        while True:
            choice = input("    [m] Keep mine  [t] Keep theirs: ").lower().strip()
            if choice == "m":
                return "take_base"
            elif choice == "t":
                return "take_target"
            print("    Please enter 'm' or 't'")

    def resolve_all(self, diff: RefDiff) -> dict[str, Resolution]:
        """Resolve all workflow conflicts interactively.

        Only shows WORKFLOW conflicts. Nodes/deps are derived from workflows.

        Args:
            diff: RefDiff with conflicts

        Returns:
            Dict mapping workflow names to resolutions
        """
        resolutions: dict[str, Resolution] = {}

        if not diff.has_conflicts:
            return resolutions

        # Only handle WORKFLOW conflicts
        workflow_conflicts = [
            wf.conflict
            for wf in diff.workflow_changes
            if wf.conflict and wf.conflict.resolution == "unresolved"
        ]

        if not workflow_conflicts:
            return resolutions

        print(f"\n{len(workflow_conflicts)} workflow conflict(s) to resolve:\n")

        for conflict in workflow_conflicts:
            resolution = self.resolve_workflow(conflict)
            resolutions[conflict.identifier] = resolution
            conflict.resolution = resolution
            print()

        return resolutions


class AutoConflictResolver:
    """Auto-resolve conflicts using a fixed strategy.

    Used with --auto-resolve or --strategy flag for non-interactive resolution.
    """

    def __init__(self, strategy: Literal["mine", "theirs"]):
        """Initialize with resolution strategy.

        Args:
            strategy: "mine" to keep local (take_base), "theirs" to take incoming (take_target)
        """
        self._resolution: Resolution = (
            "take_base" if strategy == "mine" else "take_target"
        )

    def resolve_all(self, diff: RefDiff) -> dict[str, Resolution]:
        """Auto-resolve all workflow conflicts.

        Args:
            diff: RefDiff with conflicts

        Returns:
            Dict mapping workflow names to resolutions
        """
        resolutions: dict[str, Resolution] = {}

        # Only handle WORKFLOW conflicts
        for wf in diff.workflow_changes:
            if wf.conflict and wf.conflict.resolution == "unresolved":
                resolutions[wf.conflict.identifier] = self._resolution
                wf.conflict.resolution = self._resolution

        return resolutions
