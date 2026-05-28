"""Public git helper API for ComfyGit Core consumers."""

from pathlib import Path

from .models import GitRemoteRefs
from .utils.git import (
    git_list_remote_refs,
    git_ls_remote_with_auth,
    is_git_url,
    is_github_url,
    normalize_github_url,
    parse_git_url_with_subdir,
    parse_github_url,
)

__all__ = [
    "check_remote_auth",
    "is_git_url",
    "is_github_url",
    "list_remote_refs",
    "normalize_github_url",
    "parse_git_url_with_subdir",
    "parse_github_url",
]


def list_remote_refs(url: str, repo_path: Path | None = None) -> GitRemoteRefs:
    """List importable remote refs for a Git repository URL."""
    return GitRemoteRefs.from_dict(git_list_remote_refs(url, repo_path))


def check_remote_auth(repo_path: Path, remote_url: str, token: str) -> bool:
    """Return whether a token can access a remote URL from a repository path."""
    return git_ls_remote_with_auth(repo_path, remote_url, token)
