"""Tests for PackageConfigManager."""

import pytest
from pathlib import Path

from comfygit_core.configs.package_config import (
    PackageConfigManager,
    DEFAULT_PACKAGE_SUBSTITUTIONS,
    DEFAULT_EXCLUDE_PACKAGES,
)


class TestPackageConfigManagerDefaults:
    """Test default configuration values."""

    def test_default_substitutions_include_opencv(self):
        """Default substitutions should include opencv-python -> opencv-python-headless."""
        assert "opencv-python" in DEFAULT_PACKAGE_SUBSTITUTIONS
        assert DEFAULT_PACKAGE_SUBSTITUTIONS["opencv-python"] == "opencv-python-headless"

    def test_default_exclusions_include_opencv(self):
        """Default exclusions should include opencv-python."""
        assert "opencv-python" in DEFAULT_EXCLUDE_PACKAGES

    def test_create_default_config_structure(self, tmp_path: Path):
        """Default config should have substitutions and exclude sections."""
        manager = PackageConfigManager(tmp_path)
        config = manager._create_default_config()

        assert "substitutions" in config
        assert "exclude" in config
        assert "packages" in config["exclude"]


class TestPackageConfigLoadSave:
    """Test load/save functionality."""

    def test_save_creates_file(self, tmp_path: Path):
        """Saving should create the config file."""
        manager = PackageConfigManager(tmp_path)
        manager.save()

        assert manager.config_path.exists()

    def test_load_returns_defaults_when_no_file(self, tmp_path: Path):
        """Load should return defaults when no file exists."""
        manager = PackageConfigManager(tmp_path)
        config = manager.load()

        assert "substitutions" in config
        assert "exclude" in config

    def test_load_reads_saved_config(self, tmp_path: Path):
        """Load should read previously saved config."""
        manager = PackageConfigManager(tmp_path)

        # Save with custom value
        manager.save()

        # Create new manager and load
        manager2 = PackageConfigManager(tmp_path)
        config = manager2.load()

        # Should have the default substitutions
        assert config.get("substitutions", {}).get("opencv-python") == "opencv-python-headless"

    def test_ensure_exists_creates_file(self, tmp_path: Path):
        """ensure_exists should create config file with defaults."""
        manager = PackageConfigManager(tmp_path)
        assert not manager.config_path.exists()

        manager.ensure_exists()

        assert manager.config_path.exists()

    def test_ensure_exists_does_not_overwrite(self, tmp_path: Path):
        """ensure_exists should not overwrite existing file."""
        # Create file with custom content
        config_path = tmp_path / "package_config.toml"
        config_path.write_text('[substitutions]\ncustom = "value"\n')

        manager = PackageConfigManager(tmp_path)
        manager.ensure_exists()

        # Should preserve custom content
        config = manager.load()
        assert config.get("substitutions", {}).get("custom") == "value"


class TestApplySubstitutionWithVersion:
    """Test apply_substitution with version specifiers."""

    def test_simple_substitution(self, tmp_path: Path):
        """Simple package name should be substituted."""
        manager = PackageConfigManager(tmp_path)

        result = manager.apply_substitution("opencv-python")
        assert result == "opencv-python-headless"

    def test_substitution_with_version_spec(self, tmp_path: Path):
        """Version specifier should be preserved during substitution."""
        manager = PackageConfigManager(tmp_path)

        result = manager.apply_substitution("opencv-python>=4.0")
        assert result == "opencv-python-headless>=4.0"

    def test_substitution_with_exact_pin(self, tmp_path: Path):
        """Exact version pin should be preserved."""
        manager = PackageConfigManager(tmp_path)

        result = manager.apply_substitution("opencv-python==4.8.0")
        assert result == "opencv-python-headless==4.8.0"

    def test_no_substitution_for_unknown_package(self, tmp_path: Path):
        """Unknown packages should be returned unchanged."""
        manager = PackageConfigManager(tmp_path)

        result = manager.apply_substitution("numpy>=1.21")
        assert result == "numpy>=1.21"


class TestApplySubstitutionCaseInsensitive:
    """Test case-insensitive package matching."""

    def test_uppercase_package_substituted(self, tmp_path: Path):
        """Uppercase package name should match."""
        manager = PackageConfigManager(tmp_path)

        result = manager.apply_substitution("OpenCV-Python")
        assert result == "opencv-python-headless"

    def test_mixed_case_package_substituted(self, tmp_path: Path):
        """Mixed case package name should match."""
        manager = PackageConfigManager(tmp_path)

        result = manager.apply_substitution("OPENCV-python")
        assert result == "opencv-python-headless"

    def test_mixed_case_with_version(self, tmp_path: Path):
        """Mixed case with version should work."""
        manager = PackageConfigManager(tmp_path)

        result = manager.apply_substitution("OpenCV-Python>=4.0")
        assert result == "opencv-python-headless>=4.0"


class TestPackageConfigProperties:
    """Test convenience properties."""

    def test_substitutions_property(self, tmp_path: Path):
        """substitutions property should return dict."""
        manager = PackageConfigManager(tmp_path)

        subs = manager.substitutions
        assert isinstance(subs, dict)
        assert "opencv-python" in subs

    def test_exclude_packages_property(self, tmp_path: Path):
        """exclude_packages property should return list."""
        manager = PackageConfigManager(tmp_path)

        excludes = manager.exclude_packages
        assert isinstance(excludes, list)
        assert "opencv-python" in excludes
