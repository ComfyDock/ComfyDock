"""Tests for package substitution in add_dependencies."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestAddDependenciesSubstitution:
    """Test that add_dependencies applies package substitutions."""

    @pytest.fixture
    def mock_environment(self):
        """Create a mock environment with package_config."""
        from comfygit_core.configs.package_config import PackageConfigManager

        env = MagicMock()

        # Create a real PackageConfigManager with temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            cec_path = Path(tmpdir)
            pkg_config = PackageConfigManager(cec_path)
            env.package_config = pkg_config
            env.uv_manager = MagicMock()
            env.uv_manager.add_dependency.return_value = "Added packages"

            # We need to import and use the real method
            from comfygit_core.core.environment import Environment

            # Bind the real methods to our mock
            env.add_dependencies = lambda **kwargs: Environment.add_dependencies(env, **kwargs)
            env._read_requirements_file = lambda f: Environment._read_requirements_file(env, f)

            yield env

    def test_substitutes_opencv_python(self, mock_environment):
        """Should substitute opencv-python with opencv-python-headless."""
        result = mock_environment.add_dependencies(packages=["opencv-python"])

        # Check substitution was recorded
        assert "substitutions" in result
        assert "opencv-python" in result["substitutions"]
        assert result["substitutions"]["opencv-python"] == "opencv-python-headless"

        # Check UV was called with substituted package
        mock_environment.uv_manager.add_dependency.assert_called_once()
        call_kwargs = mock_environment.uv_manager.add_dependency.call_args.kwargs
        assert call_kwargs["packages"] == ["opencv-python-headless"]

    def test_preserves_version_specifier(self, mock_environment):
        """Should preserve version specifiers during substitution."""
        result = mock_environment.add_dependencies(packages=["opencv-python>=4.5.0,<5.0"])

        assert result["substitutions"]["opencv-python>=4.5.0,<5.0"] == "opencv-python-headless>=4.5.0,<5.0"

        call_kwargs = mock_environment.uv_manager.add_dependency.call_args.kwargs
        assert call_kwargs["packages"] == ["opencv-python-headless>=4.5.0,<5.0"]

    def test_no_substitution_for_regular_packages(self, mock_environment):
        """Should not substitute packages not in config."""
        result = mock_environment.add_dependencies(packages=["requests", "pillow"])

        assert result["substitutions"] == {}

        call_kwargs = mock_environment.uv_manager.add_dependency.call_args.kwargs
        assert call_kwargs["packages"] == ["requests", "pillow"]

    def test_mixed_packages_only_substitutes_matching(self, mock_environment):
        """Should only substitute matching packages in a mixed list."""
        result = mock_environment.add_dependencies(
            packages=["requests", "opencv-python", "pillow"]
        )

        assert len(result["substitutions"]) == 1
        assert "opencv-python" in result["substitutions"]

        call_kwargs = mock_environment.uv_manager.add_dependency.call_args.kwargs
        assert call_kwargs["packages"] == ["requests", "opencv-python-headless", "pillow"]

    def test_substitutes_from_requirements_file(self, mock_environment):
        """Should substitute packages when reading from requirements file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("requests\n")
            f.write("opencv-python>=4.0\n")
            f.write("# this is a comment\n")
            f.write("pillow\n")
            f.flush()

            result = mock_environment.add_dependencies(
                requirements_file=Path(f.name)
            )

        assert "opencv-python>=4.0" in result["substitutions"]

        call_kwargs = mock_environment.uv_manager.add_dependency.call_args.kwargs
        assert call_kwargs["packages"] == ["requests", "opencv-python-headless>=4.0", "pillow"]
        assert call_kwargs["requirements_file"] is None  # We parse it ourselves now

    def test_case_insensitive_substitution(self, mock_environment):
        """Should handle case-insensitive package names."""
        result = mock_environment.add_dependencies(packages=["OpenCV-Python"])

        assert "OpenCV-Python" in result["substitutions"]

        call_kwargs = mock_environment.uv_manager.add_dependency.call_args.kwargs
        assert call_kwargs["packages"] == ["opencv-python-headless"]
