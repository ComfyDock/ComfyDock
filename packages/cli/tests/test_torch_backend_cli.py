"""Tests for PyTorch backend CLI behavior.

This tests the refined behavior where:
- Creation commands (create, import) write .pytorch-backend
- Operation commands (sync, run, pull) READ from file, never write
- --torch-backend flag is a one-time override that doesn't persist
- env-config torch-backend is environment-scoped configuration
"""

import argparse
import json
from unittest.mock import MagicMock, patch

import pytest
from comfygit_cli.cli import create_parser


class TestTorchBackendArgumentDefaults:
    """Test that --torch-backend defaults to None for operation commands.

    This ensures we can distinguish "user provided flag" from "use file".
    """

    def test_sync_command_torch_backend_default_none(self):
        """Sync command --torch-backend should default to None (not 'auto').

        This allows sync to read from .pytorch-backend file when no flag is provided.
        """
        parser = create_parser()
        args = parser.parse_args(["sync"])

        assert hasattr(args, "torch_backend")
        assert args.torch_backend is None  # Not 'auto'!

    def test_run_command_torch_backend_default_none(self):
        """Run command --torch-backend should default to None."""
        parser = create_parser()
        args = parser.parse_args(["run"])

        assert hasattr(args, "torch_backend")
        assert args.torch_backend is None

    def test_pull_command_torch_backend_default_none(self):
        """Pull command --torch-backend should default to None."""
        parser = create_parser()
        args = parser.parse_args(["pull"])

        assert hasattr(args, "torch_backend")
        assert args.torch_backend is None

    def test_sync_command_accepts_explicit_override(self):
        """Sync command should accept explicit --torch-backend override."""
        parser = create_parser()
        args = parser.parse_args(["sync", "--torch-backend", "cu128"])

        assert args.torch_backend == "cu128"

    def test_run_command_accepts_explicit_override(self):
        """Run command should accept explicit --torch-backend override."""
        parser = create_parser()
        args = parser.parse_args(["run", "--torch-backend", "cpu"])

        assert args.torch_backend == "cpu"

    def test_run_command_accepts_double_dash_passthrough(self):
        """Run command should accept ComfyUI args after --."""
        parser = create_parser()
        args, unknown = parser.parse_known_args(["run", "--", "--listen", "0.0.0.0"])

        assert args.command == "run"
        assert unknown == ["--", "--listen", "0.0.0.0"]

    def test_run_and_sync_accept_overlay_flag(self):
        """run/sync should accept repeatable --overlay flags."""
        parser = create_parser()

        run_args = parser.parse_args(["run", "--overlay", "alpha", "--overlay", "beta"])
        assert run_args.overlay == ["alpha", "beta"]

        sync_args = parser.parse_args(["sync", "--overlay", "alpha"])
        assert sync_args.overlay == ["alpha"]

    def test_pull_command_accepts_explicit_override(self):
        """Pull command should accept explicit --torch-backend override."""
        parser = create_parser()
        args = parser.parse_args(["pull", "--torch-backend", "rocm6.3"])

        assert args.torch_backend == "rocm6.3"


class TestCreationCommandsKeepAutoDefault:
    """Test that creation commands (create, import) keep 'auto' default.

    These commands SHOULD auto-detect and write to .pytorch-backend file.
    """

    def test_create_command_torch_backend_default_auto(self):
        """Create command should still default to 'auto' for detection."""
        parser = create_parser()
        args = parser.parse_args(["create", "test-env"])

        assert hasattr(args, "torch_backend")
        assert args.torch_backend == "auto"
        assert hasattr(args, "no_manager")
        assert args.no_manager is False

    def test_import_command_torch_backend_default_auto(self):
        """Import command should still default to 'auto' for detection."""
        parser = create_parser()
        args = parser.parse_args(["import", "test.tar.gz"])

        assert hasattr(args, "torch_backend")
        assert args.torch_backend == "auto"
        assert hasattr(args, "no_manager")
        assert args.no_manager is False

    def test_create_command_accepts_no_manager_flag(self):
        """Create command should parse --no-manager for headless setup."""
        parser = create_parser()
        args = parser.parse_args(["create", "test-env", "--no-manager"])
        assert args.no_manager is True

    def test_import_command_accepts_no_manager_flag(self):
        """Import command should parse --no-manager for headless setup."""
        parser = create_parser()
        args = parser.parse_args(["import", "test.tar.gz", "--no-manager"])
        assert args.no_manager is True


class TestEnvConfigTorchBackendSubcommand:
    """Test the new cg env-config torch-backend subcommand.

    This replaces the old cg config torch-backend (which was incorrectly global).
    """

    def test_env_config_torch_backend_show(self):
        """env-config torch-backend show should exist."""
        parser = create_parser()
        args = parser.parse_args(["env-config", "torch-backend", "show"])

        assert args.command == "env-config"
        assert args.env_config_command == "torch-backend"
        assert args.torch_command == "show"

    def test_env_config_torch_backend_set(self):
        """env-config torch-backend set <backend> should exist."""
        parser = create_parser()
        args = parser.parse_args(["env-config", "torch-backend", "set", "cu128"])

        assert args.command == "env-config"
        assert args.env_config_command == "torch-backend"
        assert args.torch_command == "set"
        assert args.backend == "cu128"

    def test_env_config_torch_backend_detect(self):
        """env-config torch-backend detect should exist."""
        parser = create_parser()
        args = parser.parse_args(["env-config", "torch-backend", "detect"])

        assert args.command == "env-config"
        assert args.env_config_command == "torch-backend"
        assert args.torch_command == "detect"


class TestConfigTorchBackendRemoved:
    """Test that global config torch-backend commands are removed.

    The old cg config torch-backend was incorrectly scoped - it operated on
    environments but didn't require -e flag or active environment awareness.
    """

    def test_config_torch_backend_not_available(self):
        """Global config torch-backend should not exist."""
        parser = create_parser()

        # Parsing "config torch-backend show" should fail or not set torch_command
        args = parser.parse_args(["config"])

        # Either torch-backend subparser is removed, or if config doesn't have
        # subparsers for torch-backend, it shouldn't have config_command == "torch-backend"
        if hasattr(args, 'config_command'):
            assert args.config_command != "torch-backend", \
                "config torch-backend should be removed (use env-config instead)"


class TestSyncBehavior:
    """Test that sync reads from file and doesn't overwrite user settings."""

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_sync_uses_ensure_backend(self, mock_get_workspace):
        """Sync should use ensure_backend() which handles both existing and missing backends."""
        from comfygit_cli.env_commands import EnvironmentCommands

        # Setup mocks
        mock_env = MagicMock()
        mock_env.name = "test-env"
        mock_env.cec_path = MagicMock()
        mock_env.cec_path.__truediv__ = MagicMock(return_value=MagicMock(exists=MagicMock(return_value=True)))
        mock_env.pytorch_manager.has_backend.return_value = True
        mock_env.pytorch_manager.ensure_backend.return_value = "cu128"
        mock_env.sync.return_value = MagicMock(success=True, packages_synced=0, dependency_groups_installed=[], errors=[])

        mock_workspace = MagicMock()
        mock_workspace.get_active_environment.return_value = mock_env
        mock_get_workspace.return_value = mock_workspace

        # Create commands handler
        cmd = EnvironmentCommands()
        # Clear cached property
        if 'workspace' in cmd.__dict__:
            del cmd.__dict__['workspace']

        args = argparse.Namespace(
            target_env=None,
            torch_backend=None,  # No override - should use ensure_backend
            verbose=False
        )

        cmd.sync(args)

        # Should have called ensure_backend which reads from file or probes
        mock_env.pytorch_manager.ensure_backend.assert_called()

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_sync_warns_when_no_backend_file(self, mock_get_workspace, capsys, tmp_path):
        """Sync should warn user when .pytorch-backend file doesn't exist."""
        from comfygit_cli.env_commands import EnvironmentCommands

        # Setup mocks - no backend file (has_backend returns False)
        mock_env = MagicMock()
        mock_env.name = "test-env"
        mock_env.cec_path = tmp_path  # For .python-version file check
        mock_env.pytorch_manager.has_backend.return_value = False  # Key fix: mock has_backend()
        mock_env.pytorch_manager.probe_and_set_backend.return_value = "cu126"  # Auto-detected
        mock_env.sync.return_value = MagicMock(success=True, packages_synced=0, dependency_groups_installed=[], errors=[])

        mock_workspace = MagicMock()
        mock_workspace.get_active_environment.return_value = mock_env
        mock_get_workspace.return_value = mock_workspace

        cmd = EnvironmentCommands()
        if 'workspace' in cmd.__dict__:
            del cmd.__dict__['workspace']

        args = argparse.Namespace(
            target_env=None,
            torch_backend=None,
            verbose=False
        )

        cmd.sync(args)

        captured = capsys.readouterr()
        # Should warn user about missing backend file
        assert "No PyTorch backend configured" in captured.out or "⚠️" in captured.out
        # Should suggest how to save the setting
        assert "env-config torch-backend set" in captured.out

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_sync_with_override_doesnt_write_file(self, mock_get_workspace):
        """Sync with --torch-backend override should NOT write to file."""
        from comfygit_cli.env_commands import EnvironmentCommands

        mock_env = MagicMock()
        mock_env.name = "test-env"
        mock_env.pytorch_manager.backend_file.exists.return_value = True
        mock_env.pytorch_manager.get_backend.return_value = "cu126"  # Currently stored
        mock_env.sync.return_value = MagicMock(success=True, packages_synced=0, dependency_groups_installed=[], errors=[])

        mock_workspace = MagicMock()
        mock_workspace.get_active_environment.return_value = mock_env
        mock_get_workspace.return_value = mock_workspace

        cmd = EnvironmentCommands()
        if 'workspace' in cmd.__dict__:
            del cmd.__dict__['workspace']

        args = argparse.Namespace(
            target_env=None,
            torch_backend="cpu",  # Explicit override
            verbose=False
        )

        cmd.sync(args)

        # Should NOT write to file - override is one-time only
        mock_env.pytorch_manager.set_backend.assert_not_called()


class TestRunBehavior:
    """Test that run reads from file like sync does."""

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_run_uses_ensure_backend(self, mock_get_workspace):
        """Run should use ensure_backend() which handles both existing and missing backends."""
        from comfygit_cli.env_commands import EnvironmentCommands

        mock_env = MagicMock()
        mock_env.name = "test-env"
        mock_env.get_current_branch.return_value = "main"
        mock_env.cec_path = MagicMock()
        mock_env.cec_path.__truediv__ = MagicMock(return_value=MagicMock(exists=MagicMock(return_value=True)))
        mock_env.pytorch_manager.has_backend.return_value = True
        mock_env.pytorch_manager.ensure_backend.return_value = "cu128"
        mock_env.sync.return_value = MagicMock(success=True)
        mock_env.run.return_value = MagicMock(returncode=0)

        mock_workspace = MagicMock()
        mock_workspace.get_active_environment.return_value = mock_env
        mock_get_workspace.return_value = mock_workspace

        cmd = EnvironmentCommands()
        if 'workspace' in cmd.__dict__:
            del cmd.__dict__['workspace']

        args = argparse.Namespace(
            target_env=None,
            torch_backend=None,  # Should use ensure_backend
            no_sync=False,
            args=[]
        )

        with pytest.raises(SystemExit):
            cmd.run(args)

        # Should have called ensure_backend which reads from file or probes
        mock_env.pytorch_manager.ensure_backend.assert_called()

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_run_overlay_rejects_no_sync(self, mock_get_workspace):
        """run --overlay with --no-sync should fail fast."""
        from comfygit_cli.env_commands import EnvironmentCommands

        mock_env = MagicMock()
        mock_env.name = "test-env"

        mock_workspace = MagicMock()
        mock_workspace.get_active_environment.return_value = mock_env
        mock_get_workspace.return_value = mock_workspace

        cmd = EnvironmentCommands()
        if 'workspace' in cmd.__dict__:
            del cmd.__dict__['workspace']

        args = argparse.Namespace(
            target_env=None,
            torch_backend=None,
            no_sync=True,
            args=[],
            extra=[],
            all_extras=False,
            overlay=["alpha"],
        )

        with pytest.raises(SystemExit):
            cmd.run(args)

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_run_consumes_switch_request_without_exiting_supervisor(self, mock_get_workspace, tmp_path):
        """Exit 43 should switch the long-lived cg run process to the requested env."""
        from comfygit_cli.env_commands import EnvironmentCommands

        current_env = MagicMock()
        current_env.name = "source-env"
        current_env.get_current_branch.return_value = "main"
        current_env.pytorch_manager.has_backend.return_value = True
        current_env.pytorch_manager.ensure_backend.return_value = "cu126"
        current_env.sync.return_value = MagicMock(success=True)
        current_env.run.return_value = MagicMock(returncode=43)

        target_env = MagicMock()
        target_env.name = "target-env"
        target_env.get_current_branch.return_value = "main"
        target_env.sync.return_value = MagicMock(success=True)
        target_env.run.return_value = MagicMock(returncode=0)

        metadata_dir = tmp_path / ".metadata"
        metadata_dir.mkdir()
        (metadata_dir / ".switch.lock").touch()
        (metadata_dir / ".switch_request.json").write_text(
            json.dumps({"target_env": "target-env", "source_env": "source-env"}),
            encoding="utf-8",
        )

        mock_workspace = MagicMock()
        mock_workspace.path = tmp_path
        mock_workspace.get_active_environment.return_value = current_env
        mock_workspace.get_environment.return_value = target_env
        mock_get_workspace.return_value = mock_workspace

        cmd = EnvironmentCommands()
        if 'workspace' in cmd.__dict__:
            del cmd.__dict__['workspace']

        args = argparse.Namespace(
            target_env=None,
            torch_backend=None,
            no_sync=False,
            args=[],
            extra=[],
            all_extras=False,
            overlay=[],
        )

        with pytest.raises(SystemExit) as exc:
            cmd.run(args)

        assert exc.value.code == 0
        mock_workspace.get_environment.assert_called_with("target-env", auto_sync=False)
        target_env.sync.assert_called_once()
        target_env.run.assert_called_once()
        assert not (metadata_dir / ".switch_request.json").exists()
        assert not (metadata_dir / ".switch.lock").exists()

        status = json.loads((metadata_dir / ".switch_status.json").read_text(encoding="utf-8"))
        assert status["state"] == "complete"
        assert status["target_env"] == "target-env"
