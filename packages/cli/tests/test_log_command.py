"""Tests for log command with branch/ref decorations."""
from argparse import Namespace
from io import StringIO
from unittest.mock import MagicMock, patch

from comfygit_cli.env_commands import EnvironmentCommands
from comfygit_core.models import GitCommitSummary


def _commit(
    hash: str,
    refs: str,
    message: str,
    date: str,
    date_relative: str,
) -> GitCommitSummary:
    return GitCommitSummary(
        hash=hash,
        refs=refs,
        message=message,
        date=date,
        date_relative=date_relative,
    )


class TestLogCommand:
    """Test 'cg log' command displays branch refs."""

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_log_displays_refs_in_compact_mode(self, mock_workspace):
        """Log command should display refs next to commit hash in compact mode."""
        # Setup mocks
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"

        # Mock commit history with refs
        mock_env.get_commit_history.return_value = [
            _commit(
                'a1b2c3d',
                'HEAD -> main, origin/main',
                'Latest commit',
                '2025-11-17 10:00:00',
                '5 minutes ago',
            ),
            _commit('e4f5g6h', 'feature-branch', 'Branch commit', '2025-11-17 09:00:00', '1 hour ago'),
            _commit('i7j8k9l', '', 'Old commit', '2025-11-16 10:00:00', '1 day ago'),
        ]
        mock_env.get_current_branch.return_value = "main"

        cmd = EnvironmentCommands()
        args = Namespace(
            limit=20,
            verbose=False,
            target_env=None
        )

        # Capture output
        output = StringIO()
        with patch('sys.stdout', output):
            cmd.log(args)

        result = output.getvalue()

        # Verify output contains refs next to hash
        # Format should be: hash (refs) message (date)
        assert 'a1b2c3d (HEAD -> main, origin/main)  Latest commit (5 minutes ago)' in result
        assert 'e4f5g6h (feature-branch)  Branch commit (1 hour ago)' in result

        # Commit without refs should not have empty parens
        assert 'i7j8k9l  Old commit (1 day ago)' in result
        assert 'i7j8k9l ()' not in result  # Should NOT have empty parens

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_log_displays_refs_in_verbose_mode(self, mock_workspace):
        """Log command should display refs in verbose mode."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"

        mock_env.get_commit_history.return_value = [
            _commit('a1b2c3d', 'HEAD -> main', 'Test commit', '2025-11-17 10:00:00 -0800', '5 minutes ago')
        ]
        mock_env.get_current_branch.return_value = "main"

        cmd = EnvironmentCommands()
        args = Namespace(
            limit=20,
            verbose=True,
            target_env=None
        )

        output = StringIO()
        with patch('sys.stdout', output):
            cmd.log(args)

        result = output.getvalue()

        # In verbose mode, refs should appear after hash on Commit line
        assert 'Commit:  a1b2c3d (HEAD -> main)' in result
        assert 'Date:    2025-11-17 10:00:00' in result
        assert 'Message: Test commit' in result

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_log_handles_empty_refs_gracefully(self, mock_workspace):
        """Log should handle commits with empty refs field."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"

        mock_env.get_commit_history.return_value = [
            _commit('abc123', '', 'Commit without refs', '2025-11-17 10:00:00', '1 hour ago')
        ]
        mock_env.get_current_branch.return_value = "main"

        cmd = EnvironmentCommands()
        args = Namespace(
            limit=20,
            verbose=False,
            target_env=None
        )

        output = StringIO()
        with patch('sys.stdout', output):
            cmd.log(args)

        result = output.getvalue()

        # Should display without refs
        assert 'abc123  Commit without refs (1 hour ago)' in result
        # Should NOT have empty parentheses
        assert '()' not in result

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_log_maintains_detached_head_warning(self, mock_workspace):
        """Log should still show detached HEAD warning when applicable."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"

        mock_env.get_commit_history.return_value = [
            _commit('abc123', 'tag: v1.0', 'Tagged commit', '2025-11-17 10:00:00', '1 hour ago')
        ]
        # Detached HEAD state
        mock_env.get_current_branch.return_value = None

        cmd = EnvironmentCommands()
        args = Namespace(
            limit=20,
            verbose=False,
            target_env=None
        )

        output = StringIO()
        with patch('sys.stdout', output):
            cmd.log(args)

        result = output.getvalue()

        # Should show refs
        assert 'abc123 (tag: v1.0)  Tagged commit (1 hour ago)' in result

        # Should still show detached HEAD warning
        assert 'detached HEAD state' in result
        assert 'Create a branch:' in result
