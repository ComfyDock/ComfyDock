"""Utility functions for ComfyGit CLI."""

import sys

from comfygit_core import Workspace
from comfygit_core.models import CDWorkspaceNotFoundError

from .logging.environment_logger import WorkspaceLogger


def get_workspace_or_exit() -> Workspace:
    """Get workspace or exit with error message."""
    try:
        workspace = Workspace.open()
        # Initialize workspace logging
        WorkspaceLogger.set_workspace_path(workspace.path)
        return workspace
    except CDWorkspaceNotFoundError:
        print("✗ No workspace initialized. Run 'cg init' first.")
        sys.exit(1)

def get_workspace_optional() -> Workspace | None:
    """Get workspace if it exists."""
    try:
        workspace = Workspace.open()
        # Initialize workspace logging
        WorkspaceLogger.set_workspace_path(workspace.path)
        return workspace
    except CDWorkspaceNotFoundError:
        return None
