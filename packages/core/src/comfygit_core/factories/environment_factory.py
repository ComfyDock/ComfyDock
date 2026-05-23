"""Factory for creating new environments."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from comfygit_core.core.environment import Environment

from ..logging.logging_config import get_logger
from ..managers.git_manager import GitManager
from ..models.exceptions import (
    CDEnvironmentExistsError,
)
from ..utils.comfyui_ops import clone_comfyui
from ..utils.environment_cleanup import mark_environment_complete
from ..utils.filesystem import rmtree
from ..utils.requirements import read_comfyui_requirements_with_supplements

if TYPE_CHECKING:
    from comfygit_core.core.workspace import Workspace
    from comfygit_core.models.protocols import EnvironmentCreateProgress

logger = get_logger(__name__)


def _get_manager_install_identifier() -> str:
    from ..constants import MANAGER_GITHUB_URL, MANAGER_NODE_ID

    identifier = MANAGER_NODE_ID
    try:
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as pkg_version

        current_version = pkg_version(MANAGER_NODE_ID)
    except PackageNotFoundError:
        logger.info("Manager version not detected, installing from registry")
        return identifier
    except Exception as exc:
        logger.info(f"Manager version not detected, installing from registry: {exc}")
        return identifier

    if current_version and "dev" not in current_version.lower():
        identifier = f"{MANAGER_GITHUB_URL}@v{current_version}"
        logger.info(f"Detected manager v{current_version}, installing from GitHub")
    else:
        logger.info("Manager version is dev or empty, installing from registry")

    return identifier


class EnvironmentFactory:

    @staticmethod
    def create(
        name: str,
        env_path: Path,
        workspace: Workspace,
        python_version: str = "3.12",
        comfyui_version: str | None = None,
        torch_backend: str = "auto",
        no_manager: bool = False,
        progress: EnvironmentCreateProgress | None = None,
    ) -> Environment:
        """Create a new environment.

        Args:
            name: Environment name
            env_path: Path for the environment directory
            workspace: Parent workspace
            python_version: Python version (e.g., "3.12")
            comfyui_version: ComfyUI version (None for latest)
            torch_backend: PyTorch backend (auto, cpu, cu118, cu121, etc.)
            no_manager: Skip comfygit-manager installation (headless mode)
            progress: Optional progress callback for tracking creation phases

        Returns:
            Fully initialized Environment instance
        """
        if env_path.exists():
            raise CDEnvironmentExistsError(f"Environment path already exists: {env_path}")

        # Helper to emit progress updates
        def _progress(phase: str, description: str, pct: int) -> None:
            if progress:
                progress.on_phase(phase, description, pct)

        def _complete(phase: str, success: bool = True, error: str | None = None) -> None:
            if progress:
                progress.on_phase_complete(phase, success, error)

        # Phase: Initialize structure (0-5%)
        _progress("init_structure", "Creating environment structure", 0)

        # Create structure
        env_path.mkdir(parents=True)
        cec_path = env_path / ".cec"
        cec_path.mkdir()

        # Pin Python version for uv
        python_version_file = cec_path / ".python-version"
        python_version_file.write_text(python_version + "\n")
        logger.debug(f"Created .python-version: {python_version}")

        _complete("init_structure")

        # Phase: Probe PyTorch (5-10%) - Use uv's dry-run to detect backend and versions
        _progress("probe_pytorch", "Detecting PyTorch backend", 5)

        from ..managers.pytorch_backend_manager import PyTorchBackendManager

        pytorch_manager = PyTorchBackendManager(cec_path)
        resolved_backend = pytorch_manager.probe_and_set_backend(python_version, torch_backend)

        if torch_backend == "auto":
            logger.info(f"PyTorch backend: auto-detected as {resolved_backend}")
        else:
            logger.info(f"PyTorch backend: {resolved_backend}")

        _complete("probe_pytorch")

        # Initialize environment with resolved backend
        env = Environment(
            name=name,
            path=env_path,
            workspace=workspace,
            torch_backend=resolved_backend,
        )

        # Phase: Resolve ComfyUI version (10-15%)
        _progress("resolve_version", "Resolving ComfyUI version", 10)

        from ..caching.comfyui_cache import ComfyUICacheManager, ComfyUISpec
        from ..clients.github_client import GitHubClient
        from ..utils.comfyui_ops import resolve_comfyui_version
        from ..utils.git import git_rev_parse

        github_client = GitHubClient(
            token_provider=workspace.workspace_config_manager.get_github_token,
        )

        version_to_clone, version_type, _ = resolve_comfyui_version(
            comfyui_version,
            github_client
        )

        _complete("resolve_version")

        # Phase: Clone or restore ComfyUI (15-30%)
        comfyui_cache = ComfyUICacheManager(cache_base_path=workspace.paths.cache)
        spec = ComfyUISpec(
            version=version_to_clone,
            version_type=version_type,
            commit_sha=None  # Will be set after cloning
        )

        cached_path = comfyui_cache.get_cached_comfyui(spec)

        if cached_path:
            # Restore from cache
            _progress("restore_comfyui", f"Restoring ComfyUI {version_to_clone} from cache", 15)
            logger.info(f"Restoring ComfyUI {version_type} {version_to_clone} from cache...")
            shutil.copytree(cached_path, env.comfyui_path)
            commit_sha = git_rev_parse(env.comfyui_path, "HEAD")
            sha_display = f" ({commit_sha[:7]})" if commit_sha else ""
            logger.info(f"Restored ComfyUI from cache{sha_display}")
            _complete("restore_comfyui")
        else:
            # Clone fresh
            _progress("clone_comfyui", f"Cloning ComfyUI {version_to_clone}", 15)
            logger.info(f"Cloning ComfyUI {version_type} {version_to_clone}...")
            try:
                comfyui_version_output = clone_comfyui(env.comfyui_path, version_to_clone)
                if comfyui_version_output:
                    logger.info(f"Successfully cloned ComfyUI version: {comfyui_version_output}")
                else:
                    logger.warning("ComfyUI clone failed")
                    raise RuntimeError("ComfyUI clone failed")
            except Exception as e:
                logger.warning(f"ComfyUI clone failed: {e}")
                _complete("clone_comfyui", False, str(e))
                raise e

            # Get actual commit SHA and cache it
            commit_sha = git_rev_parse(env.comfyui_path, "HEAD")
            if commit_sha:
                spec.commit_sha = commit_sha
                comfyui_cache.cache_comfyui(spec, env.comfyui_path)
                logger.info(f"Cached ComfyUI {version_type} {version_to_clone} ({commit_sha[:7]})")
            else:
                logger.warning(f"Could not determine commit SHA for ComfyUI {version_type} {version_to_clone}")
            _complete("clone_comfyui")

        # Phase: Configure environment (30-40%)
        _progress("configure_environment", "Configuring environment", 30)

        # Extract builtin nodes from ComfyUI installation
        from ..utils.builtin_extractor import extract_comfyui_builtins

        try:
            builtins_path = env.cec_path / "comfyui_builtins.json"
            extract_comfyui_builtins(env.comfyui_path, builtins_path)
            logger.info(f"Extracted builtin nodes to {builtins_path.name}")
        except Exception as e:
            logger.warning(f"Failed to extract builtin nodes: {e}")
            logger.warning("Workflow resolution will fall back to global static config")

        # Extract folder paths from ComfyUI installation
        from ..utils.folder_paths_extractor import extract_folder_paths

        try:
            folder_paths_json = env.cec_path / "comfyui_folder_paths.json"
            extract_folder_paths(env.comfyui_path, folder_paths_json)
            logger.info(f"Extracted folder paths to {folder_paths_json.name}")
        except Exception as e:
            logger.warning(f"Failed to extract folder paths: {e}")
            logger.warning("Model category validation will fall back to static config")

        # Extract model loader widget metadata from ComfyUI installation
        from ..utils.model_loader_extractor import extract_comfyui_model_loaders

        try:
            model_loaders_json = env.cec_path / "comfyui_model_loaders.json"
            extract_comfyui_model_loaders(env.comfyui_path, model_loaders_json)
            logger.info(f"Extracted model loaders to {model_loaders_json.name}")
        except Exception as e:
            logger.warning(f"Failed to extract model loader metadata: {e}")
            logger.warning("Model loader detection will fall back to static config")

        # Remove ComfyUI's default models directory (will be replaced with symlink)
        models_dir = env.comfyui_path / "models"
        if models_dir.exists() and not models_dir.is_symlink():
            rmtree(models_dir)
            logger.debug("Removed ComfyUI's default models directory")

        # Remove ComfyUI's default input/output directories (will be replaced with symlinks)
        from ..utils.symlink_utils import is_link

        input_dir = env.comfyui_path / "input"
        if input_dir.exists() and not is_link(input_dir):
            rmtree(input_dir)
            logger.debug("Removed ComfyUI's default input directory")

        output_dir = env.comfyui_path / "output"
        if output_dir.exists() and not is_link(output_dir):
            rmtree(output_dir)
            logger.debug("Removed ComfyUI's default output directory")

        # Create workspace directories and symlinks for user content
        env.user_content_manager.create_directories()
        env.user_content_manager.create_symlinks()
        logger.debug("Created user content symlinks")

        # Create default ComfyUI user settings (skip templates panel on first launch)
        user_settings_dir = env.comfyui_path / "user" / "default"
        user_settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file = user_settings_dir / "comfy.settings.json"
        settings_file.write_text('{"Comfy.TutorialCompleted": true}')
        logger.debug("Created default user settings (skip templates panel)")

        _complete("configure_environment")

        # Create initial pyproject.toml (torch_backend stored in .pytorch-backend file, not here)
        config = EnvironmentFactory._create_initial_pyproject(
            name,
            python_version,
            version_to_clone,
            version_type,
            commit_sha,
        )
        env.pyproject.save(config)

        # Create package configuration (git-tracked)
        from ..configs.package_config import PackageConfigManager
        pkg_config = PackageConfigManager(cec_path)
        pkg_config.ensure_exists()
        logger.info("Created package configuration")

        # Sync package exclusions from package_config.toml to pyproject.toml
        # This ensures exclude-dependencies is set before first uv sync
        env.pyproject.uv_config.set_exclude_dependencies(pkg_config.exclude_packages)

        # Add ComfyUI requirements
        comfyui_reqs = env.comfyui_path / "requirements.txt"
        if comfyui_reqs.exists():
            logger.info("Adding ComfyUI requirements...")
            requirements = read_comfyui_requirements_with_supplements(comfyui_reqs)
            env.uv_manager.add_requirements_with_sources(requirements, frozen=True)

        # Phase: Install dependencies with PyTorch (40-90%)
        # Single sync handles both PyTorch installation AND ComfyUI dependencies
        _progress("install_dependencies", "Installing PyTorch and dependencies", 40)
        logger.info(f"Installing dependencies with PyTorch backend: {resolved_backend}")

        extras, all_extras = env.pyproject.resolve_sync_extras(None, False)
        env.uv_manager.sync_project(
            verbose=True,
            pytorch_manager=env.pytorch_manager,
            all_groups=True,
            skip_optional_overlays=True,
            extras=extras,
            all_extras=all_extras,
        )

        _complete("install_dependencies")

        # Phase: Install comfygit-manager as tracked node (85%)
        if not no_manager:
            _progress("install_manager", "Installing comfygit-manager", 85)
            try:
                from ..constants import MANAGER_NODE_ID
                logger.info(f"Installing {MANAGER_NODE_ID} as tracked node...")
                identifier = _get_manager_install_identifier()
                env.node_manager.add_node(identifier)
                logger.info(f"{MANAGER_NODE_ID} installed successfully")

                # Upgrade workspace schema if this is a legacy workspace
                # (new envs with per-env manager = modern workspace)
                if workspace.upgrade_schema_if_needed():
                    logger.info("Upgraded workspace to schema v2 (per-environment manager)")
            except Exception as e:
                # Manager installation failure is non-fatal - environment still works
                logger.warning(f"Could not install {MANAGER_NODE_ID}: {e}")
                logger.warning("Environment will work but manager panel will be unavailable")
        else:
            _progress("install_manager", "Skipping comfygit-manager (headless mode)", 85)
            logger.info("Manager installation skipped (--no-manager)")
        _complete("install_manager")

        if no_manager:
            config = env.pyproject.load()
            config.setdefault("tool", {}).setdefault("comfygit", {})["headless"] = True
            env.pyproject.save(config)

        # Phase: Finalize environment (90-100%)
        _progress("finalize", "Finalizing environment", 90)

        # Use GitManager for repository initialization
        git_mgr = GitManager(cec_path)
        git_mgr.initialize_environment_repo("Initial environment setup")

        # Create model symlink (should succeed now that models/ is removed)
        try:
            env.model_symlink_manager.create_symlink()
            logger.info("Model directory linked successfully")
        except Exception as e:
            logger.error(f"Failed to create model symlink: {e}")
            _complete("finalize", False, str(e))
            raise  # FATAL - environment won't work without models

        # Mark environment as fully initialized
        mark_environment_complete(cec_path)

        _complete("finalize")
        _progress("complete", "Environment created successfully", 100)

        logger.info(f"Environment '{name}' created successfully")
        return env

    @staticmethod
    def import_from_bundle(
        tarball_path: Path,
        name: str,
        env_path: Path,
        workspace: Workspace,
        torch_backend: str = "auto",
    ) -> Environment:
        """Create environment structure from tarball (extraction only).

        This creates the environment directory and extracts the .cec contents.
        The environment is NOT fully initialized - caller must call
        env.finalize_import() to complete setup.

        Args:
            tarball_path: Path to .tar.gz bundle
            name: Environment name
            env_path: Target environment directory
            workspace: Workspace instance
            torch_backend: PyTorch backend (auto, cpu, cu118, cu121, etc.)

        Returns:
            Environment instance with .cec extracted but not fully initialized

        Raises:
            CDEnvironmentExistsError: If env_path already exists
        """
        if env_path.exists():
            raise CDEnvironmentExistsError(f"Environment path already exists: {env_path}")

        logger.info(f"Creating environment structure from bundle: {tarball_path}")

        # Log torch backend selection
        if torch_backend == "auto":
            logger.info("PyTorch backend: auto (will detect GPU)")
        else:
            logger.info(f"PyTorch backend: {torch_backend}")

        # Create environment directory structure
        env_path.mkdir(parents=True, exist_ok=True)
        cec_path = env_path / ".cec"

        # Extract tarball to .cec
        from ..managers.export_import_manager import ExportImportManager
        manager = ExportImportManager(cec_path, env_path / "ComfyUI")
        manager.extract_import(tarball_path, cec_path)

        # Create and return Environment instance
        # NOTE: ComfyUI is not cloned yet, workflows not copied, models not resolved
        return Environment(
            name=name,
            path=env_path,
            workspace=workspace,
            torch_backend=torch_backend,
        )

    @staticmethod
    def import_from_git(
        git_url: str,
        name: str,
        env_path: Path,
        workspace: Workspace,
        branch: str | None = None,
        torch_backend: str = "auto",
    ) -> Environment:
        """Create environment structure from git repository (clone only).

        This clones the git repository to .cec directory.
        The environment is NOT fully initialized - caller must call
        env.finalize_import() to complete setup.

        Args:
            git_url: Git repository URL
            name: Environment name
            env_path: Target environment directory
            workspace: Workspace instance
            branch: Optional branch/tag/commit to checkout
            torch_backend: PyTorch backend (auto, cpu, cu118, cu121, etc.)

        Returns:
            Environment instance with .cec cloned but not fully initialized

        Raises:
            CDEnvironmentExistsError: If env_path already exists
            ValueError: If git clone fails
        """
        if env_path.exists():
            raise CDEnvironmentExistsError(f"Environment path already exists: {env_path}")

        logger.info(f"Creating environment structure from git: {git_url}")

        # Log torch backend selection
        if torch_backend == "auto":
            logger.info("PyTorch backend: auto (will detect GPU)")
        else:
            logger.info(f"PyTorch backend: {torch_backend}")

        # Create environment directory structure
        env_path.mkdir(parents=True, exist_ok=True)
        cec_path = env_path / ".cec"

        # Parse URL for subdirectory specification
        from ..utils.git import git_clone, git_clone_subdirectory, parse_git_url_with_subdir

        base_url, subdir = parse_git_url_with_subdir(git_url)
        git_token = workspace.workspace_config_manager.get_github_token()

        # Clone repository to .cec (with subdirectory extraction if specified)
        if subdir:
            logger.info(f"Cloning {base_url} and extracting subdirectory '{subdir}' to {cec_path}")
            git_clone_subdirectory(base_url, cec_path, subdir, ref=branch, token=git_token)
            # Note: git_clone_subdirectory validates pyproject.toml internally

            # Subdirectory imports lose git history, need to init new repo
            from ..utils.git import git_init, git_remote_get_url
            if not (cec_path / ".git").exists():
                logger.info("Initializing git repository for subdirectory import")
                git_init(cec_path)

                # WARNING: Do NOT auto-add remote for subdirectory imports!
                # The base_url points to the parent repo, not a valid push target for this subdirectory.
                # User must manually set up their own remote if they want to push back to a separate repo.
                logger.warning(
                    f"Subdirectory import from {base_url}#{subdir} - no remote configured. "
                    "Set up a remote manually if you want to push changes: cg remote add origin <url>"
                )
        else:
            logger.info(f"Cloning {base_url} to {cec_path}")
            git_clone(base_url, cec_path, ref=branch, token=git_token)

            # Validate it's a ComfyGit environment (only for non-subdir imports)
            pyproject_path = cec_path / "pyproject.toml"
            if not pyproject_path.exists():
                raise ValueError(
                    "Repository does not contain pyproject.toml - not a valid ComfyGit environment"
                )

            # Auto-add the clone URL as 'origin' remote
            # Note: git clone automatically sets up 'origin', but we validate it exists
            from ..utils.git import git_remote_add, git_remote_get_url

            origin_url = git_remote_get_url(cec_path, "origin")
            if not origin_url:
                # Should not happen after git clone, but add as safety
                logger.info(f"Adding 'origin' remote: {base_url}")
                git_remote_add(cec_path, "origin", base_url)
            else:
                logger.info(f"Remote 'origin' already configured: {origin_url}")

        logger.info("Successfully prepared environment from git")

        # Create and return Environment instance
        # NOTE: ComfyUI is not cloned yet, workflows not copied, models not resolved
        return Environment(
            name=name,
            path=env_path,
            workspace=workspace,
            torch_backend=torch_backend,
        )

    @staticmethod
    def import_from_directory(
        source_path: Path,
        name: str,
        env_path: Path,
        workspace: Workspace,
        torch_backend: str = "auto",
    ) -> Environment:
        """Create environment structure from a portable source directory.

        The directory source path represents the portable environment payload,
        not a live ComfyUI runtime directory. Only files that belong to the
        portable manifest are copied into the new environment repo.
        """
        if env_path.exists():
            raise CDEnvironmentExistsError(f"Environment path already exists: {env_path}")

        source_path = source_path.resolve()
        pyproject_path = source_path / "pyproject.toml"
        if not pyproject_path.exists():
            raise ValueError(
                f"Directory does not contain pyproject.toml - not a valid ComfyGit environment: {source_path}"
            )

        logger.info(f"Creating environment structure from directory: {source_path}")

        env_path.mkdir(parents=True, exist_ok=True)
        cec_path = env_path / ".cec"
        cec_path.mkdir(parents=True, exist_ok=True)

        for filename in ("pyproject.toml", ".python-version", "package_config.toml"):
            src = source_path / filename
            if src.exists() and src.is_file():
                shutil.copy2(src, cec_path / filename)

        workflows_src = source_path / "workflows"
        if workflows_src.exists() and workflows_src.is_dir():
            shutil.copytree(workflows_src, cec_path / "workflows", dirs_exist_ok=True)

        workflow_api_src = source_path / "workflow_api"
        if workflow_api_src.exists() and workflow_api_src.is_dir():
            shutil.copytree(workflow_api_src, cec_path / "workflow_api", dirs_exist_ok=True)

        overlays_src = source_path / "overlays"
        if overlays_src.exists() and overlays_src.is_dir():
            overlays_dst = cec_path / "overlays"
            overlays_dst.mkdir(parents=True, exist_ok=True)
            for overlay_file in overlays_src.glob("*.toml"):
                if overlay_file.name == ".local.toml" or overlay_file.name.startswith("."):
                    continue
                shutil.copy2(overlay_file, overlays_dst / overlay_file.name)

        return Environment(
            name=name,
            path=env_path,
            workspace=workspace,
            torch_backend=torch_backend,
        )

    @staticmethod
    def _create_initial_pyproject(
        name: str,
        python_version: str,
        comfyui_version: str,
        comfyui_version_type: str = "branch",
        comfyui_commit_sha: str | None = None,
    ) -> dict:
        """Create the initial pyproject.toml.

        Note: torch_backend is NOT stored in pyproject.toml (schema v2+).
        It's stored in .pytorch-backend file which is gitignored.
        Note: comfygit-manager is installed as a tracked node separately,
        not through dependency-groups.system-nodes (that was legacy schema).
        Note: exclude-dependencies is synced from package_config.toml after creation,
        not hardcoded here.
        """
        from ..constants import PYPROJECT_SCHEMA_VERSION

        # Pin to minor version band (e.g., "3.12" → "==3.12.*")
        # This prevents UV from resolving for other minor versions (e.g., 3.13)
        # which can cause dependency conflicts that don't exist on the actual runtime.
        major_minor = ".".join(python_version.split(".")[:2])

        config = {
            "project": {
                "name": f"comfygit-env-{name}",
                "version": "0.1.0",
                "requires-python": f"=={major_minor}.*",
                "dependencies": []
            },
            "tool": {
                "comfygit": {
                    "schema_version": PYPROJECT_SCHEMA_VERSION,
                    "comfyui_version": comfyui_version,
                    "comfyui_version_type": comfyui_version_type,
                    "comfyui_commit_sha": comfyui_commit_sha,
                    "python_version": python_version,
                    "nodes": {}
                },
                "uv": {
                    "override-dependencies": ["uv>=0.11.8"],
                }
            },
            "dependency-groups": {
                "comfygit-system": ["uv>=0.11.8"],
            },
        }

        return config
