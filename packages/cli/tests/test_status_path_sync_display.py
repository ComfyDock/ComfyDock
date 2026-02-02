"""Test that CLI status displays path sync warnings correctly."""

import sys
from pathlib import Path
from unittest.mock import Mock

# Import CLI command handler
sys.path.insert(0, str(Path(__file__).parent.parent))
from comfygit_cli.env_commands import EnvironmentCommands

# Import core models
from comfygit_core.models.workflow import (
    ResolutionResult,
    WorkflowAnalysisStatus,
)


class TestStatusPathSyncDisplay:
    """Test that CLI status displays path sync warnings."""

    def test_print_workflow_issues_shows_path_sync_warning(self, capsys):
        """Verify path sync warnings appear first in issue output."""
        # ARRANGE: Create a mock workflow analysis with path sync issues
        mock_analysis = Mock(spec=WorkflowAnalysisStatus)
        mock_analysis.models_needing_path_sync_count = 2
        mock_analysis.models_with_category_mismatch_count = 0
        mock_analysis.has_category_mismatch_issues = False
        mock_analysis.uninstalled_count = 0
        mock_analysis.resolution = Mock(spec=ResolutionResult)
        mock_analysis.resolution.nodes_unresolved = []
        mock_analysis.resolution.models_unresolved = []
        mock_analysis.resolution.models_ambiguous = []
        mock_analysis.resolution.models_resolved = []

        # ACT: Call the method
        cmd = EnvironmentCommands()
        cmd._print_workflow_issues(mock_analysis)

        # ASSERT: Check output contains path sync warning
        captured = capsys.readouterr()
        assert "2 model paths need syncing" in captured.out

    def test_print_workflow_issues_shows_path_sync_first(self, capsys):
        """Verify path sync appears before other issues."""
        # ARRANGE: Create mock with both path sync and other issues
        mock_analysis = Mock(spec=WorkflowAnalysisStatus)
        mock_analysis.models_needing_path_sync_count = 1
        mock_analysis.models_with_category_mismatch_count = 0
        mock_analysis.has_category_mismatch_issues = False
        mock_analysis.uninstalled_count = 2
        mock_analysis.resolution = Mock(spec=ResolutionResult)
        mock_analysis.resolution.nodes_unresolved = []
        mock_analysis.resolution.models_unresolved = []
        mock_analysis.resolution.models_ambiguous = []
        mock_analysis.resolution.models_resolved = []

        # ACT: Call the method
        cmd = EnvironmentCommands()
        cmd._print_workflow_issues(mock_analysis)

        # ASSERT: Path sync should appear before uninstalled packages
        captured = capsys.readouterr()
        output = captured.out

        path_sync_pos = output.find("model paths need syncing")
        packages_pos = output.find("packages needed for installation")

        assert path_sync_pos >= 0, "Should show path sync warning"
        assert packages_pos >= 0, "Should show packages warning"
        assert path_sync_pos < packages_pos, "Path sync should appear before packages"

    def test_print_workflow_issues_no_warning_when_paths_synced(self, capsys):
        """Verify no path sync warning when paths are correct."""
        # ARRANGE: Create mock with no path sync issues
        mock_analysis = Mock(spec=WorkflowAnalysisStatus)
        mock_analysis.models_needing_path_sync_count = 0
        mock_analysis.models_with_category_mismatch_count = 0
        mock_analysis.has_category_mismatch_issues = False
        mock_analysis.uninstalled_count = 0
        mock_analysis.resolution = Mock(spec=ResolutionResult)
        mock_analysis.resolution.nodes_unresolved = []
        mock_analysis.resolution.models_unresolved = []
        mock_analysis.resolution.models_ambiguous = []
        mock_analysis.resolution.models_resolved = []

        # ACT: Call the method
        cmd = EnvironmentCommands()
        cmd._print_workflow_issues(mock_analysis)

        # ASSERT: Should not show any warnings
        captured = capsys.readouterr()
        assert "model paths need syncing" not in captured.out
