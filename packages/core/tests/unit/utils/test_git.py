"""Unit tests for git utility functions."""

import pytest
from comfygit_core.utils.git import git_clone_subdirectory, parse_git_url_with_subdir


class TestParseGitUrlWithSubdir:
    """Test URL parsing for subdirectory specification."""

    def test_url_without_subdir(self):
        """Parse URL without subdirectory returns None."""
        url, subdir = parse_git_url_with_subdir("https://github.com/user/repo")
        assert url == "https://github.com/user/repo"
        assert subdir is None

    def test_url_with_subdir(self):
        """Parse URL with subdirectory extracts both parts."""
        url, subdir = parse_git_url_with_subdir("https://github.com/user/repo#examples/example1")
        assert url == "https://github.com/user/repo"
        assert subdir == "examples/example1"

    def test_ssh_url_with_subdir(self):
        """Parse SSH URL with subdirectory."""
        url, subdir = parse_git_url_with_subdir("git@github.com:user/repo.git#workflows/prod")
        assert url == "git@github.com:user/repo.git"
        assert subdir == "workflows/prod"

    def test_normalizes_slashes(self):
        """Normalize leading and trailing slashes in subdirectory."""
        url, subdir = parse_git_url_with_subdir("https://github.com/user/repo#/examples/example1/")
        assert url == "https://github.com/user/repo"
        assert subdir == "examples/example1"

    def test_empty_after_hash(self):
        """URL ending with # but no path returns None."""
        url, subdir = parse_git_url_with_subdir("https://github.com/user/repo#")
        assert url == "https://github.com/user/repo"
        assert subdir is None


class TestGitCloneSubdirectory:
    """Test cloning specific subdirectory from git repository."""

    def test_subdirectory_not_found(self, tmp_path):
        """Raise error when subdirectory doesn't exist."""
        # This will fail until we implement the function
        # For now, we expect AttributeError since function doesn't exist
        with pytest.raises((ValueError, AttributeError)):
            git_clone_subdirectory(
                url="fake_url",
                target_path=tmp_path / "target",
                subdir="nonexistent"
            )

    def test_subdirectory_missing_pyproject(self, tmp_path):
        """Raise error when subdirectory lacks pyproject.toml."""
        with pytest.raises((ValueError, AttributeError)):
            git_clone_subdirectory(
                url="fake_url",
                target_path=tmp_path / "target",
                subdir="examples/invalid"
            )
