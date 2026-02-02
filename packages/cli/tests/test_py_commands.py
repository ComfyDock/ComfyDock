"""Unit tests for py add/remove/list commands."""
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from comfygit_cli.env_commands import EnvironmentCommands
from comfygit_core.models.exceptions import UVCommandError


class TestPyAdd:
    """Test 'cg py add' command handler."""

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_single_package(self, mock_workspace):
        """Should call add_dependencies with single package."""
        # Setup mocks
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.add_dependencies.return_value = {"output": "Added: requests", "substitutions": {}}

        # Create command handler
        cmd = EnvironmentCommands()

        # Create args
        args = Namespace(
            packages=["requests"],
            requirements=None,
            upgrade=False,
            target_env=None
        )

        # Execute
        with patch('builtins.print'):
            cmd.py_add(args)

        # Verify
        mock_env.add_dependencies.assert_called_once_with(
            packages=["requests"],
            requirements_file=None,
            upgrade=False,
            group=None,
            dev=False,
            editable=False,
            bounds=None
        )

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_multiple_packages(self, mock_workspace):
        """Should call add_dependencies with multiple packages."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.add_dependencies.return_value = {"output": "Added: 3 packages", "substitutions": {}}

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["requests", "pillow", "tqdm"],
            requirements=None,
            upgrade=False,
            target_env=None
        )

        with patch('builtins.print'):
            cmd.py_add(args)

        mock_env.add_dependencies.assert_called_once_with(
            packages=["requests", "pillow", "tqdm"],
            requirements_file=None,
            upgrade=False,
            group=None,
            dev=False,
            editable=False,
            bounds=None
        )

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_with_upgrade_flag(self, mock_workspace):
        """Should pass upgrade=True when --upgrade is specified."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.add_dependencies.return_value = {"output": "Upgraded: requests", "substitutions": {}}

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["requests"],
            requirements=None,
            upgrade=True,
            target_env=None
        )

        with patch('builtins.print'):
            cmd.py_add(args)

        mock_env.add_dependencies.assert_called_once_with(
            packages=["requests"],
            requirements_file=None,
            upgrade=True,
            group=None,
            dev=False,
            editable=False,
            bounds=None
        )

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_handles_uv_error(self, mock_workspace):
        """Should handle UVCommandError gracefully."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.add_dependencies.side_effect = UVCommandError(
            "Package not found",
            command=["uv", "add", "nonexistent"]
        )

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["nonexistent"],
            requirements=None,
            upgrade=False,
            target_env=None
        )

        with patch('builtins.print'):
            with pytest.raises(SystemExit) as exc_info:
                cmd.py_add(args)

        assert exc_info.value.code == 1

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_from_requirements_file(self, mock_workspace, tmp_path):
        """Should add packages from requirements.txt file."""

        # Create a real temporary requirements file
        reqs_file = tmp_path / "requirements.txt"
        reqs_file.write_text("requests>=2.0.0\npillow\n")

        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.add_dependencies.return_value = {"output": "Added packages from requirements", "substitutions": {}}

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=[],
            requirements=reqs_file,
            upgrade=False,
            target_env=None
        )

        with patch('builtins.print'):
            cmd.py_add(args)

        # Should call with absolute path to requirements_file
        mock_env.add_dependencies.assert_called_once_with(
            packages=None,
            requirements_file=reqs_file.resolve(),
            upgrade=False,
            group=None,
            dev=False,
            editable=False,
            bounds=None
        )

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_requirements_with_upgrade(self, mock_workspace, tmp_path):
        """Should support --upgrade with requirements file."""

        # Create a real temporary requirements file
        reqs_file = tmp_path / "requirements.txt"
        reqs_file.write_text("requests>=2.0.0\npillow\n")

        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.add_dependencies.return_value = {"output": "Upgraded packages from requirements", "substitutions": {}}

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=[],
            requirements=reqs_file,
            upgrade=True,
            target_env=None
        )

        with patch('builtins.print'):
            cmd.py_add(args)

        mock_env.add_dependencies.assert_called_once_with(
            packages=None,
            requirements_file=reqs_file.resolve(),
            upgrade=True,
            group=None,
            dev=False,
            editable=False,
            bounds=None
        )

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_errors_with_both_packages_and_requirements(self, mock_workspace, tmp_path):
        """Should error when both packages and requirements file are specified."""

        # Create a real temporary requirements file
        reqs_file = tmp_path / "requirements.txt"
        reqs_file.write_text("requests>=2.0.0\n")

        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["requests"],
            requirements=reqs_file,
            upgrade=False,
            target_env=None
        )

        with pytest.raises(SystemExit) as exc_info:
            with patch('builtins.print'):
                cmd.py_add(args)

        assert exc_info.value.code == 1

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_errors_with_neither_packages_nor_requirements(self, mock_workspace):
        """Should error when neither packages nor requirements file are specified."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=[],
            requirements=None,
            upgrade=False,
            target_env=None
        )

        with pytest.raises(SystemExit) as exc_info:
            with patch('builtins.print'):
                cmd.py_add(args)

        assert exc_info.value.code == 1

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_errors_with_nonexistent_requirements_file(self, mock_workspace):
        """Should error when requirements file doesn't exist."""
        from pathlib import Path

        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=[],
            requirements=Path("nonexistent.txt"),
            upgrade=False,
            target_env=None
        )

        with pytest.raises(SystemExit) as exc_info:
            with patch('builtins.print'):
                cmd.py_add(args)

        assert exc_info.value.code == 1


class TestPyRemove:
    """Test 'cg py remove' command handler."""

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_remove_single_package(self, mock_workspace):
        """Should call remove_dependencies with single package."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.remove_dependencies.return_value = {
            'removed': ['requests'],
            'skipped': []
        }

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["requests"],
            target_env=None
        )

        with patch('builtins.print'):
            cmd.py_remove(args)

        mock_env.remove_dependencies.assert_called_once_with(["requests"])

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_remove_multiple_packages(self, mock_workspace):
        """Should call remove_dependencies with multiple packages."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.remove_dependencies.return_value = {
            'removed': ['requests', 'pillow', 'tqdm'],
            'skipped': []
        }

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["requests", "pillow", "tqdm"],
            target_env=None
        )

        with patch('builtins.print'):
            cmd.py_remove(args)

        mock_env.remove_dependencies.assert_called_once_with(
            ["requests", "pillow", "tqdm"]
        )

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_remove_handles_uv_error(self, mock_workspace):
        """Should handle UVCommandError gracefully."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.remove_dependencies.side_effect = UVCommandError(
            "Package resolution error",
            command=["uv", "remove", "requests"]
        )

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["requests"],
            target_env=None
        )

        with patch('builtins.print'):
            with pytest.raises(SystemExit) as exc_info:
                cmd.py_remove(args)

        assert exc_info.value.code == 1

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_remove_missing_package_succeeds(self, mock_workspace):
        """Should succeed gracefully when package doesn't exist."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.remove_dependencies.return_value = {
            'removed': [],
            'skipped': ['nonexistent']
        }

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["nonexistent"],
            target_env=None
        )

        with patch('builtins.print') as mock_print:
            cmd.py_remove(args)

        # Should call remove_dependencies (which handles the filtering)
        mock_env.remove_dependencies.assert_called_once_with(["nonexistent"])

        # Should print informative message
        printed = ' '.join(str(call) for call in mock_print.call_args_list)
        assert "not in dependencies" in printed

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_remove_mixed_existing_and_missing(self, mock_workspace):
        """Should remove existing packages and skip missing ones."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.remove_dependencies.return_value = {
            'removed': ['requests', 'pillow'],
            'skipped': ['nonexistent']
        }

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["requests", "nonexistent", "pillow"],
            target_env=None
        )

        with patch('builtins.print') as mock_print:
            cmd.py_remove(args)

        # Should call remove_dependencies with all packages (filtering happens in core)
        mock_env.remove_dependencies.assert_called_once_with(["requests", "nonexistent", "pillow"])

        # Should mention skipped packages
        printed = ' '.join(str(call) for call in mock_print.call_args_list)
        assert "Skipped" in printed
        assert "nonexistent" in printed


class TestPyAddTier2Flags:
    """Test 'cg py add' with Tier 2 power-user flags."""

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_with_group_flag(self, mock_workspace):
        """Should pass group flag to add_dependencies for optional dependencies."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.add_dependencies.return_value = {"output": "Added to group optional-cuda", "substitutions": {}}

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["sageattention"],
            requirements=None,
            upgrade=False,
            group="optional-cuda",
            dev=False,
            editable=False,
            bounds=None,
            target_env=None
        )

        with patch('builtins.print'):
            cmd.py_add(args)

        mock_env.add_dependencies.assert_called_once_with(
            packages=["sageattention"],
            requirements_file=None,
            upgrade=False,
            group="optional-cuda",
            dev=False,
            editable=False,
            bounds=None
        )

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_with_dev_flag(self, mock_workspace):
        """Should pass dev=True for development dependencies."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.add_dependencies.return_value = {"output": "Added to dev dependencies", "substitutions": {}}

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["pytest", "black"],
            requirements=None,
            upgrade=False,
            group=None,
            dev=True,
            editable=False,
            bounds=None,
            target_env=None
        )

        with patch('builtins.print'):
            cmd.py_add(args)

        mock_env.add_dependencies.assert_called_once_with(
            packages=["pytest", "black"],
            requirements_file=None,
            upgrade=False,
            group=None,
            dev=True,
            editable=False,
            bounds=None
        )

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_with_editable_flag(self, mock_workspace):
        """Should pass editable=True for local package development."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.add_dependencies.return_value = {"output": "Added as editable", "substitutions": {}}

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["/path/to/mypackage"],
            requirements=None,
            upgrade=False,
            group=None,
            dev=False,
            editable=True,
            bounds=None,
            target_env=None
        )

        with patch('builtins.print'):
            cmd.py_add(args)

        mock_env.add_dependencies.assert_called_once_with(
            packages=["/path/to/mypackage"],
            requirements_file=None,
            upgrade=False,
            group=None,
            dev=False,
            editable=True,
            bounds=None
        )

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_with_bounds_flag(self, mock_workspace):
        """Should pass bounds for version specifier style control."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.add_dependencies.return_value = {"output": "Added with exact bounds", "substitutions": {}}

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["torch==2.4.1"],
            requirements=None,
            upgrade=False,
            group=None,
            dev=False,
            editable=False,
            bounds="exact",
            target_env=None
        )

        with patch('builtins.print'):
            cmd.py_add(args)

        mock_env.add_dependencies.assert_called_once_with(
            packages=["torch==2.4.1"],
            requirements_file=None,
            upgrade=False,
            group=None,
            dev=False,
            editable=False,
            bounds="exact"
        )

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_add_with_combined_flags(self, mock_workspace):
        """Should support combining multiple Tier 2 flags."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.add_dependencies.return_value = {"output": "Added with multiple flags", "substitutions": {}}

        cmd = EnvironmentCommands()
        args = Namespace(
            packages=["mypackage"],
            requirements=None,
            upgrade=True,
            group="optional-features",
            dev=False,
            editable=True,
            bounds="minor",
            target_env=None
        )

        with patch('builtins.print'):
            cmd.py_add(args)

        mock_env.add_dependencies.assert_called_once_with(
            packages=["mypackage"],
            requirements_file=None,
            upgrade=True,
            group="optional-features",
            dev=False,
            editable=True,
            bounds="minor"
        )


class TestPyUvPassthrough:
    """Test 'cg py uv' UV passthrough for advanced users."""

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    @patch('comfygit_cli.env_commands.subprocess.run')
    def test_uv_passthrough_basic_command(self, mock_subprocess, mock_workspace):
        """Should execute UV command with environment context."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.cec_path = Path("/workspace/test-env/.cec")
        mock_env.venv_path = Path("/workspace/test-env/ComfyUI/.venv")
        mock_env.workspace_paths.cache = Path("/workspace/cache")
        mock_env.uv_manager.uv._binary = "/usr/bin/uv"

        # Mock subprocess to return success
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_subprocess.return_value = mock_result

        cmd = EnvironmentCommands()
        args = Namespace(
            uv_args=["add", "--group", "optional-cuda", "sageattention"],
            target_env=None
        )

        with pytest.raises(SystemExit) as exc_info:
            cmd.py_uv(args)

        # Should exit with UV's return code
        assert exc_info.value.code == 0

        # Should call subprocess with correct command
        mock_subprocess.assert_called_once()
        call_args = mock_subprocess.call_args
        assert call_args[0][0] == ["/usr/bin/uv", "add", "--group", "optional-cuda", "sageattention"]

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    @patch('comfygit_cli.env_commands.subprocess.run')
    def test_uv_passthrough_sets_environment_vars(self, mock_subprocess, mock_workspace):
        """Should set UV environment variables for context."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.cec_path = Path("/workspace/test-env/.cec")
        mock_env.venv_path = Path("/workspace/test-env/ComfyUI/.venv")
        mock_env.workspace_paths.cache = Path("/workspace/cache")
        mock_env.uv_manager.uv._binary = "/usr/bin/uv"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_subprocess.return_value = mock_result

        cmd = EnvironmentCommands()
        args = Namespace(
            uv_args=["sync", "--frozen"],
            target_env=None
        )

        with pytest.raises(SystemExit):
            cmd.py_uv(args)

        # Check environment variables were set
        call_args = mock_subprocess.call_args
        env_vars = call_args[1]['env']
        assert env_vars["UV_PROJECT_ENVIRONMENT"] == str(Path("/workspace/test-env/ComfyUI/.venv"))
        assert env_vars["UV_CACHE_DIR"] == str(Path("/workspace/cache/uv_cache"))

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    @patch('comfygit_cli.env_commands.subprocess.run')
    def test_uv_passthrough_sets_working_directory(self, mock_subprocess, mock_workspace):
        """Should execute UV in .cec directory."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.cec_path = Path("/workspace/test-env/.cec")
        mock_env.venv_path = Path("/workspace/test-env/ComfyUI/.venv")
        mock_env.workspace_paths.cache = Path("/workspace/cache")
        mock_env.uv_manager.uv._binary = "/usr/bin/uv"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_subprocess.return_value = mock_result

        cmd = EnvironmentCommands()
        args = Namespace(
            uv_args=["lock"],
            target_env=None
        )

        with pytest.raises(SystemExit):
            cmd.py_uv(args)

        # Check working directory
        call_args = mock_subprocess.call_args
        assert call_args[1]['cwd'] == Path("/workspace/test-env/.cec")

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_uv_passthrough_empty_args_shows_help(self, mock_workspace):
        """Should show usage message when no UV args provided."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"

        cmd = EnvironmentCommands()
        args = Namespace(
            uv_args=[],
            target_env=None
        )

        with pytest.raises(SystemExit) as exc_info:
            with patch('builtins.print') as mock_print:
                cmd.py_uv(args)

        # Should exit with error
        assert exc_info.value.code == 1

        # Should print usage message
        printed = ' '.join(str(call) for call in mock_print.call_args_list)
        assert "Usage" in printed or "usage" in printed.lower()
        assert "uv" in printed.lower()

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    @patch('comfygit_cli.env_commands.subprocess.run')
    def test_uv_passthrough_propagates_exit_code(self, mock_subprocess, mock_workspace):
        """Should exit with UV's error code on failure."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.cec_path = Path("/workspace/test-env/.cec")
        mock_env.venv_path = Path("/workspace/test-env/ComfyUI/.venv")
        mock_env.workspace_paths.cache = Path("/workspace/cache")
        mock_env.uv_manager.uv._binary = "/usr/bin/uv"

        # Mock subprocess to return failure
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_subprocess.return_value = mock_result

        cmd = EnvironmentCommands()
        args = Namespace(
            uv_args=["add", "nonexistent-package"],
            target_env=None
        )

        with pytest.raises(SystemExit) as exc_info:
            with patch('builtins.print'):
                cmd.py_uv(args)

        # Should exit with UV's return code
        assert exc_info.value.code == 1


class TestPyList:
    """Test 'cg py list' command handler."""

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_list_empty_dependencies(self, mock_workspace):
        """Should display message when no dependencies exist."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.list_dependencies.return_value = {"dependencies": []}

        cmd = EnvironmentCommands()
        args = Namespace(target_env=None, all=False)

        with patch('builtins.print') as mock_print:
            cmd.py_list(args)

        # Verify "No project dependencies" was printed
        calls = [str(call) for call in mock_print.call_args_list]
        assert any("No project dependencies" in call for call in calls)

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_list_shows_dependencies(self, mock_workspace):
        """Should display all dependencies."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.list_dependencies.return_value = {
            "dependencies": [
                "requests>=2.0.0",
                "pillow",
                "tqdm>=4.0.0"
            ]
        }

        cmd = EnvironmentCommands()
        args = Namespace(target_env=None, all=False)

        with patch('builtins.print') as mock_print:
            cmd.py_list(args)

        # Verify packages were printed
        calls = [str(call) for call in mock_print.call_args_list]
        output = "\n".join(calls)
        assert "requests>=2.0.0" in output
        assert "pillow" in output
        assert "tqdm>=4.0.0" in output

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_list_with_all_flag(self, mock_workspace):
        """Should display all dependencies including groups when --all is used."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.list_dependencies.return_value = {
            "dependencies": ["requests>=2.0.0", "pillow"],
            "test-group": ["pytest", "pytest-cov"],
            "dev-group": ["black", "ruff"]
        }

        cmd = EnvironmentCommands()
        args = Namespace(target_env=None, all=True)

        with patch('builtins.print') as mock_print:
            cmd.py_list(args)

        # Verify all packages were printed
        calls = [str(call) for call in mock_print.call_args_list]
        output = "\n".join(calls)
        assert "requests>=2.0.0" in output
        assert "pillow" in output
        assert "pytest" in output
        assert "pytest-cov" in output
        assert "black" in output
        assert "ruff" in output
        # Verify group names appear
        assert "test-group" in output
        assert "dev-group" in output
