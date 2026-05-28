"""Tests for conflict resolution strategies.

The conflict resolver now only handles WORKFLOW conflicts.
Nodes and dependencies are derived from workflow resolutions.
There is NO skip option - all conflicts must be resolved.
"""

from unittest.mock import patch

from comfygit_cli.strategies.conflict_resolver import (
    AutoConflictResolver,
    InteractiveConflictResolver,
)
from comfygit_core.models import (
    DependencyChanges,
    RefDiff,
    WorkflowChange,
    WorkflowConflict,
)


class TestAutoConflictResolver:
    """Tests for AutoConflictResolver."""

    def test_mine_strategy_resolves_to_take_base(self):
        """Auto-resolve with 'mine' should resolve workflows to take_base."""
        resolver = AutoConflictResolver("mine")

        wf_conflict = WorkflowConflict(
            identifier="test-workflow",
            conflict_type="both_modified",
            base_hash="abc123",
            target_hash="def456",
        )

        wf_change = WorkflowChange(
            name="test-workflow",
            change_type="modified",
            conflict=wf_conflict,
        )

        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            node_changes=[],
            model_changes=[],
            workflow_changes=[wf_change],
            dependency_changes=DependencyChanges(),
        )

        resolutions = resolver.resolve_all(diff)

        assert resolutions["test-workflow"] == "take_base"
        assert wf_conflict.resolution == "take_base"

    def test_theirs_strategy_resolves_to_take_target(self):
        """Auto-resolve with 'theirs' should resolve workflows to take_target."""
        resolver = AutoConflictResolver("theirs")

        wf_conflict = WorkflowConflict(
            identifier="test-workflow",
            conflict_type="both_modified",
        )

        wf_change = WorkflowChange(
            name="test-workflow",
            change_type="modified",
            conflict=wf_conflict,
        )

        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            node_changes=[],
            model_changes=[],
            workflow_changes=[wf_change],
            dependency_changes=DependencyChanges(),
        )

        resolutions = resolver.resolve_all(diff)

        assert resolutions["test-workflow"] == "take_target"

    def test_resolve_all_only_resolves_workflow_conflicts(self):
        """resolve_all should only update workflow conflicts (not nodes)."""
        resolver = AutoConflictResolver("theirs")

        wf_conflict = WorkflowConflict(
            identifier="wf1",
            conflict_type="both_modified",
        )

        wf_change = WorkflowChange(
            name="wf1",
            change_type="modified",
            conflict=wf_conflict,
        )

        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            node_changes=[],  # Node conflicts are no longer handled
            model_changes=[],
            workflow_changes=[wf_change],
            dependency_changes=DependencyChanges(),
        )

        resolutions = resolver.resolve_all(diff)

        # Only workflow conflicts are resolved
        assert len(resolutions) == 1
        assert resolutions["wf1"] == "take_target"
        assert wf_conflict.resolution == "take_target"


class TestInteractiveConflictResolver:
    """Tests for InteractiveConflictResolver."""

    def test_resolve_workflow_mine_choice(self):
        """User choosing 'm' should return take_base."""
        resolver = InteractiveConflictResolver()

        conflict = WorkflowConflict(
            identifier="test-workflow",
            conflict_type="both_modified",
            base_hash="abc123",
            target_hash="def456",
        )

        with patch("builtins.input", return_value="m"):
            with patch("builtins.print"):
                result = resolver.resolve_workflow(conflict)

        assert result == "take_base"

    def test_resolve_workflow_theirs_choice(self):
        """User choosing 't' should return take_target."""
        resolver = InteractiveConflictResolver()

        conflict = WorkflowConflict(
            identifier="test-workflow",
            conflict_type="both_modified",
        )

        with patch("builtins.input", return_value="t"):
            with patch("builtins.print"):
                result = resolver.resolve_workflow(conflict)

        assert result == "take_target"

    def test_resolve_workflow_invalid_then_valid_choice(self):
        """Invalid choices should prompt again until valid."""
        resolver = InteractiveConflictResolver()

        conflict = WorkflowConflict(
            identifier="test-workflow",
            conflict_type="both_modified",
        )

        # First 's' (invalid - no skip), then 'x' (invalid), then 'm' (valid)
        with patch("builtins.input", side_effect=["s", "x", "m"]):
            with patch("builtins.print"):
                result = resolver.resolve_workflow(conflict)

        assert result == "take_base"

    def test_resolve_all_only_handles_workflow_conflicts(self):
        """resolve_all should only resolve workflow conflicts."""
        resolver = InteractiveConflictResolver()

        wf_conflict = WorkflowConflict(
            identifier="test-wf",
            conflict_type="both_modified",
        )

        wf_change = WorkflowChange(
            name="test-wf",
            change_type="modified",
            conflict=wf_conflict,
        )

        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            node_changes=[],
            model_changes=[],
            workflow_changes=[wf_change],
            dependency_changes=DependencyChanges(),
        )

        with patch("builtins.input", return_value="t"):
            with patch("builtins.print"):
                resolutions = resolver.resolve_all(diff)

        assert resolutions["test-wf"] == "take_target"
        assert wf_conflict.resolution == "take_target"

    def test_resolve_all_returns_empty_when_no_conflicts(self):
        """resolve_all should return empty dict when no conflicts."""
        resolver = InteractiveConflictResolver()

        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            node_changes=[],
            model_changes=[],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )

        resolutions = resolver.resolve_all(diff)

        assert resolutions == {}
