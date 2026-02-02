"""Integration test for ComfyUI version reproducibility on import.

BUG: export_import_manager.py:228 always passes None to clone_comfyui(),
     ignoring the comfyui_version from manifest and pyproject.toml.

This test verifies that when importing an environment, the EXACT ComfyUI
version specified in the export is cloned, not the latest HEAD.
"""

import tarfile
from unittest.mock import patch


class TestImportComfyUIVersionBug:
    """Test that import reproduces exact ComfyUI version."""

    def test_import_uses_comfyui_version_from_pyproject(self, test_workspace, mock_comfyui_clone, mock_github_api):
        """Test that import clones specific comfyui_version from pyproject.toml."""
        # ARRANGE - Create a fake export with v0.3.15 in pyproject.toml
        export_tarball = test_workspace.paths.root / "test_export.tar.gz"

        # Create export structure
        export_content = test_workspace.paths.root / "export_content"
        export_content.mkdir()

        # Create pyproject.toml with version metadata
        pyproject_content = """
[project]
name = "comfygit-env-test"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "v0.3.15"
python_version = "3.12"
nodes = {}
"""
        (export_content / "pyproject.toml").write_text(pyproject_content)

        # Create tarball
        with tarfile.open(export_tarball, "w:gz") as tar:
            for item in export_content.iterdir():
                tar.add(item, arcname=item.name)

        # Track what version is requested (override fixture's mock)
        cloned_version = None

        def track_clone_version(target_path, version):
            nonlocal cloned_version
            cloned_version = version
            return mock_comfyui_clone(target_path, version)

        # ACT - Import the environment (fixture handles subprocess mocking)
        with patch('comfygit_core.utils.comfyui_ops.clone_comfyui', side_effect=track_clone_version):
            test_workspace.import_environment(
                tarball_path=export_tarball,
                name="imported-env"
            )

        # ASSERT - Should have cloned v0.3.15, not None
        assert cloned_version is not None, \
            "clone_comfyui should be called with version from pyproject.toml"
        assert cloned_version == "v0.3.15", \
            f"Expected version 'v0.3.15' but got '{cloned_version}'"

    def test_import_uses_version_not_commit_sha(self, test_workspace, mock_comfyui_clone, mock_github_api):
        """SHOULD use comfyui_version (tag/branch), NOT commit_sha (can't shallow clone)."""
        # ARRANGE
        export_tarball = test_workspace.paths.root / "test_export.tar.gz"
        export_content = test_workspace.paths.root / "export_content"
        export_content.mkdir()

        # Create pyproject with both version and commit_sha
        pyproject_content = """
[project]
name = "comfygit-env-test"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "v0.3.15"
comfyui_commit_sha = "abc123def456"
python_version = "3.12"
nodes = {}
"""
        (export_content / "pyproject.toml").write_text(pyproject_content)

        # Create tarball
        with tarfile.open(export_tarball, "w:gz") as tar:
            for item in export_content.iterdir():
                tar.add(item, arcname=item.name)

        # Track what version is requested (override fixture's mock)
        cloned_version = None

        def track_clone_version(target_path, version):
            nonlocal cloned_version
            cloned_version = version
            return mock_comfyui_clone(target_path, version)

        # ACT (fixture handles subprocess mocking)
        with patch('comfygit_core.utils.comfyui_ops.clone_comfyui', side_effect=track_clone_version):
            test_workspace.import_environment(
                tarball_path=export_tarball,
                name="imported-env2"
            )

        # ASSERT - Should use version tag (can shallow clone), not commit SHA (can't shallow clone)
        assert cloned_version == "v0.3.15", \
            f"Expected version tag 'v0.3.15' but got '{cloned_version}'. Commit SHA can't be shallow cloned!"
