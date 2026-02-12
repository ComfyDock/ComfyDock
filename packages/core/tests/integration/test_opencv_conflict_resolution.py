"""Integration test for opencv package conflict resolution.

This test verifies that the package substitution system correctly handles
the opencv package family conflict.

Bug scenario (before fix):
1. Install node A with opencv-contrib-python-headless
2. Install node B with opencv-python (overwrites cv2)
3. Uninstall node B
4. cv2 is now missing (corrupted state)

Expected behavior (after fix):
- non-canonical opencv families are substituted with opencv-contrib-python-headless
- non-canonical opencv families are in exclude-dependencies, never installed
- cv2 always works regardless of install/uninstall order
"""
import pytest


@pytest.fixture
def test_environment(tmp_path, test_workspace, mock_comfyui_clone, mock_github_api):
    """Create a test environment."""
    import json

    # Create empty node mappings to avoid network fetch
    custom_nodes_cache = test_workspace.paths.cache / "custom_nodes"
    custom_nodes_cache.mkdir(parents=True, exist_ok=True)
    node_mappings = custom_nodes_cache / "node_mappings.json"
    with open(node_mappings, 'w') as f:
        json.dump({"mappings": {}, "packages": {}, "stats": {}}, f)

    # Set models directory
    models_dir = test_workspace.path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    test_workspace.set_models_directory(models_dir)

    # Create environment
    env = test_workspace.create_environment(
        name="opencv-test",
        python_version="3.12",
        comfyui_version="master"
    )
    return env


class TestOpencvConflictResolution:
    """Test that opencv package conflicts are properly resolved."""

    def test_package_config_file_exists(self, test_environment):
        """Verify package_config.toml was created."""
        config_path = test_environment.cec_path / "package_config.toml"
        assert config_path.exists(), "package_config.toml should exist"

    def test_opencv_substitution_in_requirements(self, test_environment):
        """Verify opencv-python gets substituted to contrib-headless in requirements."""
        # Create mock requirements with opencv-python
        mock_reqs = ["opencv-python>=4.5.0", "numpy"]

        # Apply substitutions
        pkg_config = test_environment.package_config
        transformed = [pkg_config.apply_substitution(r) for r in mock_reqs]

        assert "opencv-contrib-python-headless>=4.5.0" in transformed, "Should substitute opencv-python with contrib-headless"
        assert "opencv-python>=4.5.0" not in transformed, "Original opencv-python should not be in result"
        assert "numpy" in transformed, "Unchanged packages should remain"

    def test_all_non_canonical_opencv_variants_substitute(self, test_environment):
        """Verify all non-canonical opencv packages map to contrib-headless."""
        pkg_config = test_environment.package_config

        test_cases = [
            "opencv-python",
            "opencv-contrib-python",
            "opencv-python-headless",
        ]

        transformed = [pkg_config.apply_substitution(pkg) for pkg in test_cases]
        assert transformed == ["opencv-contrib-python-headless"] * 3

    def test_opencv_substitution_without_version(self, test_environment):
        """Verify opencv-python substitution works without version specifier."""
        pkg_config = test_environment.package_config
        result = pkg_config.apply_substitution("opencv-python")

        assert result == "opencv-contrib-python-headless", "Should substitute to contrib-headless without version"

    def test_opencv_substitution_preserves_complex_version(self, test_environment):
        """Verify version specifiers are preserved during substitution."""
        pkg_config = test_environment.package_config

        test_cases = [
            ("opencv-python==4.8.0.76", "opencv-contrib-python-headless==4.8.0.76"),
            ("opencv-python>=4.5.0,<5.0.0", "opencv-contrib-python-headless>=4.5.0,<5.0.0"),
            ("opencv-python~=4.8.0", "opencv-contrib-python-headless~=4.8.0"),
        ]

        for original, expected in test_cases:
            result = pkg_config.apply_substitution(original)
            assert result == expected, f"Failed for {original}"


class TestPackageSubstitutionConfig:
    """Test package substitution configuration."""

    def test_default_substitutions_include_opencv(self, test_environment):
        """Verify default substitutions include all non-canonical opencv mappings."""
        pkg_config = test_environment.package_config
        subs = pkg_config.substitutions

        assert "opencv-python" in subs, "Default substitutions should include opencv-python"
        assert "opencv-contrib-python" in subs, "Default substitutions should include opencv-contrib-python"
        assert "opencv-python-headless" in subs, "Default substitutions should include opencv-python-headless"
        assert subs["opencv-python"] == "opencv-contrib-python-headless", "Should map to contrib-headless"
        assert subs["opencv-contrib-python"] == "opencv-contrib-python-headless", "Should map to contrib-headless"
        assert subs["opencv-python-headless"] == "opencv-contrib-python-headless", "Should map to contrib-headless"

    def test_custom_substitution_can_be_added(self, test_environment):
        """Verify users can add custom substitutions."""
        pkg_config = test_environment.package_config
        config = pkg_config.load()

        # Add custom substitution
        config["substitutions"]["pillow"] = "pillow-simd"
        pkg_config.save(config)

        # Verify it persists by reloading
        pkg_config._config = None  # Clear cache
        subs = pkg_config.substitutions

        assert subs["pillow"] == "pillow-simd", "Custom substitution should persist"
        assert subs["opencv-python"] == "opencv-contrib-python-headless", "Default substitutions should remain"

    def test_exclude_packages_list_has_non_canonical_opencv_defaults(self, test_environment):
        """Verify excluded package defaults block non-canonical opencv families."""
        pkg_config = test_environment.package_config
        excludes = pkg_config.exclude_packages

        assert isinstance(excludes, list), "exclude_packages should return a list"
        assert excludes == [
            "opencv-python",
            "opencv-contrib-python",
            "opencv-python-headless",
        ]

    def test_package_config_structure(self, test_environment):
        """Verify package_config.toml has expected structure."""
        import tomlkit

        config_path = test_environment.cec_path / "package_config.toml"
        with open(config_path, encoding="utf-8") as f:
            config = tomlkit.load(f)

        # Check substitutions section exists
        assert "substitutions" in config, "Should have substitutions section"
        assert "exclude" in config, "exclude section should exist by default"
        assert list(config["exclude"]["packages"]) == [
            "opencv-python",
            "opencv-contrib-python",
            "opencv-python-headless",
        ]

    def test_case_insensitive_substitution(self, test_environment):
        """Verify substitution works case-insensitively."""
        pkg_config = test_environment.package_config

        # Try different casing
        test_cases = [
            "opencv-python",
            "OpenCV-Python",
            "OPENCV-PYTHON",
        ]

        for pkg in test_cases:
            result = pkg_config.apply_substitution(pkg)
            # Result should always use the replacement name (which is lowercase)
            assert "opencv-contrib-python-headless" in result.lower(), f"Should substitute {pkg} case-insensitively"
