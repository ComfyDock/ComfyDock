"""Utility functions for ComfyGit CLI."""

import sys
from typing import TYPE_CHECKING

from comfygit_core.factories.workspace_factory import WorkspaceFactory
from comfygit_core.models.exceptions import CDWorkspaceNotFoundError

from .logging.environment_logger import WorkspaceLogger

if TYPE_CHECKING:
    from comfygit_core.core.workspace import Workspace


def get_workspace_or_exit() -> "Workspace":
    """Get workspace or exit with error message."""
    try:
        workspace = WorkspaceFactory.find()
        # Initialize workspace logging
        WorkspaceLogger.set_workspace_path(workspace.path)
        return workspace
    except CDWorkspaceNotFoundError:
        print("✗ No workspace initialized. Run 'cg init' first.")
        sys.exit(1)

def get_workspace_optional() -> "Workspace | None":
    """Get workspace if it exists."""
    try:
        workspace = WorkspaceFactory.find()
        # Initialize workspace logging
        WorkspaceLogger.set_workspace_path(workspace.path)
        return workspace
    except CDWorkspaceNotFoundError:
        return None
