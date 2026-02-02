"""Unit tests for Environment Python dependency management."""
from unittest.mock import MagicMock, patch

import pytest
from comfygit_core.core.environment import Environment
from comfygit_core.models.exceptions import UVCommandError


@pytest.fixture
def mock_env():
    """Create a mock Environment with mocked UV manager."""
    with patch('comfygit_core.core.environment.WorkflowManager'), \
         patch('comfygit_core.core.environment.NodeManager'), \
         patch('comfygit_core.core.environment.GitManager'), \
         patch('comfygit_core.core.environment.PyprojectManager'), \
         patch('comfygit_core.core.environment.UVProjectManager'):

        # Create environment instance
        env = Environment.__new__(Environment)
        env.uv_manager = MagicMock()
        env.pyproject = MagicMock()

        # Mock package_config to return packages unchanged (no substitutions)
        mock_pkg_config = MagicMock()
        mock_pkg_config.apply_substitution.side_effect = lambda x: x  # Return unchanged
        env.package_config = mock_pkg_config

        yield env


class TestAddDependencies:
    """Test Environment.add_dependencies() method."""

    def test_add_single_dependency(self, mock_env):
        """Should call uv_manager.add_dependency with single package."""
        mock_env.uv_manager.add_dependency.return_value = "Added: requests"

        result = mock_env.add_dependencies(["requests"])

        mock_env.uv_manager.add_dependency.assert_called_once_with(
            packages=["requests"],
            requirements_file=None,
            upgrade=False,
            group=None,
            dev=False,
            editable=False,
            bounds=None
        )
        assert result["output"] == "Added: requests"
        assert result["substitutions"] == {}

    def test_add_multiple_dependencies(self, mock_env):
        """Should call uv_manager.add_dependency with multiple packages."""
        packages = ["requests>=2.0.0", "pillow", "tqdm"]
        mock_env.uv_manager.add_dependency.return_value = "Added: 3 packages"

        result = mock_env.add_dependencies(packages)

        mock_env.uv_manager.add_dependency.assert_called_once_with(
            packages=packages,
            requirements_file=None,
            upgrade=False,
            group=None,
            dev=False,
            editable=False,
            bounds=None
        )
        assert result["output"] == "Added: 3 packages"

    def test_add_dependencies_with_upgrade_flag(self, mock_env):
        """Should pass upgrade=True when upgrade flag is set."""
        mock_env.uv_manager.add_dependency.return_value = "Upgraded: requests"

        result = mock_env.add_dependencies(["requests"], upgrade=True)

        mock_env.uv_manager.add_dependency.assert_called_once_with(
            packages=["requests"],
            requirements_file=None,
            upgrade=True,
            group=None,
            dev=False,
            editable=False,
            bounds=None
        )
        assert result["output"] == "Upgraded: requests"

    def test_add_dependencies_handles_uv_error(self, mock_env):
        """Should propagate UVCommandError from uv_manager."""
        mock_env.uv_manager.add_dependency.side_effect = UVCommandError(
            "Package not found",
            command=["uv", "add", "nonexistent"]
        )

        with pytest.raises(UVCommandError) as exc_info:
            mock_env.add_dependencies(["nonexistent"])

        assert "Package not found" in str(exc_info.value)


class TestRemoveDependencies:
    """Test Environment.remove_dependencies() method."""

    def test_remove_single_dependency(self, mock_env):
        """Should call uv_manager.remove_dependency with single package."""
        mock_env.uv_manager.remove_dependency.return_value = {
            'removed': ['requests'],
            'skipped': []
        }

        result = mock_env.remove_dependencies(["requests"])

        mock_env.uv_manager.remove_dependency.assert_called_once_with(
            packages=["requests"]
        )
        assert result == {'removed': ['requests'], 'skipped': []}

    def test_remove_multiple_dependencies(self, mock_env):
        """Should call uv_manager.remove_dependency with multiple packages."""
        packages = ["requests", "pillow", "tqdm"]
        mock_env.uv_manager.remove_dependency.return_value = {
            'removed': packages,
            'skipped': []
        }

        result = mock_env.remove_dependencies(packages)

        mock_env.uv_manager.remove_dependency.assert_called_once_with(
            packages=packages
        )
        assert result == {'removed': packages, 'skipped': []}

    def test_remove_dependencies_handles_uv_error(self, mock_env):
        """Should propagate UVCommandError from uv_manager."""
        mock_env.uv_manager.remove_dependency.side_effect = UVCommandError(
            "Package not installed",
            command=["uv", "remove", "nonexistent"]
        )

        with pytest.raises(UVCommandError) as exc_info:
            mock_env.remove_dependencies(["nonexistent"])

        assert "Package not installed" in str(exc_info.value)


class TestListDependencies:
    """Test Environment.list_dependencies() method."""

    def test_list_dependencies_returns_project_deps(self, mock_env):
        """Should return dependencies from [project.dependencies]."""
        mock_config = {
            'project': {
                'dependencies': [
                    'requests>=2.0.0',
                    'pillow',
                    'tqdm>=4.0.0'
                ]
            }
        }
        mock_env.pyproject.load.return_value = mock_config

        deps = mock_env.list_dependencies()

        assert deps == {
            'dependencies': ['requests>=2.0.0', 'pillow', 'tqdm>=4.0.0']
        }

    def test_list_dependencies_returns_empty_when_no_deps(self, mock_env):
        """Should return empty dict when no dependencies exist."""
        mock_config = {'project': {}}
        mock_env.pyproject.load.return_value = mock_config

        deps = mock_env.list_dependencies()

        assert deps == {'dependencies': []}

    def test_list_dependencies_returns_empty_when_no_project_section(self, mock_env):
        """Should return empty dict when project section doesn't exist."""
        mock_config = {}
        mock_env.pyproject.load.return_value = mock_config

        deps = mock_env.list_dependencies()

        assert deps == {'dependencies': []}
