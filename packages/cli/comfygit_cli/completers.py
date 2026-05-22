"""Custom argcomplete completers for ComfyGit CLI."""
import argparse
from typing import Any

from argcomplete.io import warn
from comfygit_core import Environment, Workspace
from comfygit_core.models import CDWorkspaceNotFoundError

# ============================================================================
# Shared Utilities
# ============================================================================

def get_workspace_safe() -> Workspace | None:
    """Get workspace or return None if not initialized."""
    try:
        return Workspace.open()
    except CDWorkspaceNotFoundError:
        return None
    except Exception as e:
        warn(f"Error loading workspace: {e}")
        return None


def get_env_from_args(parsed_args: argparse.Namespace, workspace: Workspace) -> Environment | None:
    """Get environment from -e flag or active environment.

    Args:
        parsed_args: Parsed arguments from argparse
        workspace: Workspace instance

    Returns:
        Environment instance or None
    """
    try:
        # Check for -e/--env flag
        env_name = getattr(parsed_args, 'target_env', None)
        if env_name:
            return workspace.get_environment(env_name, auto_sync=False)

        # Fall back to active environment
        env = workspace.get_active_environment()
        if not env:
            warn("No active environment. Use -e or run 'cg use <env>'")
        return env
    except Exception as e:
        warn(f"Error loading environment: {e}")
        return None


def filter_by_prefix(items: list[str], prefix: str) -> list[str]:
    """Filter items that start with the given prefix."""
    return [item for item in items if item.startswith(prefix)]


# ============================================================================
# Completers
# ============================================================================

def environment_completer(prefix: str, parsed_args: argparse.Namespace, **kwargs: Any) -> list[str]:
    """Complete environment names from workspace.

    Used for:
    - cg use <TAB>
    - cg delete <TAB>
    - cg -e <TAB>
    """
    workspace = get_workspace_safe()
    if not workspace:
        return []

    try:
        envs = workspace.list_environments()
        names = [env.name for env in envs]
        return filter_by_prefix(names, prefix)
    except Exception as e:
        warn(f"Error listing environments: {e}")
        return []


def workflow_completer(prefix: str, parsed_args: argparse.Namespace, **kwargs: Any) -> list[str]:
    """Complete workflow names, prioritizing unresolved workflows.

    Smart ordering:
    1. New/modified workflows (likely need resolution)
    2. Synced workflows

    Used for:
    - cg workflow resolve <TAB>
    """
    workspace = get_workspace_safe()
    if not workspace:
        return []

    env = get_env_from_args(parsed_args, workspace)
    if not env:
        return []

    try:
        workflows = env.list_workflows()

        # Build candidates with smart ordering
        candidates = []

        # Priority 1: Unresolved workflows (new/modified)
        candidates.extend(workflows.new)
        candidates.extend(workflows.modified)

        # Priority 2: Synced workflows
        candidates.extend(workflows.synced)

        # Remove .json extension and filter by prefix
        names = [name.replace('.json', '') for name in candidates]
        return filter_by_prefix(names, prefix)

    except Exception as e:
        warn(f"Error listing workflows: {e}")
        return []


def installed_node_completer(prefix: str, parsed_args: argparse.Namespace, **kwargs: Any) -> list[str]:
    """Complete installed node names.

    Used for:
    - cg node remove <TAB>
    - cg node update <TAB>
    """
    workspace = get_workspace_safe()
    if not workspace:
        return []

    env = get_env_from_args(parsed_args, workspace)
    if not env:
        return []

    try:
        nodes = env.list_nodes()
        # Use registry_id if available, otherwise fall back to name
        names = [node.registry_id or node.name for node in nodes]
        return filter_by_prefix(names, prefix)
    except Exception as e:
        warn(f"Error listing nodes: {e}")
        return []


def branch_completer(prefix: str, parsed_args: argparse.Namespace, **kwargs: Any) -> list[str]:
    """Complete branch names from environment.

    Returns only branch names for commands that accept branches.

    Used for:
    - cg switch <TAB>
    """
    workspace = get_workspace_safe()
    if not workspace:
        return []

    env = get_env_from_args(parsed_args, workspace)
    if not env:
        return []

    try:
        branches = env.list_branches()
        names = [branch.name for branch in branches]
        return filter_by_prefix(names, prefix)

    except Exception as e:
        warn(f"Error loading branches: {e}")
        return []


def commit_hash_completer(prefix: str, parsed_args: argparse.Namespace, **kwargs: Any) -> list[str]:
    """Complete commit hashes from environment history.

    Returns only short commit hashes for clean tab completion.
    Users can run 'cg log' to see commit messages.

    Used for:
    - cg reset <TAB>
    """
    workspace = get_workspace_safe()
    if not workspace:
        return []

    env = get_env_from_args(parsed_args, workspace)
    if not env:
        return []

    try:
        # Get recent commits (50 should cover most use cases)
        history = env.get_commit_history(limit=50)

        # Return only hashes for clean completion
        hashes = [commit.hash for commit in history]
        return filter_by_prefix(hashes, prefix)

    except Exception as e:
        warn(f"Error loading commits: {e}")
        return []


def ref_completer(prefix: str, parsed_args: argparse.Namespace, **kwargs: Any) -> list[str]:
    """Complete git refs (branches and commits) from environment.

    Returns branches first (most common use case), then recent commit hashes.
    This provides comprehensive completion for commands like checkout that
    accept both branches and commits.

    Used for:
    - cg checkout <TAB>
    """
    workspace = get_workspace_safe()
    if not workspace:
        return []

    env = get_env_from_args(parsed_args, workspace)
    if not env:
        return []

    try:
        candidates = []

        # Priority 1: Branches (most common for checkout)
        branches = env.list_branches()
        candidates.extend([branch.name for branch in branches])

        # Priority 2: Recent commits
        history = env.get_commit_history(limit=50)
        candidates.extend([commit.hash for commit in history])

        return filter_by_prefix(candidates, prefix)

    except Exception as e:
        warn(f"Error loading refs: {e}")
        return []
