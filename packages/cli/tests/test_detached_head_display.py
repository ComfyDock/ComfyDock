"""CLI test for detached HEAD state display in status command.

This tests the critical bug where detached HEAD state was hidden when the
environment was in a clean state (no workflows, no uncommitted changes).

Bug: Status command early return for clean state bypassed detached HEAD warning,
showing "Environment: test ✓" instead of "Environment: test (detached HEAD) ⚠️"

Fix: Always display git state and show detached HEAD warning even in clean state.
"""

import argparse
import sys
from pathlib import Path
from unittest.mock import Mock

# Import CLI command handler
sys.path.insert(0, str(Path(__file__).parent.parent))
from comfygit_cli.env_commands import EnvironmentCommands  # noqa: E402

# Import core models
core_src_path = Path(__file__).parent.parent.parent / "core" / "src"
sys.path.insert(0, str(core_src_path))
from comfygit_core.models import (  # noqa: E402
    DetailedWorkflowStatus,
    EnvironmentComparison,
    EnvironmentLifecycleStatus,
    EnvironmentStatus,
    GitStatus,
    WorkflowSyncStatus,
)


class TestDetachedHeadDisplay:
    """Test that CLI status command properly displays detached HEAD warnings."""

    def test_status_shows_detached_head_in_clean_state(self, capsys):
        """
        CRITICAL BUG TEST: Verify detached HEAD is shown even when environment is clean.

        This is the original bug - when the environment had no workflows and no changes,
        the early return path in status() would show "Environment: name ✓" without any
        indication of detached HEAD state.

        Expected behavior: Show "Environment: name (detached HEAD) ⚠️" with warning.
        """
        # ARRANGE: Create mock environment in detached HEAD with clean state
        mock_env = Mock()
        mock_env.name = "test-env"

        # Create clean status (no workflows, no changes, synced)
        clean_status = EnvironmentStatus(
            git=GitStatus(
                current_branch=None,  # ← Detached HEAD!
                has_changes=False,
                nodes_added=[],
                nodes_removed=[],
                workflow_changes=[]
            ),
            workflow=DetailedWorkflowStatus(
                sync_status=WorkflowSyncStatus(
                    synced=[],
                    new=[],
                    modified=[],
                    deleted=[]
                ),
                analyzed_workflows=[]
            ),
            comparison=EnvironmentComparison(
                missing_nodes=[],
                extra_nodes=[],
                version_mismatches=[],
                packages_in_sync=True
            ),
            missing_models=[]
        )

        mock_env.status.return_value = clean_status
        mock_env.get_lifecycle_status.return_value = EnvironmentLifecycleStatus()

        # Create command handler and mock its methods
        cmd = EnvironmentCommands()
        cmd._get_env = Mock(return_value=mock_env)

        # Create args namespace
        args = argparse.Namespace(environment="test-env")

        # ACT: Call status command
        cmd.status(args)

        # ASSERT: Capture output and verify detached HEAD is visible
        captured = capsys.readouterr()
        output = captured.out

        # Critical assertions for the bug fix
        assert "(detached HEAD)" in output, \
            "Status must show '(detached HEAD)' in header even when clean"

        assert "⚠️" in output, \
            "Status must show warning indicator (⚠️) not success (✓) when in detached HEAD"

        assert "You are in detached HEAD state" in output, \
            "Status must show explicit detached HEAD warning even when clean"

        assert "Any commits you make will not be saved to a branch" in output, \
            "Warning must explain the danger of detached HEAD"

        assert "cg checkout -b <branch-name>" in output, \
            "Must provide actionable guidance to fix detached HEAD"

    def test_status_shows_branch_when_on_branch(self, capsys):
        """Verify normal case: on branch with clean state shows success indicator."""
        # ARRANGE: Create mock environment on a branch with clean state
        mock_env = Mock()
        mock_env.name = "test-env"

        clean_status = EnvironmentStatus(
            git=GitStatus(
                current_branch="main",  # ← On a branch
                has_changes=False,
                nodes_added=[],
                nodes_removed=[],
                workflow_changes=[]
            ),
            workflow=DetailedWorkflowStatus(
                sync_status=WorkflowSyncStatus(
                    synced=[],
                    new=[],
                    modified=[],
                    deleted=[]
                ),
                analyzed_workflows=[]
            ),
            comparison=EnvironmentComparison(
                missing_nodes=[],
                extra_nodes=[],
                version_mismatches=[],
                packages_in_sync=True
            ),
            missing_models=[]
        )

        mock_env.status.return_value = clean_status
        mock_env.get_lifecycle_status.return_value = EnvironmentLifecycleStatus()

        cmd = EnvironmentCommands()
        cmd._get_env = Mock(return_value=mock_env)
        args = argparse.Namespace(environment="test-env")

        # ACT
        cmd.status(args)

        # ASSERT
        captured = capsys.readouterr()
        output = captured.out

        assert "(on main)" in output, \
            "Status must show branch name when on a branch"

        assert "(on main) ✓" in output, \
            "Status must show success indicator (✓) when on branch and clean"

        assert "detached HEAD" not in output, \
            "Must not show detached HEAD warning when on a branch"
