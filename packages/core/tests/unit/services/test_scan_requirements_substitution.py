"""Tests for package substitution in scan_requirements.

TDD tests to verify that:
1. scan_requirements() applies package substitutions when PackageConfigManager is provided
2. scan_requirements() works unchanged when no config is provided
3. Package substitutions are logged for debugging
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from comfygit_core.configs.package_config import PackageConfigManager
from comfygit_core.services.node_lookup_service import NodeLookupService


class TestScanRequirementsSubstitution:
    """Test package substitution in scan_requirements."""

    @pytest.fixture
    def cache_dir(self):
        """Create a temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def node_dir(self):
        """Create a temporary node directory with requirements.txt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node_path = Path(tmpdir) / "test-node"
            node_path.mkdir()
            # Create requirements.txt with opencv-python (to be substituted)
            (node_path / "requirements.txt").write_text(
                "opencv-python>=4.0\n"
                "numpy>=1.20\n"
                "pillow\n"
            )
            yield node_path

    @pytest.fixture
    def package_config(self):
        """Create a PackageConfigManager with default substitutions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cec_path = Path(tmpdir)
            config = PackageConfigManager(cec_path)
            # ensure_exists creates the config with defaults
            config.ensure_exists()
            yield config

    def test_scan_requirements_applies_substitution_with_config(
        self, cache_dir, node_dir, package_config
    ):
        """SHOULD substitute opencv-python with opencv-contrib-python-headless when config provided."""
        # ARRANGE
        service = NodeLookupService(cache_path=cache_dir)

        # ACT
        requirements = service.scan_requirements(node_dir, package_config=package_config)

        # ASSERT
        assert "opencv-contrib-python-headless>=4.0" in requirements
        assert "opencv-python>=4.0" not in requirements
        # Other packages should be unchanged
        assert "numpy>=1.20" in requirements
        assert "pillow" in requirements

    def test_scan_requirements_no_config_unchanged(self, cache_dir, node_dir):
        """SHOULD return original requirements when no config provided."""
        # ARRANGE
        service = NodeLookupService(cache_path=cache_dir)

        # ACT
        requirements = service.scan_requirements(node_dir)

        # ASSERT
        # Without config, opencv-python should remain unchanged
        assert "opencv-python>=4.0" in requirements
        assert "opencv-contrib-python-headless>=4.0" not in requirements
        assert "numpy>=1.20" in requirements
        assert "pillow" in requirements

    def test_scan_requirements_substitution_logged(self, cache_dir, node_dir, package_config):
        """SHOULD log substitutions for debugging."""
        # ARRANGE
        service = NodeLookupService(cache_path=cache_dir)

        # ACT
        with patch("comfygit_core.configs.package_config.logger") as mock_logger:
            service.scan_requirements(node_dir, package_config=package_config)

            # ASSERT - apply_substitution logs the substitution
            # The log happens in apply_substitution, not scan_requirements
            mock_logger.debug.assert_called()

    def test_scan_requirements_empty_node_returns_empty_list(self, cache_dir, package_config):
        """SHOULD return empty list for nodes with no requirements."""
        # ARRANGE
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_node = Path(tmpdir) / "empty-node"
            empty_node.mkdir()

            service = NodeLookupService(cache_path=cache_dir)

            # ACT
            requirements = service.scan_requirements(empty_node, package_config=package_config)

            # ASSERT
            assert requirements == []

    def test_scan_requirements_preserves_version_specifiers(
        self, cache_dir, package_config
    ):
        """SHOULD preserve version specifiers when applying substitution."""
        # ARRANGE
        with tempfile.TemporaryDirectory() as tmpdir:
            node_path = Path(tmpdir) / "version-test-node"
            node_path.mkdir()
            # Various version specifier formats
            (node_path / "requirements.txt").write_text(
                "opencv-python>=4.5.3\n"
                "opencv-contrib-python==4.8.0\n"
            )

            service = NodeLookupService(cache_path=cache_dir)

            # ACT
            requirements = service.scan_requirements(node_path, package_config=package_config)

            # ASSERT
            assert "opencv-contrib-python-headless>=4.5.3" in requirements
            assert "opencv-contrib-python-headless==4.8.0" in requirements

    def test_scan_requirements_skips_false_environment_markers(self, cache_dir):
        """SHOULD skip requirements whose environment marker does not match."""
        # ARRANGE
        with tempfile.TemporaryDirectory() as tmpdir:
            node_path = Path(tmpdir) / "marker-test-node"
            node_path.mkdir()
            (node_path / "requirements.txt").write_text(
                "numpy\n"
                "pynvml; python_version >= '3'\n"
                "jetson-stats; python_version < '0'\n"
            )

            service = NodeLookupService(cache_path=cache_dir)

            # ACT
            requirements = service.scan_requirements(node_path)

            # ASSERT
            assert "numpy" in requirements
            assert "pynvml; python_version >= '3'" in requirements
            assert "jetson-stats; python_version < '0'" not in requirements

    def test_scan_requirements_keeps_invalid_requirement_lines(self, cache_dir):
        """SHOULD keep non-standard lines so downstream tooling can handle them."""
        # ARRANGE
        with tempfile.TemporaryDirectory() as tmpdir:
            node_path = Path(tmpdir) / "nonstandard-test-node"
            node_path.mkdir()
            (node_path / "requirements.txt").write_text(
                "--extra-index-url https://example.invalid/simple\n"
                "numpy\n"
            )

            service = NodeLookupService(cache_path=cache_dir)

            # ACT
            requirements = service.scan_requirements(node_path)

            # ASSERT
            assert "--extra-index-url https://example.invalid/simple" in requirements
            assert "numpy" in requirements
