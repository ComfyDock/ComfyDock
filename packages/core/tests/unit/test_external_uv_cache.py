"""Tests for external UV cache configuration.

This feature allows specifying an external UV cache path via workspace config,
useful for development testing with multiple workspaces sharing a cache.
"""
import json

from comfygit_core.models.workspace_config import WorkspaceConfig
from comfygit_core.repositories.workspace_config_repository import WorkspaceConfigRepository


class TestWorkspaceConfigExternalUvCache:
    """Test WorkspaceConfig serialization with external_uv_cache field."""

    def test_external_uv_cache_defaults_to_none(self):
        """external_uv_cache should default to None."""
        config = WorkspaceConfig(
            version=1,
            active_environment="",
            created_at="2025-01-01T00:00:00",
            global_model_directory=None,
        )
        assert config.external_uv_cache is None

    def test_from_dict_parses_external_uv_cache(self):
        """from_dict should parse external_uv_cache when present."""
        data = {
            "version": 1,
            "active_environment": "",
            "created_at": "2025-01-01T00:00:00",
            "global_model_directory": None,
            "external_uv_cache": "/shared/uv_cache",
        }
        config = WorkspaceConfig.from_dict(data)
        assert config.external_uv_cache == "/shared/uv_cache"

    def test_from_dict_handles_missing_external_uv_cache(self):
        """from_dict should handle missing external_uv_cache (backwards compat)."""
        data = {
            "version": 1,
            "active_environment": "",
            "created_at": "2025-01-01T00:00:00",
            "global_model_directory": None,
        }
        config = WorkspaceConfig.from_dict(data)
        assert config.external_uv_cache is None

    def test_to_dict_includes_external_uv_cache(self):
        """to_dict should include external_uv_cache when set."""
        config = WorkspaceConfig(
            version=1,
            active_environment="",
            created_at="2025-01-01T00:00:00",
            global_model_directory=None,
            external_uv_cache="/shared/uv_cache",
        )
        data = WorkspaceConfig.to_dict(config)
        assert data["external_uv_cache"] == "/shared/uv_cache"

    def test_to_dict_includes_null_external_uv_cache(self):
        """to_dict should include external_uv_cache as null when not set."""
        config = WorkspaceConfig(
            version=1,
            active_environment="",
            created_at="2025-01-01T00:00:00",
            global_model_directory=None,
        )
        data = WorkspaceConfig.to_dict(config)
        assert "external_uv_cache" in data
        assert data["external_uv_cache"] is None


class TestWorkspaceConfigRepositoryExternalUvCache:
    """Test WorkspaceConfigRepository get/set for external_uv_cache."""

    def test_get_external_uv_cache_returns_none_when_not_set(self, tmp_path):
        """get_external_uv_cache should return None when not configured."""
        config_file = tmp_path / "workspace.json"
        config_file.write_text(json.dumps({
            "version": 1,
            "active_environment": "",
            "created_at": "2025-01-01T00:00:00",
            "global_model_directory": None,
        }))

        repo = WorkspaceConfigRepository(config_file)
        assert repo.get_external_uv_cache() is None

    def test_get_external_uv_cache_returns_path_when_set(self, tmp_path):
        """get_external_uv_cache should return Path when configured."""
        from pathlib import Path

        config_file = tmp_path / "workspace.json"
        config_file.write_text(json.dumps({
            "version": 1,
            "active_environment": "",
            "created_at": "2025-01-01T00:00:00",
            "global_model_directory": None,
            "external_uv_cache": "/shared/uv_cache",
        }))

        repo = WorkspaceConfigRepository(config_file)
        result = repo.get_external_uv_cache()
        assert result == Path("/shared/uv_cache")

    def test_set_external_uv_cache_persists_path(self, tmp_path):
        """set_external_uv_cache should persist the path to config."""

        config_file = tmp_path / "workspace.json"
        config_file.write_text(json.dumps({
            "version": 1,
            "active_environment": "",
            "created_at": "2025-01-01T00:00:00",
            "global_model_directory": None,
        }))

        # Create the cache directory
        cache_dir = tmp_path / "shared_cache"
        cache_dir.mkdir()

        repo = WorkspaceConfigRepository(config_file)
        repo.set_external_uv_cache(cache_dir)

        # Verify persisted
        saved = json.loads(config_file.read_text())
        assert saved["external_uv_cache"] == str(cache_dir)

    def test_set_external_uv_cache_none_clears_setting(self, tmp_path):
        """set_external_uv_cache(None) should clear the setting."""
        config_file = tmp_path / "workspace.json"
        config_file.write_text(json.dumps({
            "version": 1,
            "active_environment": "",
            "created_at": "2025-01-01T00:00:00",
            "global_model_directory": None,
            "external_uv_cache": "/old/path",
        }))

        repo = WorkspaceConfigRepository(config_file)
        repo.set_external_uv_cache(None)

        # Verify cleared
        saved = json.loads(config_file.read_text())
        assert saved["external_uv_cache"] is None


class TestUvFactoryExternalCache:
    """Test UV factory uses external cache when configured."""

    def test_get_uv_cache_paths_uses_workspace_default(self, tmp_path):
        """Without external cache, should use workspace-local uv_cache/."""
        from comfygit_core.factories.uv_factory import get_uv_cache_paths

        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir()

        uv_cache, uv_python = get_uv_cache_paths(workspace_path)

        assert uv_cache == workspace_path / "uv_cache"
        assert uv_python == workspace_path / "uv" / "python"

    def test_get_uv_cache_paths_uses_external_when_provided(self, tmp_path):
        """With external cache path, should use it instead of workspace-local."""
        from comfygit_core.factories.uv_factory import get_uv_cache_paths

        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir()

        external_cache = tmp_path / "shared_cache"
        external_cache.mkdir()

        uv_cache, uv_python = get_uv_cache_paths(
            workspace_path,
            external_uv_cache=external_cache,
        )

        assert uv_cache == external_cache
        assert uv_python == external_cache / "python"
