"""Factory for creating and discovering workspaces."""

import json
import os
from pathlib import Path

from ..core.workspace import Workspace, WorkspacePaths
from ..logging.logging_config import get_logger
from ..models.exceptions import (
    CDWorkspaceError,
    CDWorkspaceExistsError,
    CDWorkspaceNotFoundError,
)

logger = get_logger(__name__)


class WorkspaceFactory:
    """Factory for creating and discovering ComfyDock workspaces."""

    @staticmethod
    def get_paths(path: Path | None = None) -> WorkspacePaths:
        # Determine workspace path
        if path:
            workspace_path = path
        elif comfydock_home := os.environ.get("COMFYGIT_HOME"):
            workspace_path = Path(comfydock_home)
        else:
            workspace_path = Path.home() / "comfygit"
        return WorkspacePaths(workspace_path)

    @staticmethod
    def find(path: Path | None = None) -> Workspace:
        """Find an existing workspace.

        Args:
            path: Workspace path (defaults to ~/comfygit or COMFYGIT_HOME)

        Returns:
            Workspace instance

        Raises:
            CDWorkspaceNotFoundError: If workspace not found
        """
        # Determine workspace path
        workspace_paths = WorkspaceFactory.get_paths(path)
        if not workspace_paths.exists():
            raise CDWorkspaceNotFoundError(f"No workspace found at {workspace_paths.root}")

        return Workspace(workspace_paths)

    @staticmethod
    def create(path: Path | None = None) -> Workspace:
        """Create a new ComfyDock workspace.

        Args:
            path: Workspace directory (defaults to ~/comfygit)

        Returns:
            Initialized Workspace

        Raises:
            CDWorkspaceExistsError: If workspace already exists
            CDWorkspaceError: If directory exists and is not empty
            PermissionError: If cannot create directories
            OSError: If filesystem operations fail
        """
        # Check if already exists
        workspace_paths = WorkspaceFactory.get_paths(path)
        if workspace_paths.exists():
            logger.info(f"Workspace already exists at {workspace_paths.root}")
            raise CDWorkspaceExistsError(f"Workspace already exists at {workspace_paths.root}")

        # Check if path exists but is not empty
        if workspace_paths.root.exists() and any(workspace_paths.root.iterdir()):
            raise CDWorkspaceError(f"Directory exists and is not empty: {workspace_paths.root}")

        try:
            # Create workspace structure (includes models/ directory)
            workspace_paths.ensure_directories()

            # Initialize metadata with default models directory
            from datetime import datetime
            metadata = {
                "version": 1,
                "active_environment": "",
                "created_at": datetime.now().isoformat(),
                "global_model_directory": {
                    "path": str(workspace_paths.models),
                    "added_at": datetime.now().isoformat(),
                    "last_sync": datetime.now().isoformat()
                }
            }

            with open(workspace_paths.workspace_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)

            workspace = Workspace(workspace_paths)

            # Write schema version to mark as modern workspace
            workspace._write_schema_version()

            logger.info(f"Created workspace at {workspace_paths.root}")
            logger.info(f"Default models directory: {workspace_paths.models}")

            return workspace

        except PermissionError as e:
            raise PermissionError(f"Cannot create workspace at {workspace_paths.root}: insufficient permissions") from e
        except OSError as e:
            # Clean up partial workspace if creation failed
            if workspace_paths.exists() and not any(workspace_paths.root.iterdir()):
                workspace_paths.root.rmdir()
            raise OSError(f"Failed to create workspace at {workspace_paths.root}: {e}") from e
