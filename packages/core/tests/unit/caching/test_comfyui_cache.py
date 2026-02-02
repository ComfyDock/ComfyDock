"""Unit tests for ComfyUICacheManager.

TDD tests to verify:
1. ComfyUI versions can be cached and retrieved
2. Cache keys are generated correctly for releases, commits, and branches
3. Metadata is stored with version type and commit SHA
"""

import json
import tempfile
from pathlib import Path

from comfygit_core.caching.comfyui_cache import ComfyUICacheManager, ComfyUISpec


class TestComfyUICacheManager:
    """Test ComfyUI cache manager."""

    def test_initialization_creates_comfyui_cache_structure(self):
        """SHOULD create comfyui/store directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ComfyUICacheManager(cache_base_path=Path(tmpdir))

            assert cache.cache_dir == Path(tmpdir) / "comfyui"
            assert cache.store_dir == Path(tmpdir) / "comfyui" / "store"
            assert cache.cache_dir.exists()
            assert cache.store_dir.exists()

    def test_generate_cache_key_for_release(self):
        """SHOULD generate release_v0.3.20 for release version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ComfyUICacheManager(cache_base_path=Path(tmpdir))

            spec = ComfyUISpec(
                version="v0.3.20",
                version_type="release",
                commit_sha="abc123"
            )

            cache_key = cache.generate_cache_key(spec)
            assert cache_key == "release_v0.3.20"

    def test_generate_cache_key_for_commit(self):
        """SHOULD generate commit_abc123 for commit hash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ComfyUICacheManager(cache_base_path=Path(tmpdir))

            spec = ComfyUISpec(
                version="abc123",
                version_type="commit",
                commit_sha="abc123"
            )

            cache_key = cache.generate_cache_key(spec)
            assert cache_key == "commit_abc123"

    def test_generate_cache_key_for_branch(self):
        """SHOULD generate branch_main for branch ref."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ComfyUICacheManager(cache_base_path=Path(tmpdir))

            spec = ComfyUISpec(
                version="main",
                version_type="branch",
                commit_sha="def456"
            )

            cache_key = cache.generate_cache_key(spec)
            # Branches should use commit SHA for cache key
            assert cache_key == "commit_def456"

    def test_generate_cache_key_from_string(self):
        """SHOULD handle simple version string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ComfyUICacheManager(cache_base_path=Path(tmpdir))

            cache_key = cache.generate_cache_key("v0.3.20")
            assert cache_key == "version_v0.3.20"

    def test_cache_comfyui_stores_version_metadata(self):
        """SHOULD store version, type, and commit SHA in metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ComfyUICacheManager(cache_base_path=Path(tmpdir))

            # Create fake ComfyUI directory (use different name to avoid case-insensitive FS collision)
            comfyui_dir = Path(tmpdir) / "test_comfyui"
            comfyui_dir.mkdir()
            (comfyui_dir / "main.py").write_text("# ComfyUI")

            spec = ComfyUISpec(
                version="v0.3.20",
                version_type="release",
                commit_sha="abc123def456"
            )

            cache.cache_comfyui(spec, comfyui_dir)

            # Check metadata
            metadata_file = cache.store_dir / "release_v0.3.20" / "metadata.json"
            assert metadata_file.exists()

            metadata = json.loads(metadata_file.read_text())
            assert metadata["version"] == "v0.3.20"
            assert metadata["version_type"] == "release"
            assert metadata["commit_sha"] == "abc123def456"

    def test_cache_comfyui_includes_git_directory(self):
        """SHOULD cache entire ComfyUI directory including .git."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ComfyUICacheManager(cache_base_path=Path(tmpdir))

            # Create fake ComfyUI with .git (use different name to avoid case-insensitive FS collision)
            comfyui_dir = Path(tmpdir) / "test_comfyui"
            comfyui_dir.mkdir()
            (comfyui_dir / "main.py").write_text("# ComfyUI")
            git_dir = comfyui_dir / ".git"
            git_dir.mkdir()
            (git_dir / "config").write_text("[core]")

            spec = ComfyUISpec(
                version="v0.3.20",
                version_type="release",
                commit_sha="abc123"
            )

            cached_path = cache.cache_comfyui(spec, comfyui_dir)

            assert (cached_path / "main.py").exists()
            assert (cached_path / ".git").exists()
            assert (cached_path / ".git" / "config").exists()

    def test_get_cached_comfyui_returns_none_when_missing(self):
        """SHOULD return None when version not cached."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ComfyUICacheManager(cache_base_path=Path(tmpdir))

            spec = ComfyUISpec(
                version="v0.3.20",
                version_type="release"
            )

            result = cache.get_cached_comfyui(spec)
            assert result is None

    def test_get_cached_comfyui_returns_path_when_exists(self):
        """SHOULD return content path when version is cached."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ComfyUICacheManager(cache_base_path=Path(tmpdir))

            # Cache a version (use different name to avoid case-insensitive FS collision)
            comfyui_dir = Path(tmpdir) / "test_comfyui"
            comfyui_dir.mkdir()
            (comfyui_dir / "main.py").write_text("# ComfyUI")

            spec = ComfyUISpec(
                version="v0.3.20",
                version_type="release",
                commit_sha="abc123"
            )

            cache.cache_comfyui(spec, comfyui_dir)

            # Retrieve it
            cached_path = cache.get_cached_comfyui(spec)

            assert cached_path is not None
            assert cached_path.exists()
            assert (cached_path / "main.py").exists()

    def test_get_cached_comfyui_with_string_version(self):
        """SHOULD support simple string lookup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ComfyUICacheManager(cache_base_path=Path(tmpdir))

            # Cache with spec (use different name to avoid case-insensitive FS collision)
            comfyui_dir = Path(tmpdir) / "test_comfyui"
            comfyui_dir.mkdir()
            (comfyui_dir / "main.py").write_text("# ComfyUI")

            # First cache using a simple string approach
            cache.cache_content(
                cache_key="version_v0.3.20",
                source_path=comfyui_dir
            )

            # Retrieve with string
            cached_path = cache.get_cached_comfyui("v0.3.20")

            assert cached_path is not None
            assert cached_path.exists()

    def test_different_versions_cached_separately(self):
        """SHOULD maintain separate cache entries for different versions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ComfyUICacheManager(cache_base_path=Path(tmpdir))

            # Cache v0.3.19
            dir1 = Path(tmpdir) / "ComfyUI_v19"
            dir1.mkdir()
            (dir1 / "main.py").write_text("# v0.3.19")

            spec1 = ComfyUISpec(version="v0.3.19", version_type="release")
            cache.cache_comfyui(spec1, dir1)

            # Cache v0.3.20
            dir2 = Path(tmpdir) / "ComfyUI_v20"
            dir2.mkdir()
            (dir2 / "main.py").write_text("# v0.3.20")

            spec2 = ComfyUISpec(version="v0.3.20", version_type="release")
            cache.cache_comfyui(spec2, dir2)

            # Both should exist independently
            cached1 = cache.get_cached_comfyui(spec1)
            cached2 = cache.get_cached_comfyui(spec2)

            assert (cached1 / "main.py").read_text() == "# v0.3.19"
            assert (cached2 / "main.py").read_text() == "# v0.3.20"
