"""Factory for creating and discovering workspaces."""

import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from ..core.workspace import Workspace, WorkspacePaths
from ..logging.logging_config import get_logger
from ..models.credentials import CredentialStore
from ..models.exceptions import (
    CDWorkspaceError,
    CDWorkspaceExistsError,
    CDWorkspaceNotFoundError,
)
from ..models.workspace_config import ModelDirectory, WorkspaceConfig
from ..repositories.workspace_config_repository import WorkspaceConfigRepository
from ..utils.filesystem import harden_private_file

logger = get_logger(__name__)


class WorkspaceFactory:
    """Factory for creating and discovering ComfyGit workspaces."""

    @staticmethod
    def get_paths(path: Path | None = None) -> WorkspacePaths:
        # Determine workspace path
        if path:
            workspace_path = path
        elif comfygit_home := os.environ.get("COMFYGIT_HOME"):
            workspace_path = Path(comfygit_home)
        else:
            workspace_path = Path.home() / "comfygit"
        return WorkspacePaths(workspace_path)

    @staticmethod
    def find(
        path: Path | None = None,
        *,
        credential_store: CredentialStore | None = None,
    ) -> Workspace:
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

        harden_private_file(workspace_paths.workspace_file)
        return Workspace(workspace_paths, credential_store=credential_store)

    @staticmethod
    def create(
        path: Path | None = None,
        *,
        credential_store: CredentialStore | None = None,
    ) -> Workspace:
        """Create a new ComfyGit workspace.

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

            # Initialize metadata through the hardened atomic repository path.
            now = datetime.now().isoformat()
            metadata = WorkspaceConfig(
                version=1,
                active_environment="",
                created_at=now,
                workspace_id=str(uuid4()),
                global_model_directory=ModelDirectory(
                    path=str(workspace_paths.models),
                    added_at=now,
                    last_sync=now,
                ),
            )
            WorkspaceConfigRepository(
                workspace_paths.workspace_file,
                default_models_path=workspace_paths.models,
            ).save(metadata)

            workspace = Workspace(workspace_paths, credential_store=credential_store)

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
