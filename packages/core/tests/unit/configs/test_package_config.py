"""Tests for PackageConfigManager."""

from pathlib import Path

from comfygit_core.configs.package_config import (
    DEFAULT_EXCLUDE_PACKAGES,
    DEFAULT_PACKAGE_SUBSTITUTIONS,
    PackageConfigManager,
)


class TestPackageConfigManagerDefaults:
    """Test default configuration values."""

    def test_default_substitutions_include_opencv(self):
        """Default substitutions should map non-canonical opencv packages to contrib-headless."""
        assert "opencv-python" in DEFAULT_PACKAGE_SUBSTITUTIONS
        assert "opencv-contrib-python" in DEFAULT_PACKAGE_SUBSTITUTIONS
        assert "opencv-python-headless" in DEFAULT_PACKAGE_SUBSTITUTIONS
        assert DEFAULT_PACKAGE_SUBSTITUTIONS["opencv-python"] == "opencv-contrib-python-headless"
        assert DEFAULT_PACKAGE_SUBSTITUTIONS["opencv-contrib-python"] == "opencv-contrib-python-headless"
        assert DEFAULT_PACKAGE_SUBSTITUTIONS["opencv-python-headless"] == "opencv-contrib-python-headless"

    def test_create_default_config_structure(self, tmp_path: Path):
        """Default config should have substitutions and exclude sections."""
        manager = PackageConfigManager(tmp_path)
        config = manager._create_default_config()

        assert "substitutions" in config
        assert "exclude" in config
        assert list(config["exclude"]["packages"]) == DEFAULT_EXCLUDE_PACKAGES


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
        assert config.get("substitutions", {}).get("opencv-python") == "opencv-contrib-python-headless"

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
        assert result == "opencv-contrib-python-headless"

    def test_substitutes_opencv_contrib_python(self, tmp_path: Path):
        """opencv-contrib-python should map to the canonical contrib-headless package."""
        manager = PackageConfigManager(tmp_path)

        result = manager.apply_substitution("opencv-contrib-python")
        assert result == "opencv-contrib-python-headless"

    def test_substitutes_opencv_python_headless(self, tmp_path: Path):
        """opencv-python-headless should map to canonical contrib-headless package."""
        manager = PackageConfigManager(tmp_path)

        result = manager.apply_substitution("opencv-python-headless")
        assert result == "opencv-contrib-python-headless"

    def test_substitution_with_version_spec(self, tmp_path: Path):
        """Version specifier should be preserved during substitution."""
        manager = PackageConfigManager(tmp_path)

        result = manager.apply_substitution("opencv-python>=4.0")
        assert result == "opencv-contrib-python-headless>=4.0"

    def test_substitution_with_exact_pin(self, tmp_path: Path):
        """Exact version pin should be preserved."""
        manager = PackageConfigManager(tmp_path)

        result = manager.apply_substitution("opencv-python==4.8.0")
        assert result == "opencv-contrib-python-headless==4.8.0"

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
        assert result == "opencv-contrib-python-headless"

    def test_mixed_case_package_substituted(self, tmp_path: Path):
        """Mixed case package name should match."""
        manager = PackageConfigManager(tmp_path)

        result = manager.apply_substitution("OPENCV-python")
        assert result == "opencv-contrib-python-headless"

    def test_mixed_case_with_version(self, tmp_path: Path):
        """Mixed case with version should work."""
        manager = PackageConfigManager(tmp_path)

        result = manager.apply_substitution("OpenCV-Python>=4.0")
        assert result == "opencv-contrib-python-headless>=4.0"


class TestPackageConfigProperties:
    """Test convenience properties."""

    def test_substitutions_property(self, tmp_path: Path):
        """substitutions property should return dict."""
        manager = PackageConfigManager(tmp_path)

        subs = manager.substitutions
        assert isinstance(subs, dict)
        assert "opencv-python" in subs

    def test_exclude_packages_property(self, tmp_path: Path):
        """exclude_packages property should return default excluded packages."""
        manager = PackageConfigManager(tmp_path)

        excludes = manager.exclude_packages
        assert isinstance(excludes, list)
        assert excludes == DEFAULT_EXCLUDE_PACKAGES


class TestPackageConfigCacheInvalidation:
    """Test mtime-based cache invalidation."""

    def test_load_detects_external_file_changes(self, tmp_path: Path):
        """load() should detect when file changed externally via mtime."""
        import os
        import time

        manager = PackageConfigManager(tmp_path)
        manager.save()  # Create initial file

        # Load and cache
        config1 = manager.load()
        assert config1["substitutions"]["opencv-python"] == "opencv-contrib-python-headless"

        # Modify file externally with different mtime
        time.sleep(0.01)  # Ensure mtime differs
        manager.config_path.write_text("""
[substitutions]
custom-pkg = "replacement"
""")
        # Bump mtime deterministically to ensure change is detected
        new_mtime = manager.config_path.stat().st_mtime + 2
        os.utime(manager.config_path, (new_mtime, new_mtime))

        # Load should detect change via mtime
        config2 = manager.load()
        assert "custom-pkg" in config2.get("substitutions", {})
        assert config2["substitutions"]["custom-pkg"] == "replacement"
