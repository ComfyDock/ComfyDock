"""Tests for manager commands (cg manager status/update)."""
import argparse
from unittest.mock import MagicMock, patch

from comfygit_core.models.shared import ManagerStatus, ManagerUpdateResult


class TestManagerCommands:
    """Tests for manager status and update CLI commands."""

    def test_manager_status_shows_not_installed(self, capsys):
        """manager status shows 'not installed' when manager is missing."""
        from comfygit_cli.env_commands import EnvironmentCommands

        env_cmds = EnvironmentCommands()

        # Mock environment
        mock_env = MagicMock()
        mock_env.name = "test-env"
        mock_env.get_manager_status.return_value = ManagerStatus(
            current_version=None,
            latest_version="0.3.0",
            update_available=False,
            is_legacy=False,
            is_tracked=False,
        )

        with patch.object(env_cmds, "_get_env", return_value=mock_env):
            args = argparse.Namespace(target_env="test-env")
            env_cmds.manager_status(args)

        captured = capsys.readouterr()
        assert "not installed" in captured.out
        assert "manager update" in captured.out

    def test_manager_status_shows_legacy(self, capsys):
        """manager status shows legacy notice for symlinked installations."""
        from comfygit_cli.env_commands import EnvironmentCommands

        env_cmds = EnvironmentCommands()

        mock_env = MagicMock()
        mock_env.name = "test-env"
        mock_env.get_manager_status.return_value = ManagerStatus(
            current_version="0.2.0",
            latest_version="0.3.0",
            update_available=True,
            is_legacy=True,
            is_tracked=False,
        )

        with patch.object(env_cmds, "_get_env", return_value=mock_env):
            args = argparse.Namespace(target_env="test-env")
            env_cmds.manager_status(args)

        captured = capsys.readouterr()
        assert "Legacy" in captured.out
        assert "manager update" in captured.out

    def test_manager_status_shows_update_available(self, capsys):
        """manager status shows update available for tracked installations."""
        from comfygit_cli.env_commands import EnvironmentCommands

        env_cmds = EnvironmentCommands()

        mock_env = MagicMock()
        mock_env.name = "test-env"
        mock_env.get_manager_status.return_value = ManagerStatus(
            current_version="0.2.0",
            latest_version="0.3.0",
            update_available=True,
            is_legacy=False,
            is_tracked=True,
        )

        with patch.object(env_cmds, "_get_env", return_value=mock_env):
            args = argparse.Namespace(target_env="test-env")
            env_cmds.manager_status(args)

        captured = capsys.readouterr()
        assert "Update available" in captured.out
        assert "0.2.0" in captured.out
        assert "0.3.0" in captured.out

    def test_manager_status_shows_up_to_date(self, capsys):
        """manager status shows up to date when no update needed."""
        from comfygit_cli.env_commands import EnvironmentCommands

        env_cmds = EnvironmentCommands()

        mock_env = MagicMock()
        mock_env.name = "test-env"
        mock_env.get_manager_status.return_value = ManagerStatus(
            current_version="0.3.0",
            latest_version="0.3.0",
            update_available=False,
            is_legacy=False,
            is_tracked=True,
        )

        with patch.object(env_cmds, "_get_env", return_value=mock_env):
            args = argparse.Namespace(target_env="test-env")
            env_cmds.manager_status(args)

        captured = capsys.readouterr()
        assert "Up to date" in captured.out

    def test_manager_update_calls_env_update_manager(self, capsys):
        """manager update calls environment update_manager method."""
        from comfygit_cli.env_commands import EnvironmentCommands

        env_cmds = EnvironmentCommands()

        mock_env = MagicMock()
        mock_env.name = "test-env"
        mock_env.get_manager_status.return_value = ManagerStatus(
            current_version="0.2.0",
            latest_version="0.3.0",
            update_available=True,
            is_legacy=False,
            is_tracked=True,
        )
        mock_env.update_manager.return_value = ManagerUpdateResult(
            changed=True,
            message="Updated from 0.2.0 to 0.3.0",
            old_version="0.2.0",
            new_version="0.3.0",
        )

        with patch.object(env_cmds, "_get_env", return_value=mock_env):
            args = argparse.Namespace(target_env="test-env", version=None, yes=True)
            env_cmds.manager_update(args)

        mock_env.update_manager.assert_called_once()
        captured = capsys.readouterr()
        assert "Updated" in captured.out or "Updating" in captured.out

    def test_manager_update_shows_migration_message_for_legacy(self, capsys):
        """manager update shows migration message for legacy installations."""
        from comfygit_cli.env_commands import EnvironmentCommands

        env_cmds = EnvironmentCommands()

        mock_env = MagicMock()
        mock_env.name = "test-env"
        mock_env.get_manager_status.return_value = ManagerStatus(
            current_version="0.2.0",
            latest_version="0.3.0",
            update_available=True,
            is_legacy=True,
            is_tracked=False,
        )
        mock_env.update_manager.return_value = ManagerUpdateResult(
            changed=True,
            was_migration=True,
            message="Migrated and updated to 0.3.0",
            old_version="0.2.0",
            new_version="0.3.0",
        )

        with patch.object(env_cmds, "_get_env", return_value=mock_env):
            args = argparse.Namespace(target_env="test-env", version=None, yes=True)
            env_cmds.manager_update(args)

        captured = capsys.readouterr()
        assert "Migrating" in captured.out


class TestInitNoSystemNodes:
    """Tests that init no longer installs system nodes."""

    def test_init_does_not_install_system_nodes(self, tmp_path):
        """init should not call _install_system_nodes (removed)."""
        from comfygit_cli.global_commands import GlobalCommands

        global_cmds = GlobalCommands()

        # Mock workspace factory and creation
        mock_workspace = MagicMock()
        mock_workspace.paths.root = tmp_path
        mock_workspace.path = tmp_path
        mock_workspace.update_registry_data.return_value = True
        mock_workspace.get_models_directory.return_value = tmp_path / "models"

        with patch("comfygit_cli.global_commands.WorkspaceFactory") as mock_factory:
            mock_factory.get_paths.return_value = mock_workspace.paths
            mock_factory.create.return_value = mock_workspace

            with patch.object(global_cmds, "_setup_models_directory"):
                args = argparse.Namespace(
                    path=None,
                    models_dir=None,
                    yes=True,
                )

                global_cmds.init(args)

                # Verify workspace was created (no system nodes installation)
                mock_factory.create.assert_called_once()

    def test_bare_flag_no_longer_exists(self):
        """--bare flag should not exist in init parser."""
        from comfygit_cli.cli import create_parser

        parser = create_parser()

        # Find the init subparser through the subparsers action
        init_action = None
        for action in parser._subparsers._actions:
            if hasattr(action, "choices") and action.choices is not None:
                if "init" in action.choices:
                    init_action = action.choices["init"]
                    break

        assert init_action is not None, "init subparser should exist"

        # Check that --bare is not in the init parser
        option_strings = []
        for action in init_action._actions:
            option_strings.extend(action.option_strings)

        assert "--bare" not in option_strings


class TestStatusLegacyManagerNotice:
    """Tests that status command shows legacy manager notice."""

    def test_status_shows_legacy_notice_even_when_clean(self, capsys):
        """status should show legacy manager notice even when environment is clean.

        Bug: Previously the status command returned early for clean environments,
        skipping the legacy manager notice check.
        """
        from comfygit_cli.env_commands import EnvironmentCommands
        from comfygit_core.models.environment import (
            EnvironmentComparison,
            EnvironmentStatus,
            GitStatus,
        )
        from comfygit_core.models.shared import ManagerStatus
        from comfygit_core.models.workflow import DetailedWorkflowStatus, WorkflowSyncStatus

        env_cmds = EnvironmentCommands()

        # Mock a clean environment with legacy manager
        mock_env = MagicMock()
        mock_env.name = "test-env"

        # Create clean status (no workflows, no changes, synced)
        mock_env.status.return_value = EnvironmentStatus(
            git=GitStatus(
                current_branch="main",
                has_changes=False,
            ),
            workflow=DetailedWorkflowStatus(
                sync_status=WorkflowSyncStatus(
                    synced=[],
                    new=[],
                    modified=[],
                    deleted=[],
                ),
                analyzed_workflows=[],
            ),
            comparison=EnvironmentComparison(
                missing_nodes=[],
                extra_nodes=[],
                version_mismatches=[],
                packages_in_sync=True,
            ),
            missing_models=[],
        )

        # Legacy manager detected
        mock_env.get_manager_status.return_value = ManagerStatus(
            current_version="0.2.0",
            latest_version="0.3.0",
            update_available=True,
            is_legacy=True,
            is_tracked=False,
        )

        with patch.object(env_cmds, "_get_env", return_value=mock_env):
            args = argparse.Namespace(target_env="test-env", verbose=False)
            env_cmds.status(args)

        captured = capsys.readouterr()
        # Should show clean state
        assert "No workflows" in captured.out
        assert "No uncommitted changes" in captured.out
        # AND also show legacy notice
        assert "Legacy manager detected" in captured.out


class TestLegacyWorkspaceNotice:
    """Tests for legacy notice in get_workspace_or_exit.

    Note: Legacy notices have been moved to per-environment level.
    The workspace-level notice has been removed. These tests verify
    that get_workspace_or_exit() does NOT show legacy notices.
    """

    def test_no_legacy_notice_at_workspace_level(self, capsys):
        """Workspace-level legacy notice has been removed."""
        from comfygit_cli import cli_utils

        mock_workspace = MagicMock()
        mock_workspace.has_legacy_system_nodes.return_value = True

        with patch.object(cli_utils.WorkspaceFactory, "find", return_value=mock_workspace):
            with patch.object(cli_utils.WorkspaceLogger, "set_workspace_path"):
                result = cli_utils.get_workspace_or_exit()

        assert result == mock_workspace
        captured = capsys.readouterr()
        # Legacy notices are now per-environment, not workspace-level
        assert "Legacy workspace" not in captured.out
        assert "Legacy" not in captured.out
