"""Test CLI commands for dependency group removal."""

from argparse import Namespace
from unittest.mock import patch


class TestPyRemoveGroupCLI:
    """Test py remove-group and py remove --group commands."""

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_py_remove_group_command(self, mock_workspace, test_env):
        """Should call remove_group on the pyproject dependencies handler."""
        # ARRANGE
        mock_workspace.return_value.get_active_environment.return_value = test_env

        from comfygit_cli.env_commands import EnvironmentCommands

        cmd = EnvironmentCommands()
        args = Namespace(
            target_env=None,  # Uses active
            group="optional-test"
        )

        # Add a group first
        config = test_env.pyproject.load()
        config.setdefault("dependency-groups", {})
        config["dependency-groups"]["optional-test"] = ["pytest>=7.0", "coverage>=6.0"]
        test_env.pyproject.save(config)

        # ACT: Call the command
        with patch('builtins.print'):
            cmd.py_remove_group(args)

        # ASSERT: Group should be removed
        groups = test_env.pyproject.dependencies.get_groups()
        assert "optional-test" not in groups

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_py_remove_with_group_flag(self, mock_workspace, test_env):
        """Should remove packages from a group using --group flag."""
        # ARRANGE
        mock_workspace.return_value.get_active_environment.return_value = test_env

        config = test_env.pyproject.load()
        config.setdefault("dependency-groups", {})
        config["dependency-groups"]["optional-ml"] = [
            "numpy>=1.20.0",
            "scipy>=1.7.0",
            "pandas>=1.3.0"
        ]
        test_env.pyproject.save(config)

        from comfygit_cli.env_commands import EnvironmentCommands

        cmd = EnvironmentCommands()
        args = Namespace(
            target_env=None,
            packages=["scipy"],
            group="optional-ml"
        )

        # ACT
        with patch('builtins.print'):
            cmd.py_remove(args)

        # ASSERT
        groups = test_env.pyproject.dependencies.get_groups()
        assert "optional-ml" in groups
        assert "numpy>=1.20.0" in groups["optional-ml"]
        assert "pandas>=1.3.0" in groups["optional-ml"]
        assert "scipy>=1.7.0" not in groups["optional-ml"]

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_py_remove_without_group_flag_uses_main_deps(self, mock_workspace, test_env):
        """Should remove from main dependencies when --group is not specified."""
        # ARRANGE
        mock_workspace.return_value.get_active_environment.return_value = test_env

        config = test_env.pyproject.load()
        config.setdefault("project", {})
        config["project"].setdefault("dependencies", [])
        config["project"]["dependencies"].append("requests>=2.0.0")
        test_env.pyproject.save(config)

        # Also add a dependency group (should not be touched)
        config = test_env.pyproject.load()
        config.setdefault("dependency-groups", {})
        config["dependency-groups"]["optional-test"] = ["pytest>=7.0"]
        test_env.pyproject.save(config)

        from comfygit_cli.env_commands import EnvironmentCommands

        cmd = EnvironmentCommands()
        args = Namespace(
            target_env=None,
            packages=["requests"],
            group=None  # No --group flag
        )

        # ACT
        with patch('builtins.print'):
            cmd.py_remove(args)

        # ASSERT: Main deps should be modified, group untouched
        config = test_env.pyproject.load()
        main_deps = config.get("project", {}).get("dependencies", [])
        assert not any("requests" in dep for dep in main_deps)

        # Group should still exist
        groups = test_env.pyproject.dependencies.get_groups()
        assert "optional-test" in groups
        assert "pytest>=7.0" in groups["optional-test"]

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_py_remove_group_all_packages_deletes_group(self, mock_workspace, test_env):
        """Should delete group when all packages are removed."""
        # ARRANGE
        mock_workspace.return_value.get_active_environment.return_value = test_env

        config = test_env.pyproject.load()
        config.setdefault("dependency-groups", {})
        config["dependency-groups"]["optional-small"] = ["pillow>=9.0.0"]
        test_env.pyproject.save(config)

        from comfygit_cli.env_commands import EnvironmentCommands

        cmd = EnvironmentCommands()
        args = Namespace(
            target_env=None,
            packages=["pillow"],
            group="optional-small"
        )

        # ACT
        with patch('builtins.print'):
            cmd.py_remove(args)

        # ASSERT: Group should be deleted entirely
        groups = test_env.pyproject.dependencies.get_groups()
        assert "optional-small" not in groups
