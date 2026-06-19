"""Git information extraction for custom nodes."""
from pathlib import Path

from ..logging.logging_config import get_logger
from ..models.environment import GitInfo
from ..utils.git import (
    git_describe_tags,
    git_remote_get_url,
    git_rev_parse,
    git_status_porcelain,
)

logger = get_logger(__name__)


def get_node_git_info(node_path: Path) -> GitInfo | None:
    """Get git repository information for a custom node.

    Args:
        node_path: Path to the custom node directory

    Returns:
        GitInfo with git information or None if not a git repository
    """
    import re

    git_info = GitInfo()

    try:
        # Check if it's a git repository
        git_dir = node_path / ".git"
        if not git_dir.exists():
            return None

        # Get current commit hash
        commit = git_rev_parse(node_path, "HEAD")
        if commit:
            git_info.commit = commit

        # Get current branch
        branch = git_rev_parse(node_path, "HEAD", abbrev_ref=True)
        if branch and branch != "HEAD":
            git_info.branch = branch

        # Try to get current tag/version
        tag = git_describe_tags(node_path, exact_match=True)
        if tag:
            git_info.tag = tag
        else:
            # Try to get the most recent tag
            tag = git_describe_tags(node_path, abbrev=0)
            if tag:
                git_info.tag = tag

        # Get remote URL
        remote_url = git_remote_get_url(node_path)
        if remote_url:
            git_info.remote_url = remote_url

            # Extract GitHub info if it's a GitHub URL
            github_match = re.match(
                r"(?:https?://github\.com/|git@github\.com:)([^/]+)/([^/\.]+)",
                remote_url,
            )
            if github_match:
                git_info.github_owner = github_match.group(1)
                git_info.github_repo = github_match.group(2).replace(".git", "")

        # Check if there are uncommitted changes
        status_entries = git_status_porcelain(node_path, check=False)
        git_info.is_dirty = bool(status_entries)

        return git_info

    except Exception as e:
        logger.warning(f"Error getting git info for {node_path}: {e}")
        return None
