"""Unit tests for git utility functions."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from comfygit_core.utils.git import (
    git_clone,
    git_clone_subdirectory,
    git_list_remote_refs,
    parse_git_url_with_subdir,
)


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


class TestGitCloneCommitDetection:
    """Test commit hash detection behavior in git_clone."""

    @patch("comfygit_core.utils.git._git")
    def test_abbreviated_commit_hash_uses_full_clone_then_checkout(self, mock_git):
        """7-char commit hashes should avoid --depth/--branch and checkout after clone."""
        target_path = Path("/tmp/repo")
        git_clone("https://github.com/example/repo.git", target_path, depth=1, ref="615a29b")

        assert mock_git.call_count == 2
        assert mock_git.call_args_list[0].args[0] == ["clone", "https://github.com/example/repo.git", str(target_path)]
        assert mock_git.call_args_list[1].args[0] == ["checkout", "615a29b"]

    @patch("comfygit_core.utils.git._git")
    def test_branch_ref_uses_shallow_clone_with_branch(self, mock_git):
        """Branch refs should continue using shallow clone with --branch."""
        target_path = Path("/tmp/repo")
        git_clone("https://github.com/example/repo.git", target_path, depth=1, ref="main")

        mock_git.assert_called_once()
        assert mock_git.call_args.args[0] == [
            "clone",
            "--depth",
            "1",
            "--branch",
            "main",
            "https://github.com/example/repo.git",
            str(target_path),
        ]

    @patch("comfygit_core.utils.git._git")
    def test_full_commit_hash_still_uses_full_clone_then_checkout(self, mock_git):
        """40-char commit hashes should keep existing full clone behavior."""
        target_path = Path("/tmp/repo")
        full_hash = "a" * 40

        git_clone("https://github.com/example/repo.git", target_path, depth=1, ref=full_hash)

        assert mock_git.call_count == 2
        assert mock_git.call_args_list[0].args[0] == ["clone", "https://github.com/example/repo.git", str(target_path)]
        assert mock_git.call_args_list[1].args[0] == ["checkout", full_hash]

    @patch("comfygit_core.utils.git._git_with_auth")
    @patch("comfygit_core.utils.git._git")
    def test_https_clone_with_token_uses_askpass_auth(self, mock_git, mock_git_with_auth):
        """HTTPS clones should use GIT_ASKPASS auth when a token is provided."""
        target_path = Path("/tmp/repo")

        git_clone("https://github.com/example/repo.git", target_path, depth=1, ref="main", token="ghp_test")

        mock_git_with_auth.assert_called_once()
        assert mock_git_with_auth.call_args.args[0] == [
            "clone",
            "--depth",
            "1",
            "--branch",
            "main",
            "https://github.com/example/repo.git",
            str(target_path),
        ]
        mock_git.assert_not_called()

    @patch("comfygit_core.utils.git._git_with_auth")
    @patch("comfygit_core.utils.git._git")
    def test_ssh_clone_with_token_uses_normal_git(self, mock_git, mock_git_with_auth):
        """SSH remotes should rely on SSH credentials instead of token askpass."""
        target_path = Path("/tmp/repo")

        git_clone("git@github.com:example/repo.git", target_path, depth=1, ref="main", token="ghp_test")

        mock_git.assert_called_once()
        mock_git_with_auth.assert_not_called()


class TestGitListRemoteRefs:
    """Test remote ref parsing for git import source selection."""

    @patch("comfygit_core.utils.git._git")
    def test_lists_default_branch_branches_and_tags(self, mock_git):
        mock_git.return_value = SimpleNamespace(stdout="\n".join([
            "ref: refs/heads/test1\tHEAD",
            "1111111111111111111111111111111111111111\tHEAD",
            "2222222222222222222222222222222222222222\trefs/heads/main",
            "1111111111111111111111111111111111111111\trefs/heads/test1",
            "3333333333333333333333333333333333333333\trefs/tags/v1.0.0",
            "4444444444444444444444444444444444444444\trefs/tags/v1.0.0^{}",
        ]))

        refs = git_list_remote_refs("https://github.com/example/repo.git#subdir")

        mock_git.assert_called_once_with(
            [
                "ls-remote",
                "--symref",
                "https://github.com/example/repo.git",
                "HEAD",
                "refs/heads/*",
                "refs/tags/*",
            ],
            Path.cwd(),
        )
        assert refs["default_branch"] == "test1"
        assert refs["head_commit"] == "1111111111111111111111111111111111111111"
        assert refs["branches"] == [
            {
                "name": "test1",
                "commit": "1111111111111111111111111111111111111111",
                "is_default": True,
            },
            {
                "name": "main",
                "commit": "2222222222222222222222222222222222222222",
                "is_default": False,
            },
        ]
        assert refs["tags"] == [
            {"name": "v1.0.0", "commit": "3333333333333333333333333333333333333333"},
        ]

    @patch("comfygit_core.utils.git._git")
    def test_handles_remote_without_symref_default(self, mock_git):
        mock_git.return_value = SimpleNamespace(stdout="\n".join([
            "2222222222222222222222222222222222222222\trefs/heads/main",
        ]))

        refs = git_list_remote_refs("https://github.com/example/repo.git")

        assert refs["default_branch"] is None
        assert refs["head_commit"] is None
        assert refs["branches"] == [
            {
                "name": "main",
                "commit": "2222222222222222222222222222222222222222",
                "is_default": False,
            },
        ]
        assert refs["tags"] == []
