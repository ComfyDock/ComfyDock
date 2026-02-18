"""ComfyGit workspace - manages multiple environments within a validated workspace."""

import json
import re
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from comfygit_core.repositories.comfyui_builtin_versions_repository import (
    ComfyUIBuiltinVersionsRepository,
)
from comfygit_core.repositories.node_mappings_repository import NodeMappingsRepository
from comfygit_core.repositories.workspace_config_repository import WorkspaceConfigRepository

from ..analyzers.model_scanner import ModelScanner
from ..factories.environment_factory import EnvironmentFactory
from ..logging.logging_config import get_logger
from ..models.exceptions import (
    CDEnvironmentExistsError,
    CDEnvironmentNotFoundError,
    CDWorkspaceError,
    ComfyDockError,
    UVCommandError,
)
from ..models.shared import ModelDetails, ModelWithLocation
from ..repositories.model_repository import ModelRepository
from ..services.model_downloader import ModelDownloader
from ..services.registry_data_manager import RegistryDataManager
from ..utils.environment_cleanup import (
    cleanup_partial_environment,
    is_environment_complete,
    remove_environment_directory,
)
from .environment import Environment

if TYPE_CHECKING:
    from ..models.protocols import EnvironmentCreateProgress, ImportCallbacks
    from ..models.shared import LegacyCleanupResult

logger = get_logger(__name__)


# Environment names must be valid as part of a PEP 508 package name
# (used in pyproject.toml as "comfygit-env-{name}") and safe as directory names.
# Allowed: letters, digits, hyphens, underscores, dots.
# Must start and end with a letter or digit.
_ENV_NAME_PATTERN = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$')

_ENV_NAME_MAX_LENGTH = 128


def _validate_environment_name(name: str) -> None:
    """Validate environment name is safe and not reserved.

    Args:
        name: Environment name to validate

    Raises:
        CDEnvironmentError: If name is invalid or reserved
    """
    from ..models.exceptions import CDEnvironmentError

    RESERVED_NAMES = {'workspace', 'logs', 'models', 'input', 'output', '.comfygit'}

    # Ensure not empty first
    if not name or not name.strip():
        raise CDEnvironmentError("Environment name cannot be empty")

    # Check reserved names (case-insensitive)
    if name.lower() in RESERVED_NAMES:
        raise CDEnvironmentError(
            f"Environment name '{name}' is reserved. "
            f"Please choose a different name."
        )

    # Prevent path traversal and separators (check before hidden dir check)
    if '/' in name or '\\' in name or '..' in name:
        raise CDEnvironmentError(
            "Environment name cannot contain path separators"
        )

    # Prevent hidden directories
    if name.startswith('.'):
        raise CDEnvironmentError(
            "Environment name cannot start with '.'"
        )

    # Enforce max length
    if len(name) > _ENV_NAME_MAX_LENGTH:
        raise CDEnvironmentError(
            f"Environment name is too long ({len(name)} chars). "
            f"Maximum length is {_ENV_NAME_MAX_LENGTH} characters."
        )

    # Validate character set (PEP 508 compatible + safe directory name)
    if not _ENV_NAME_PATTERN.match(name):
        raise CDEnvironmentError(
            f"Invalid environment name '{name}'. "
            f"Names can only contain letters, numbers, hyphens (-), "
            f"underscores (_), and dots (.). "
            f"Must start and end with a letter or number."
        )


class WorkspacePaths:
    """All paths for the workspace."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    @property
    def environments(self) -> Path:
        return self.root / "environments"

    @property
    def metadata(self) -> Path:
        return self.root / ".metadata"

    @property
    def workspace_file(self) -> Path:
        return self.metadata / "workspace.json"

    @property
    def cache(self) -> Path:
        return self.root / "comfygit_cache"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def input(self) -> Path:
        """Base directory for per-environment input directories."""
        return self.root / "input"

    @property
    def output(self) -> Path:
        """Base directory for per-environment output directories."""
        return self.root / "output"

    @property
    def system_nodes(self) -> Path:
        """Legacy directory for workspace-level system nodes.

        In schema v1, comfygit-manager was symlinked from this directory.
        In schema v2, manager is tracked per-environment in pyproject.toml.
        This property is kept for legacy migration detection only.
        """
        return self.metadata / "system_nodes"

    @property
    def schema_version_file(self) -> Path:
        """Path to workspace schema version file."""
        return self.metadata / "version"

    def exists(self) -> bool:
        return self.root.exists() and self.metadata.exists()

    def ensure_directories(self) -> None:
        self.environments.mkdir(parents=True, exist_ok=True)
        self.metadata.mkdir(parents=True, exist_ok=True)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        self.models.mkdir(parents=True, exist_ok=True)
        self.input.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(parents=True, exist_ok=True)
        # Note: system_nodes is NOT created anymore (legacy, schema v1 only)

class Workspace:
    """Manages ComfyGit workspace and all environments within it.

    Represents an existing, validated workspace - no nullable state.
    """

    # Current workspace schema version (v2 = per-environment manager)
    CURRENT_SCHEMA_VERSION = 2

    def __init__(self, paths: WorkspacePaths):
        """Initialize workspace with validated paths.

        Args:
            paths: Validated WorkspacePaths instance
        """
        self.paths = paths

    def get_schema_version(self) -> int:
        """Get workspace schema version.

        Returns:
            1 if legacy (no version file), else the version from file.
        """
        version_file = self.paths.schema_version_file
        if not version_file.exists():
            return 1  # Legacy workspace
        try:
            return int(version_file.read_text().strip())
        except (ValueError, OSError):
            return 1  # Treat as legacy if file is corrupted

    def is_legacy_schema(self) -> bool:
        """Check if this is a legacy workspace (schema v1).

        Legacy workspaces use symlinked system nodes from .metadata/system_nodes/.
        Modern workspaces (v2+) track manager per-environment in pyproject.toml.
        """
        return self.get_schema_version() < self.CURRENT_SCHEMA_VERSION

    def has_legacy_system_nodes(self) -> bool:
        """Check if workspace has legacy system_nodes directory with content.

        This is a more specific check than is_legacy_schema() - it only returns
        True if there's actually a system_nodes directory with nodes in it.
        Used to determine if migration notice should be shown.
        """
        system_nodes_dir = self.paths.system_nodes
        if not system_nodes_dir.exists():
            return False
        # Check if there's at least one subdirectory (an actual node)
        return any(p.is_dir() for p in system_nodes_dir.iterdir())

    def _write_schema_version(self) -> None:
        """Write current schema version to workspace.

        Called during workspace creation to mark as modern schema.
        """
        self.paths.schema_version_file.write_text(str(self.CURRENT_SCHEMA_VERSION))

    def upgrade_schema_if_needed(self) -> bool:
        """Upgrade workspace schema to current version if no version file exists.

        This is called when creating new environments with per-env manager.
        Only writes the version file if it doesn't exist (preserves existing).

        Returns:
            True if upgraded, False if already has version file.
        """
        if self.paths.schema_version_file.exists():
            return False
        self._write_schema_version()
        return True

    def cleanup_legacy_system_nodes(self, force: bool = False) -> "LegacyCleanupResult":
        """Remove legacy .metadata/system_nodes/ directory.

        Scans all environments to verify none use legacy symlinks before removing.

        Args:
            force: Skip environment verification check

        Returns:
            LegacyCleanupResult with status and any environments still using legacy
        """
        import shutil

        from ..models.shared import LegacyCleanupResult

        system_nodes_dir = self.paths.system_nodes

        # Check if directory exists
        if not system_nodes_dir.exists():
            return LegacyCleanupResult(
                success=False,
                message="No legacy system_nodes directory found"
            )

        # If not forcing, check all environments for legacy symlinks
        if not force:
            legacy_envs = []
            for env in self.list_environments():
                try:
                    status = env.get_manager_status()
                    if status.is_legacy:
                        legacy_envs.append(env.name)
                except Exception:
                    pass  # Skip environments that can't be checked

            if legacy_envs:
                return LegacyCleanupResult(
                    success=False,
                    legacy_environments=legacy_envs,
                    message="Some environments still use legacy manager"
                )

        # Remove the directory
        try:
            shutil.rmtree(system_nodes_dir)
            self._write_schema_version()  # Ensure v2 after cleanup
            return LegacyCleanupResult(
                success=True,
                removed_path=str(system_nodes_dir),
                message=f"Removed {system_nodes_dir}"
            )
        except Exception as e:
            return LegacyCleanupResult(
                success=False,
                message=f"Failed to remove: {e}"
            )

    @property
    def path(self) -> Path:
        """Get workspace path."""
        return self.paths.root

    @cached_property
    def workspace_config_manager(self) -> WorkspaceConfigRepository:
        return WorkspaceConfigRepository(
            self.paths.workspace_file,
            default_models_path=self.paths.models
        )

    @cached_property
    def registry_data_manager(self) -> RegistryDataManager:
        return RegistryDataManager(self.paths.cache)

    @cached_property
    def model_repository(self) -> ModelRepository:
        db_path = self.paths.cache / "models.db"
        repo = ModelRepository(db_path)

        # Initialize current_directory from config if available
        try:
            current_dir = self.workspace_config_manager.get_models_directory()
            repo.set_current_directory(current_dir)
        except ComfyDockError:
            # No models directory configured yet - filtering disabled
            pass

        return repo

    @cached_property
    def node_mapping_repository(self) -> NodeMappingsRepository:
        return NodeMappingsRepository(self.registry_data_manager)

    @cached_property
    def comfyui_builtin_versions_repository(self) -> ComfyUIBuiltinVersionsRepository:
        return ComfyUIBuiltinVersionsRepository(self.registry_data_manager)

    @cached_property
    def model_scanner(self) -> ModelScanner:
        from ..configs.model_config import ModelConfig
        config = ModelConfig.load()
        return ModelScanner(self.model_repository, config)

    @cached_property
    def model_downloader(self) -> ModelDownloader:
        return ModelDownloader(
            model_repository=self.model_repository,
            workspace_config=self.workspace_config_manager
        )

    @cached_property
    def import_analyzer(self):
        """Get import analysis service."""
        from ..services.import_analyzer import ImportAnalyzer
        return ImportAnalyzer(
            model_repository=self.model_repository,
            node_mapping_repository=self.node_mapping_repository
        )

    def update_registry_data(self) -> bool:
        """Force update registry data from GitHub.

        Returns:
            True if successful, False otherwise
        """
        return self.registry_data_manager.force_update()

    def get_registry_info(self) -> dict:
        """Get information about cached registry data.

        Returns:
            Dict with cache status and metadata
        """
        return self.registry_data_manager.get_cache_info()

    def list_environments(self) -> list[Environment]:
        """List all environments in the workspace.

        Only returns fully initialized environments (those with completion marker).
        Partial environments from interrupted creation are excluded.
        """
        environments = []

        if not self.paths.environments.exists():
            return environments

        for env_dir in self.paths.environments.iterdir():
            cec_path = env_dir / ".cec"
            if env_dir.is_dir() and cec_path.exists() and is_environment_complete(cec_path):
                try:
                    env = Environment(
                        name=env_dir.name,
                        path=env_dir,
                        workspace=self
                    )
                    environments.append(env)
                except Exception as e:
                    logger.warning(f"Could not load environment {env_dir.name}: {e}")

        return sorted(environments, key=lambda e: e.name)

    def get_environment(self, name: str, auto_sync: bool = True, progress=None) -> Environment:
        """Get an environment by name.

        Args:
            name: Environment name
            auto_sync: If True, sync model index before returning environment.
                      Use True for operations that need model resolution (e.g., workflow resolve).
                      Use False for read-only operations (e.g., status, list).
            progress: Optional progress callback for model sync (ModelScanProgress protocol)

        Returns:
            Environment instance if found

        Raises:
            CDEnvironmentNotFoundError: If environment not found
        """
        # Auto-sync model index if requested (for operations needing fresh model data)
        if auto_sync:
            logger.debug("Auto-syncing model index...")
            self.sync_model_directory(progress=progress)

        env_path = self.paths.environments / name

        if not env_path.exists() or not (env_path / ".cec").exists():
            raise CDEnvironmentNotFoundError(f"Environment '{name}' not found")

        return Environment(
            name=name,
            path=env_path,
            workspace=self
        )

    def create_environment(
        self,
        name: str,
        python_version: str = "3.12",
        comfyui_version: str | None = None,
        template_path: Path | None = None,
        torch_backend: str = "auto",
        no_manager: bool = False,
        progress: "EnvironmentCreateProgress | None" = None,
    ) -> Environment:
        """Create a new environment.

        Args:
            name: Environment name
            python_version: Python version (e.g., "3.12")
            comfyui_version: ComfyUI version
            template_path: Optional template to copy from
            torch_backend: PyTorch backend (auto, cpu, cu118, cu121, etc.)
            no_manager: Skip comfygit-manager install (headless mode)
            progress: Optional progress callback for tracking creation phases

        Returns:
            Environment

        Raises:
            CDEnvironmentExistsError: If environment already exists
            CDEnvironmentError: If name is reserved or invalid
            ComfyDockError: If environment creation fails
            RuntimeError: If environment creation fails
        """
        # Validate name first
        _validate_environment_name(name)

        env_path = self.paths.environments / name

        if env_path.exists():
            raise CDEnvironmentExistsError(f"Environment '{name}' already exists")

        try:
            # Create the environment
            environment = EnvironmentFactory.create(
                name=name,
                env_path=env_path,
                workspace=self,
                python_version=python_version,
                comfyui_version=comfyui_version,
                torch_backend=torch_backend,
                no_manager=no_manager,
                progress=progress,
            )

            # TODO: Apply template if provided
            if template_path and template_path.exists():
                logger.info(f"Applying template from {template_path}")
                # Copy template pyproject.toml and apply
                pass

            return environment

        except Exception as e:
            logger.error(f"Failed to create environment: {e}")

            if isinstance(e, ComfyDockError):
                raise
            else:
                raise RuntimeError(f"Failed to create environment '{name}': {e}") from e

        finally:
            # Cleanup runs on ANY exit (Exception, KeyboardInterrupt, etc.)
            # Only cleanup if environment wasn't successfully completed
            cec_path = env_path / ".cec"
            if not is_environment_complete(cec_path) and env_path.exists():
                if not cleanup_partial_environment(env_path):
                    logger.warning(
                        f"Could not fully remove partial environment at {env_path}. "
                        f"You may need to delete it manually or reboot to release file locks."
                    )

    def preview_import(self, tarball_path: Path):
        """Preview import requirements without creating environment.

        Extracts to temp directory, analyzes, then cleans up.

        Args:
            tarball_path: Path to .tar.gz bundle

        Returns:
            ImportAnalysis with full breakdown
        """
        import tempfile

        from ..managers.export_import_manager import ExportImportManager

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_cec = Path(temp_dir) / ".cec"

            # Extract to temp location
            manager = ExportImportManager(temp_cec, Path(temp_dir) / "ComfyUI")
            manager.extract_import(tarball_path, temp_cec)

            # Analyze
            return self.import_analyzer.analyze_import(temp_cec)

    def preview_git_import(
        self,
        git_url: str,
        branch: str | None = None
    ):
        """Preview git import requirements without creating environment.

        Clones to temp directory, analyzes, then cleans up.
        Supports subdirectory syntax: <git_url>#<subdirectory>

        Args:
            git_url: Git repository URL (with optional #subdirectory)
            branch: Optional branch/tag/commit

        Returns:
            ImportAnalysis with full breakdown
        """
        import tempfile

        from ..utils.git import git_clone, git_clone_subdirectory, parse_git_url_with_subdir

        # Parse URL for subdirectory
        base_url, subdir = parse_git_url_with_subdir(git_url)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_cec = Path(temp_dir) / ".cec"

            # Clone to temp location (with subdirectory extraction if specified)
            if subdir:
                git_clone_subdirectory(base_url, temp_cec, subdir, ref=branch)
            else:
                git_clone(base_url, temp_cec, ref=branch)

            # Analyze
            return self.import_analyzer.analyze_import(temp_cec)

    def import_environment(
        self,
        tarball_path: Path,
        name: str,
        model_strategy: str = "all",
        callbacks: "ImportCallbacks | None" = None,
        torch_backend: str = "auto",
        no_manager: bool = False,
    ) -> Environment:
        """Import environment from tarball bundle.

        Complete workflow:
        1. Create environment structure and extract tarball
        2. Finalize import (clone ComfyUI, install deps, sync nodes, resolve models)

        Args:
            tarball_path: Path to .tar.gz bundle
            name: Name for imported environment
            model_strategy: "all", "required", or "skip"
            callbacks: Optional callbacks for progress updates
            torch_backend: PyTorch backend (auto, cpu, cu118, cu121, etc.)
            no_manager: Skip comfygit-manager install/registration (headless mode)

        Returns:
            Fully initialized Environment

        Raises:
            CDEnvironmentExistsError: If environment already exists
            CDEnvironmentError: If name is reserved or invalid
            ComfyDockError: If import fails
            RuntimeError: If import fails
        """
        # Validate name first
        _validate_environment_name(name)

        env_path = self.paths.environments / name

        if env_path.exists():
            raise CDEnvironmentExistsError(f"Environment '{name}' already exists")

        try:
            # Step 1: Create environment structure (extract .cec)
            environment = EnvironmentFactory.import_from_bundle(
                tarball_path=tarball_path,
                name=name,
                env_path=env_path,
                workspace=self,
                torch_backend=torch_backend,
            )

            # Step 2: Let environment complete its setup
            environment.finalize_import(model_strategy, callbacks, no_manager=no_manager)

            return environment

        except Exception as e:
            logger.error(f"Failed to import environment: {e}")

            if isinstance(e, ComfyDockError):
                raise
            else:
                raise RuntimeError(f"Failed to import environment '{name}': {e}") from e

        finally:
            # Cleanup runs on ANY exit (Exception, KeyboardInterrupt, etc.)
            # Only cleanup if environment wasn't successfully completed
            cec_path = env_path / ".cec"
            if not is_environment_complete(cec_path) and env_path.exists():
                if not cleanup_partial_environment(env_path):
                    logger.warning(
                        f"Could not fully remove partial environment at {env_path}. "
                        f"You may need to delete it manually or reboot to release file locks."
                    )

    def import_from_git(
        self,
        git_url: str,
        name: str,
        model_strategy: str = "all",
        branch: str | None = None,
        callbacks: "ImportCallbacks | None" = None,
        torch_backend: str = "auto",
        no_manager: bool = False,
    ) -> Environment:
        """Import environment from git repository.

        Complete workflow:
        1. Create environment structure and clone repository
        2. Finalize import (clone ComfyUI, install deps, sync nodes, resolve models)

        Args:
            git_url: Git repository URL (https://, git@, or local path)
            name: Name for imported environment
            model_strategy: "all", "required", or "skip"
            branch: Optional branch/tag/commit
            callbacks: Optional callbacks for progress updates
            torch_backend: PyTorch backend (auto, cpu, cu118, cu121, etc.)
            no_manager: Skip comfygit-manager install/registration (headless mode)

        Returns:
            Fully initialized Environment

        Raises:
            CDEnvironmentExistsError: If environment already exists
            CDEnvironmentError: If name is reserved or invalid
            ValueError: If repository is invalid
            ComfyDockError: If import fails
            RuntimeError: If import fails
        """
        # Validate name first
        _validate_environment_name(name)

        env_path = self.paths.environments / name

        if env_path.exists():
            raise CDEnvironmentExistsError(f"Environment '{name}' already exists")

        try:
            # Step 1: Create environment structure (clone git repo to .cec)
            environment = EnvironmentFactory.import_from_git(
                git_url=git_url,
                name=name,
                env_path=env_path,
                workspace=self,
                branch=branch,
                torch_backend=torch_backend,
            )

            # Step 2: Let environment complete its setup
            environment.finalize_import(model_strategy, callbacks, no_manager=no_manager)

            return environment

        except Exception as e:
            # Log UV command failures with full context
            if isinstance(e, UVCommandError):
                logger.error(f"UV command failed: {e.command}")
                if e.stderr:
                    logger.error(f"UV stderr:\n{e.stderr}")
                if e.stdout:
                    logger.error(f"UV stdout:\n{e.stdout}")

            logger.error(f"Failed to import from git: {e}")

            if isinstance(e, ComfyDockError):
                raise
            else:
                raise RuntimeError(f"Failed to import environment '{name}': {e}") from e

        finally:
            # Cleanup runs on ANY exit (Exception, KeyboardInterrupt, etc.)
            # Only cleanup if environment wasn't successfully completed
            cec_path = env_path / ".cec"
            if not is_environment_complete(cec_path) and env_path.exists():
                if not cleanup_partial_environment(env_path):
                    logger.warning(
                        f"Could not fully remove partial environment at {env_path}. "
                        f"You may need to delete it manually or reboot to release file locks."
                    )

    def delete_environment(self, name: str, delete_user_data: bool = False):
        """Delete an environment permanently.

        Args:
            name: Environment name
            delete_user_data: If True, also delete workspace input/output data.
                             If False (default), preserve user content.

        Raises:
            CDEnvironmentNotFoundError: If environment not found
            PermissionError: If deletion fails due to permissions
            OSError: If deletion fails for other reasons
        """
        env_path = self.paths.environments / name
        if not env_path.exists():
            raise CDEnvironmentNotFoundError(f"Environment '{name}' not found")

        # Check if this is the active environment
        active = self.get_active_environment()
        if active and active.name == name:
            self.set_active_environment(None)

        # Get user data info before deleting environment
        try:
            env = Environment(name=name, path=env_path, workspace=self)
            user_data_size = env.user_content_manager.get_user_data_size()
            has_user_data = (
                user_data_size["input"][0] > 0 or
                user_data_size["output"][0] > 0
            )

            if has_user_data:
                input_count, input_size = user_data_size["input"]
                output_count, output_size = user_data_size["output"]
                logger.info(
                    f"Environment '{name}' contains user data:\n"
                    f"  Input: {input_count} files ({input_size / 1024 / 1024:.1f} MB)\n"
                    f"  Output: {output_count} files ({output_size / 1024 / 1024:.1f} MB)"
                )

                if delete_user_data:
                    logger.info("Deleting user data (--delete-data flag set)")
                    env.user_content_manager.delete_user_data()
                else:
                    logger.info(
                        f"User data preserved at:\n"
                        f"  Input: {self.paths.input / name}\n"
                        f"  Output: {self.paths.output / name}\n"
                        f"Use --delete-data flag to remove"
                    )
        except Exception as e:
            logger.warning(f"Could not check user data: {e}")

        # Delete using shared utility with platform-specific handling
        remove_environment_directory(env_path)
        logger.info(f"Deleted environment '{name}'")

    def get_active_environment(self, progress=None) -> Environment | None:
        """Get the currently active environment.

        Args:
            progress: Optional progress callback for model sync (ModelScanProgress protocol)

        Returns:
            Environment instance if found, None if no active environment

        Raises:
            PermissionError: If workspace metadata cannot be read
            json.JSONDecodeError: If workspace metadata is corrupted
            OSError: If workspace metadata cannot be read
        """
        try:
            with open(self.paths.workspace_file, encoding='utf-8') as f:
                metadata = json.load(f)
                active_name = metadata.get("active_environment")

            if active_name:
                try:
                    return self.get_environment(active_name, progress=progress)
                except CDEnvironmentNotFoundError:
                    # Active environment was deleted - clear it
                    logger.warning(f"Active environment '{active_name}' no longer exists")
                    return None
            return None

        except PermissionError as e:
            raise PermissionError("Cannot read workspace metadata: insufficient permissions") from e
        except json.JSONDecodeError as e:
            raise CDWorkspaceError(f"Corrupted workspace metadata: {e}") from e
        except OSError as e:
            raise OSError(f"Failed to read workspace metadata: {e}") from e

    def set_active_environment(self, name: str | None, progress=None):
        """Set the active environment.

        Args:
            name: Environment name or None to clear
            progress: Optional progress callback for model sync (ModelScanProgress protocol)

        Raises:
            CDEnvironmentNotFoundError: If environment not found
            PermissionError: If setting active environment fails due to permissions
            OSError: If setting active environment fails for other reasons
        """
        # Validate environment exists if name provided
        if name is not None:
            try:
                self.get_environment(name, progress=progress)
            except CDEnvironmentNotFoundError:
                env_names = [e.name for e in self.list_environments()]
                raise CDEnvironmentNotFoundError(
                    f"Environment '{name}' not found. Available environments: {', '.join(env_names)}"
                ) from None

        try:
            # Read existing metadata
            metadata = {}
            if self.paths.workspace_file.exists():
                with open(self.paths.workspace_file, encoding='utf-8') as f:
                    metadata = json.load(f)

            # Update active environment
            metadata["active_environment"] = name

            # Write back
            with open(self.paths.workspace_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)

        except PermissionError as e:
            raise PermissionError("Cannot set active environment: insufficient permissions") from e
        except OSError as e:
            raise OSError(f"Failed to set active environment: {e}") from e

    # === Model Management ===

    def list_models(self) -> list[ModelWithLocation]:
        """List models in workspace index.

        Args:
            model_type: Optional filter by model type

        Returns:
            List of ModelWithLocation objects
        """
        return self.model_repository.get_all_models()

    def search_models(self, query: str) -> list[ModelWithLocation]:
        """Search models by hash prefix or filename.

        Args:
            query: Search query (hash prefix or filename)

        Returns:
            List of matching ModelWithLocation objects
        """
        # Try hash search first if it looks like a hash
        if len(query) >= 6 and all(c in '0123456789abcdef' for c in query.lower()):
            hash_results = self.model_repository.find_model_by_hash(query.lower())
            if hash_results:
                return hash_results

        # Fall back to filename search
        return self.model_repository.find_by_filename(query)

    def get_model_details(self, identifier: str) -> "ModelDetails":
        """Get complete model information by identifier.

        Args:
            identifier: Model hash, hash prefix, filename, or path

        Returns:
            ModelDetails with model, all locations, and sources

        Raises:
            ValueError: Multiple matches found (ambiguous identifier)
            KeyError: No model found matching identifier
        """
        results = self.search_models(identifier)

        if not results:
            raise KeyError(f"No model found matching: {identifier}")

        # Check if all results are the same model (same hash, different locations)
        unique_hashes = {r.hash for r in results}
        if len(unique_hashes) > 1:
            # Multiple different models match - ambiguous
            raise ValueError(f"Multiple models found matching '{identifier}': {len(unique_hashes)} different models")

        # Same model, possibly multiple locations - use any result to get the model info
        model = results[0]
        sources = self.model_repository.get_sources(model.hash)
        locations = self.model_repository.get_locations(model.hash)

        return ModelDetails(
            model=model,
            all_locations=locations,
            sources=sources
        )

    def get_model_stats(self):
        """Get model index statistics for current directory.

        Returns:
            Dictionary with model statistics
        """
        return self.model_repository.get_stats()

    # === Model Directory Management ===

    def set_models_directory(self, path: Path, progress=None) -> Path:
        """Set the global model directory and update index.

        When switching directories, this method:
        1. Scans the new directory for models
        2. Preserves model metadata (hashes, sources) for all known models
        3. Updates location records to reflect the new directory

        Model records without current locations are kept to preserve their
        metadata (hashes, sources). This enables fast directory switching
        without re-hashing or losing download sources.

        Args:
            path: Path to model directory
            progress: Optional progress callback (ModelScanProgress protocol)

        Returns:
            Path to added directory

        Raises:
            ComfyDockError: If directory doesn't exist or is already tracked
        """
        if not path.exists() or not path.is_dir():
            raise ComfyDockError(f"Directory does not exist: {path}")

        path = path.resolve()

        # Update config to point to new directory
        self.workspace_config_manager.set_models_directory(path)

        # Set repository's current directory for query filtering
        self.model_repository.set_current_directory(path)

        # Scan new directory (updates locations for existing models, adds new ones)
        # clean_stale_locations() removes locations not in the new directory
        result = self.model_scanner.scan_directory(path, progress=progress)

        logger.info(
            f"Set models directory to {path}: "
            f"{result.added_count} new models, {result.updated_count} updated"
        )

        # Update paths in all environments for the newly indexed models
        self._update_all_environment_paths()

        return path

    def get_models_directory(self) -> Path:
        """Get path to tracked model directory."""
        return self.workspace_config_manager.get_models_directory()

    def sync_model_directory(self, progress=None) -> int:
        """Sync tracked model directories.

        Args:
            progress: Optional progress callback (ModelScanProgress protocol)

        Returns:
            Number of changes
        """
        logger.info("Syncing models directory...")
        results = 0
        path = self.workspace_config_manager.get_models_directory()

        # Ensure repository filters by current directory
        self.model_repository.set_current_directory(path)

        logger.debug(f"Tracked directory: {path}")
        if path.exists():
            result = self.model_scanner.scan_directory(path, quiet=True, progress=progress)
            logger.debug(f"Found {result.added_count} new, {result.updated_count} updated models")

            # Calculate total changes (including removals)
            total_changes = result.added_count + result.updated_count + result.removed_count
            results = total_changes

            # Only update timestamp if actual changes occurred
            if total_changes > 0:
                self.workspace_config_manager.update_models_sync_time()
                logger.info(f"Sync complete: {total_changes} changes ({result.added_count} added, {result.updated_count} updated, {result.removed_count} removed)")
            else:
                logger.debug("Model index scan complete: no changes detected")
        else:
            logger.warning(f"Tracked directory no longer exists: {path}")

        # After syncing the model index, update paths in all environments
        self._update_all_environment_paths()

        return results

    def _update_all_environment_paths(self) -> None:
        """Update model paths in all environments after model sync."""
        try:
            environments = self.list_environments()
            if not environments:
                return

            # Count environments that need updating
            total_updated = 0
            total_unchanged = 0

            for env in environments:
                try:
                    stats = env.sync_model_paths()
                    if stats:
                        if stats.get("status") == "updated":
                            total_updated += 1
                            changes = stats.get("changes", {})
                            if changes.get("added") or changes.get("removed"):
                                # Detailed changes are already logged by ModelPathManager
                                pass
                        else:
                            total_unchanged += 1
                except Exception as e:
                    logger.warning(f"Failed to update model paths for environment '{env.name}': {e}")
                    # Continue with other environments

            # Summary logging
            if total_updated > 0:
                logger.info(f"Model paths updated: {total_updated} environment(s) modified, {total_unchanged} unchanged")
            else:
                logger.debug(f"Model paths already in sync for all {len(environments)} environment(s)")

        except Exception as e:
            logger.warning(f"Failed to update environment model paths: {e}")
            # Non-fatal - model sync still succeeded
