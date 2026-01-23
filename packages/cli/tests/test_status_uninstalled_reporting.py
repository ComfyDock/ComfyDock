"""CLI test for status reporting of uninstalled nodes.

Tests the _print_workflow_issues() method to ensure it correctly reports
uninstalled packages after resolution.
"""
from comfygit_cli.env_commands import EnvironmentCommands
from comfygit_core.models.workflow import (
    WorkflowAnalysisStatus,
    WorkflowDependencies,
    ResolutionResult,
)


class TestStatusUninstalledReporting:
    """Test that CLI status correctly reports uninstalled nodes."""

    def test_print_workflow_issues_shows_uninstalled_packages(self, capsys):
        """
        Test _print_workflow_issues() reports uninstalled nodes correctly.

        When nodes are resolved but not yet installed, the CLI should
        display "X packages needed for installation".
        """
        # ARRANGE: Create a WorkflowAnalysisStatus with uninstalled nodes
        wf_status = WorkflowAnalysisStatus(
            name="test_workflow",
            sync_state="synced",
            dependencies=WorkflowDependencies(workflow_name="test_workflow"),
            resolution=ResolutionResult(workflow_name="test_workflow"),
            uninstalled_nodes=["node-3"],  # 1 package resolved but not installed
        )

        # ACT: Call _print_workflow_issues
        env_commands = EnvironmentCommands()
        env_commands._print_workflow_issues(wf_status)

        output = capsys.readouterr().out

        # ASSERT: Should report 1 package needed
        assert "1 packages needed for installation" in output, \
            f"Output should show 1 package needed, got: {output}"

    def test_print_workflow_issues_shows_nothing_when_all_installed(self, capsys):
        """Test _print_workflow_issues() shows nothing when all nodes installed."""
        # ARRANGE: Create a WorkflowAnalysisStatus with no issues
        wf_status = WorkflowAnalysisStatus(
            name="test_workflow",
            sync_state="synced",
            dependencies=WorkflowDependencies(workflow_name="test_workflow"),
            resolution=ResolutionResult(workflow_name="test_workflow"),
            uninstalled_nodes=[],  # All resolved nodes are installed
        )

        # ACT: Call _print_workflow_issues
        env_commands = EnvironmentCommands()
        env_commands._print_workflow_issues(wf_status)

        output = capsys.readouterr().out

        # ASSERT: Should not mention packages needed
        assert "packages needed" not in output, \
            f"Output should not show packages needed when all installed, got: {output}"
