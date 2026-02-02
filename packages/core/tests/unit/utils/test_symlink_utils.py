"""Tests for symlink utility functions."""
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from comfygit_core.models.exceptions import CDEnvironmentError
from comfygit_core.utils.symlink_utils import (
    create_platform_link,
    create_windows_junction,
    is_link,
    is_safe_to_delete,
)


class TestIsLink:
    """Test symlink detection across platforms."""

    def test_detects_symlink(self, tmp_path):
        """Test detection of regular symlink."""
        target = tmp_path / "target"
        target.mkdir()
        link = tmp_path / "link"
        link.symlink_to(target)

        assert is_link(link) is True

    def test_detects_non_symlink_directory(self, tmp_path):
        """Test that real directories are not detected as links."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()

        assert is_link(real_dir) is False

    def test_detects_non_symlink_file(self, tmp_path):
        """Test that regular files are not detected as links."""
        regular_file = tmp_path / "file.txt"
        regular_file.write_text("content")

        assert is_link(regular_file) is False

    def test_handles_nonexistent_path(self, tmp_path):
        """Test that nonexistent paths return False."""
        nonexistent = tmp_path / "does_not_exist"

        assert is_link(nonexistent) is False

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
    def test_detects_windows_junction(self, tmp_path):
        """Test detection of Windows junction points."""
        target = tmp_path / "target"
        target.mkdir()
        junction = tmp_path / "junction"

        # Create junction using mklink
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
            check=True,
            capture_output=True,
        )

        assert is_link(junction) is True


class TestCreatePlatformLink:
    """Test platform-specific symlink creation."""

    @pytest.mark.skipif(os.name == "nt", reason="Unix-specific test")
    def test_creates_symlink_on_unix(self, tmp_path):
        """Test symlink creation on Unix platforms."""
        target = tmp_path / "target"
        target.mkdir()
        link = tmp_path / "link"

        create_platform_link(link, target, "test")

        assert link.exists()
        assert is_link(link)
        assert link.resolve() == target.resolve()

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
    def test_creates_junction_on_windows(self, tmp_path):
        """Test junction creation on Windows."""
        target = tmp_path / "target"
        target.mkdir()
        link = tmp_path / "link"

        create_platform_link(link, target, "test")

        assert link.exists()
        assert is_link(link)
        assert link.resolve() == target.resolve()

    def test_raises_on_link_creation_failure(self, tmp_path):
        """Test error handling when link creation fails."""
        target = tmp_path / "target"
        target.mkdir()
        link = tmp_path / "link"

        # Create a file at the link location to cause conflict
        link.write_text("blocking")

        with pytest.raises(CDEnvironmentError, match="Failed to create test"):
            create_platform_link(link, target, "test")


class TestCreateWindowsJunction:
    """Test Windows junction creation."""

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
    def test_creates_junction(self, tmp_path):
        """Test junction creation using mklink."""
        target = tmp_path / "target"
        target.mkdir()
        junction = tmp_path / "junction"

        create_windows_junction(junction, target, "test")

        assert junction.exists()
        assert is_link(junction)
        assert junction.resolve() == target.resolve()

    def test_raises_on_junction_failure_with_mock(self, tmp_path):
        """Test error handling when junction creation fails (mocked)."""
        target = tmp_path / "target"
        target.mkdir()
        junction = tmp_path / "junction"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="Access denied",
            )

            with pytest.raises(CDEnvironmentError, match="Failed to create test junction"):
                create_windows_junction(junction, target, "test")


class TestIsSafeToDelete:
    """Test safe deletion checks."""

    def test_empty_directory_is_safe(self, tmp_path):
        """Test that completely empty directory is safe to delete."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        assert is_safe_to_delete(empty_dir, set()) is True

    def test_directory_with_only_safe_files_is_safe(self, tmp_path):
        """Test that directory with only placeholder files is safe."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        (test_dir / ".gitkeep").touch()
        (test_dir / ".gitignore").touch()
        (test_dir / "Put models here.txt").touch()

        safe_files = {".gitkeep", ".gitignore", "Put models here.txt"}

        assert is_safe_to_delete(test_dir, safe_files) is True

    def test_directory_with_other_files_is_not_safe(self, tmp_path):
        """Test that directory with actual content is not safe."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        (test_dir / ".gitkeep").touch()
        (test_dir / "important_file.txt").touch()

        safe_files = {".gitkeep", ".gitignore"}

        assert is_safe_to_delete(test_dir, safe_files) is False

    def test_directory_with_subdirectories_with_files_is_not_safe(self, tmp_path):
        """Test that directory with nested content is not safe."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        subdir = test_dir / "subdir"
        subdir.mkdir()
        (subdir / "file.txt").touch()

        assert is_safe_to_delete(test_dir, set()) is False

    def test_directory_with_empty_subdirectories_is_safe(self, tmp_path):
        """Test that directory with only empty subdirectories is safe."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        (test_dir / "empty1").mkdir()
        (test_dir / "empty2").mkdir()
        (test_dir / "nested" / "empty3").mkdir(parents=True)

        assert is_safe_to_delete(test_dir, set()) is True

    def test_nonexistent_directory_is_safe(self, tmp_path):
        """Test that nonexistent directory is considered safe."""
        nonexistent = tmp_path / "does_not_exist"

        assert is_safe_to_delete(nonexistent, set()) is True

    def test_mixed_safe_and_empty_subdirs_is_safe(self, tmp_path):
        """Test directory with safe files and empty subdirs is safe."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        (test_dir / ".gitkeep").touch()
        (test_dir / "empty_subdir").mkdir()

        assert is_safe_to_delete(test_dir, {".gitkeep"}) is True
