import json
import os
from datetime import datetime
from functools import cached_property
from pathlib import Path

from comfygit_core.models.exceptions import ComfyDockError

from ..logging.logging_config import get_logger
from ..models.workspace_config import APICredentials, ModelDirectory, WorkspaceConfig

logger = get_logger(__name__)


class WorkspaceConfigRepository:

    def __init__(self, config_file: Path, default_models_path: Path | None = None):
        self.config_file_path = config_file
        self._default_models_path = default_models_path

    @cached_property
    def config_file(self) -> WorkspaceConfig:
        return self._load_or_fail()

    def _load_or_fail(self) -> WorkspaceConfig:
        """Load config from file, raising on any error.

        Unlike the old load() which silently recreated config on errors,
        this method fails loudly to aid debugging.
        """
        if not self.config_file_path.exists():
            raise ComfyDockError(
                f"Workspace config not found: {self.config_file_path}\n"
                f"Run 'cg init' to create a workspace."
            )

        try:
            with self.config_file_path.open("r", encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ComfyDockError(
                f"Failed to load workspace config: invalid JSON at {self.config_file_path}\n"
                f"Error: {e}\n"
                f"The config file may be corrupted. Check the file contents."
            ) from e

        try:
            result = WorkspaceConfig.from_dict(data)
        except (KeyError, TypeError) as e:
            raise ComfyDockError(
                f"Failed to load workspace config: missing or invalid fields\n"
                f"Error: {e}\n"
                f"The config file may be from an incompatible version."
            ) from e

        logger.debug(f"Loaded workspace config: {result}")
        return result

    def load(self) -> WorkspaceConfig:
        """Load config - delegates to _load_or_fail for backwards compatibility."""
        return self._load_or_fail()

    def save(self, data: WorkspaceConfig):
        """Save config atomically (write to temp, then rename)."""
        data_dict = WorkspaceConfig.to_dict(data)
        self.config_file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.config_file_path.with_suffix(".tmp")
        with temp_path.open("w", encoding='utf-8') as f:
            json.dump(data_dict, f, indent=2)
        self._harden_config_file_permissions(temp_path)
        temp_path.replace(self.config_file_path)  # Atomic on POSIX
        self._harden_config_file_permissions(self.config_file_path)

    @staticmethod
    def _harden_config_file_permissions(path: Path) -> None:
        """Best-effort owner-only permissions for local credential config files."""
        if os.name == "nt":
            return
        try:
            path.chmod(0o600)
        except OSError as e:
            logger.debug("Could not harden workspace config permissions for %s: %s", path, e)

    def set_models_directory(self, path: Path):
        logger.info(f"Setting models directory to {path}")
        data = self.config_file
        logger.debug(f"Loaded data: {data}")
        model_dir = ModelDirectory(
            path=str(path),
            added_at=str(datetime.now().isoformat()),
            last_sync=str(datetime.now().isoformat()),
        )
        data.global_model_directory = model_dir
        logger.debug(f"Updated data: {data}, saving...")
        self.save(data)
        logger.info(f"Models directory set to {path}")

    def get_models_directory(self) -> Path:
        """Get path to tracked model directory.

        Returns configured path, or falls back to default workspace models path.
        """
        data = self.config_file
        if data.global_model_directory is not None:
            return Path(data.global_model_directory.path)
        if self._default_models_path is not None:
            return self._default_models_path
        raise ComfyDockError("No models directory set and no default available")

    def update_models_sync_time(self):
        data = self.config_file
        if data.global_model_directory is None:
            raise ComfyDockError("No models directory set")
        data.global_model_directory.last_sync = str(datetime.now().isoformat())
        self.save(data)

    def set_civitai_token(self, token: str | None):
        """Set or clear CivitAI API token."""
        data = self.config_file
        if token:
            if not data.api_credentials:
                data.api_credentials = APICredentials(civitai_token=token)
            else:
                data.api_credentials.civitai_token = token
            logger.info("CivitAI API token configured")
        else:
            if data.api_credentials:
                data.api_credentials.civitai_token = None
            logger.info("CivitAI API token cleared")
        self.save(data)

    def get_civitai_token(self) -> str | None:
        """Get CivitAI API token from config or environment."""
        # Priority: environment variable > config file
        env_token = os.environ.get("CIVITAI_API_TOKEN")
        if env_token:
            logger.debug("Using CivitAI token from environment")
            return env_token

        data = self.config_file
        if data.api_credentials and data.api_credentials.civitai_token:
            logger.debug("Using CivitAI token from config")
            return data.api_credentials.civitai_token

        return None

    def set_huggingface_token(self, token: str | None):
        """Set or clear HuggingFace API token."""
        data = self.config_file
        if token:
            if not data.api_credentials:
                data.api_credentials = APICredentials(huggingface_token=token)
            else:
                data.api_credentials.huggingface_token = token
            logger.info("HuggingFace API token configured")
        else:
            if data.api_credentials:
                data.api_credentials.huggingface_token = None
            logger.info("HuggingFace API token cleared")
        self.save(data)

    def get_huggingface_token(self) -> str | None:
        """Get HuggingFace API token from config or environment.

        Priority: HF_TOKEN env > HUGGING_FACE_HUB_TOKEN env > config file
        """
        # Priority: environment variable > config file
        env_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        if env_token:
            logger.debug("Using HuggingFace token from environment")
            return env_token

        data = self.config_file
        if data.api_credentials and data.api_credentials.huggingface_token:
            logger.debug("Using HuggingFace token from config")
            return data.api_credentials.huggingface_token

        return None

    def set_github_token(self, token: str | None):
        """Set or clear GitHub API token."""
        data = self.config_file
        if token:
            if not data.api_credentials:
                data.api_credentials = APICredentials(github_token=token)
            else:
                data.api_credentials.github_token = token
            logger.info("GitHub API token configured")
        else:
            if data.api_credentials:
                data.api_credentials.github_token = None
            logger.info("GitHub API token cleared")
        self.save(data)

    def get_github_token(self) -> str | None:
        """Get GitHub API token from config or environment.

        Priority: GITHUB_TOKEN env > GH_TOKEN env > config file
        """
        env_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if env_token:
            logger.debug("Using GitHub token from environment")
            return env_token

        data = self.config_file
        if data.api_credentials and data.api_credentials.github_token:
            logger.debug("Using GitHub token from config")
            return data.api_credentials.github_token

        return None

    def get_external_uv_cache(self) -> Path | None:
        """Get external UV cache path if configured."""
        data = self.config_file
        if data.external_uv_cache:
            return Path(data.external_uv_cache)
        return None

    def set_external_uv_cache(self, path: Path | None):
        """Set or clear external UV cache path."""
        data = self.config_file
        if path:
            data.external_uv_cache = str(path.resolve())
            logger.info(f"External UV cache set to: {path}")
        else:
            data.external_uv_cache = None
            logger.info("External UV cache cleared")
        self.save(data)
