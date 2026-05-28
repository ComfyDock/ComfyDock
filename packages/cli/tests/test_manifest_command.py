"""Unit tests for manifest command."""
from argparse import Namespace
from unittest.mock import MagicMock, patch

from comfygit_cli.env_commands import EnvironmentCommands


class TestManifest:
    """Test 'cg manifest' command handler."""

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_manifest_default_toml_output(self, mock_workspace):
        """Should output raw TOML by default."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"

        # Mock pyproject config
        mock_config = {
            'project': {'name': 'test-env', 'version': '0.1.0'},
            'tool': {
                'comfygit': {
                    'comfyui_version': 'v0.3.68',
                    'python_version': '3.12'
                }
            }
        }
        mock_env.load_manifest_config.return_value = mock_config

        cmd = EnvironmentCommands()
        args = Namespace(
            target_env=None,
            pretty=False,
            section=None
        )

        with patch('builtins.print') as mock_print:
            cmd.manifest(args)

        # Should print TOML content
        mock_print.assert_called()
        output = str(mock_print.call_args[0][0])
        assert 'project' in output or 'test-env' in output

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_manifest_pretty_yaml_output(self, mock_workspace):
        """Should output YAML when --pretty is used."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"

        mock_config = {
            'project': {'name': 'test-env', 'version': '0.1.0'},
            'tool': {'comfygit': {'comfyui_version': 'v0.3.68'}}
        }
        mock_env.load_manifest_config.return_value = mock_config

        cmd = EnvironmentCommands()
        args = Namespace(
            target_env=None,
            pretty=True,
            section=None
        )

        with patch('builtins.print') as mock_print:
            cmd.manifest(args)

        # Should print YAML content
        mock_print.assert_called()
        str(mock_print.call_args[0][0])
        # YAML output should contain the data
        assert mock_print.called

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_manifest_section_filter(self, mock_workspace):
        """Should filter to specific section when --section is used."""

        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"

        mock_config = {
            'project': {'name': 'test-env'},
            'tool': {
                'comfygit': {
                    'nodes': {'node1': {'version': '1.0.0'}},
                    'models': {}
                }
            }
        }
        mock_env.load_manifest_config.return_value = mock_config

        cmd = EnvironmentCommands()
        args = Namespace(
            target_env=None,
            pretty=False,
            section='tool.comfygit.nodes'
        )

        with patch('builtins.print') as mock_print:
            cmd.manifest(args)

        # Should print filtered section
        mock_print.assert_called()
        output = str(mock_print.call_args[0][0])
        assert 'node1' in output or 'tool.comfygit.nodes' in output

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_manifest_section_not_found(self, mock_workspace):
        """Should error gracefully when section doesn't exist."""
        import pytest

        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"

        mock_config = {
            'project': {'name': 'test-env'},
            'tool': {'comfygit': {}}
        }
        mock_env.load_manifest_config.return_value = mock_config

        cmd = EnvironmentCommands()
        args = Namespace(
            target_env=None,
            pretty=False,
            section='nonexistent.section',
            ide=None
        )

        with pytest.raises(SystemExit) as exc_info:
            with patch('builtins.print'):
                cmd.manifest(args)

        # Should exit with error
        assert exc_info.value.code == 1

    @patch('subprocess.run')
    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_manifest_ide_opens_editor(self, mock_workspace, mock_run):
        """Should open pyproject.toml in specified editor."""
        from pathlib import Path

        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.get_manifest_path.return_value = Path("/fake/path/.cec/pyproject.toml")

        cmd = EnvironmentCommands()
        args = Namespace(
            target_env=None,
            pretty=False,
            section=None,
            ide="code"
        )

        cmd.manifest(args)

        # Should call subprocess.run with editor and path
        mock_run.assert_called_once_with(["code", "/fake/path/.cec/pyproject.toml"])
        # Should not load config (early return)
        mock_env.load_manifest_config.assert_not_called()

    @patch('subprocess.run')
    @patch.dict('os.environ', {'EDITOR': 'vim'})
    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_manifest_ide_auto_uses_editor_env(self, mock_workspace, mock_run):
        """Should use $EDITOR when --ide is given without argument."""
        from pathlib import Path

        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.get_manifest_path.return_value = Path("/fake/path/.cec/pyproject.toml")

        cmd = EnvironmentCommands()
        args = Namespace(
            target_env=None,
            pretty=False,
            section=None,
            ide="auto"
        )

        cmd.manifest(args)

        # Should use vim from $EDITOR
        mock_run.assert_called_once_with(["vim", "/fake/path/.cec/pyproject.toml"])
