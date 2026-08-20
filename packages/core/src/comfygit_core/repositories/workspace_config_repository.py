import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from comfygit_core.models.exceptions import ComfyDockError

from ..logging.logging_config import get_logger
from ..models.credentials import (
    CredentialMigrationResult,
    CredentialProvider,
    CredentialStatus,
    CredentialStore,
)
from ..models.workspace_config import ModelDirectory, WorkspaceConfig
from ..services.credential_service import CredentialService, get_huggingface_native_token
from ..utils.filesystem import harden_private_file
from .credential_store import KeyringCredentialStore

logger = get_logger(__name__)


class WorkspaceConfigRepository:

    _LEGACY_FIELDS = {
        CredentialProvider.CIVITAI: "civitai_token",
        CredentialProvider.HUGGINGFACE: "huggingface_token",
        CredentialProvider.GITHUB: "github_token",
    }

    def __init__(
        self,
        config_file: Path,
        default_models_path: Path | None = None,
        credential_store: CredentialStore | None = None,
    ):
        self.config_file_path = config_file
        self._default_models_path = default_models_path
        harden_private_file(config_file)
        self.credential_service = CredentialService(
            self,
            credential_store or KeyringCredentialStore(),
            native_resolvers={
                CredentialProvider.HUGGINGFACE: get_huggingface_native_token,
            },
        )

    @property
    def config_file(self) -> WorkspaceConfig:
        """Load current metadata without retaining stale secret-bearing state."""
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
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            json.dump(data_dict, f, indent=2)
        harden_private_file(temp_path)
        temp_path.replace(self.config_file_path)  # Atomic on POSIX
        harden_private_file(self.config_file_path)

    def ensure_workspace_id(self) -> str:
        """Return a stable nonsecret identifier used to scope secure credentials."""
        data = self.load()
        if data.workspace_id:
            return data.workspace_id
        data.workspace_id = str(uuid4())
        self.save(data)
        return data.workspace_id

    def get_legacy_credentials(self) -> dict[CredentialProvider, str]:
        """Return plaintext credentials that still require secure migration."""
        credentials = self.load().api_credentials
        if credentials is None:
            return {}
        return {
            provider: value
            for provider, field_name in self._LEGACY_FIELDS.items()
            if (value := getattr(credentials, field_name))
        }

    def get_legacy_credential(self, provider: CredentialProvider) -> str | None:
        return self.get_legacy_credentials().get(provider)

    def clear_legacy_credentials(self, providers: tuple[CredentialProvider, ...]) -> None:
        """Remove verified legacy values from workspace metadata atomically."""
        data = self.load()
        if data.api_credentials is None:
            return
        for provider in providers:
            setattr(data.api_credentials, self._LEGACY_FIELDS[provider], None)
        if not data.api_credentials.to_dict():
            data.api_credentials = None
        self.save(data)

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
        """Set or clear a CivitAI credential in secure storage."""
        if token:
            self.credential_service.set(CredentialProvider.CIVITAI, token)
            logger.info("CivitAI API token configured")
        else:
            self.credential_service.clear(CredentialProvider.CIVITAI)
            logger.info("CivitAI API token cleared")

    def get_civitai_token(self) -> str | None:
        """Resolve a CivitAI credential from environment or secure storage."""
        return self.credential_service.resolve(CredentialProvider.CIVITAI)

    def set_huggingface_token(self, token: str | None):
        """Set or clear a Hugging Face credential in secure storage."""
        if token:
            self.credential_service.set(CredentialProvider.HUGGINGFACE, token)
            logger.info("HuggingFace API token configured")
        else:
            self.credential_service.clear(CredentialProvider.HUGGINGFACE)
            logger.info("HuggingFace API token cleared")

    def get_huggingface_token(self) -> str | None:
        """Resolve Hugging Face auth from environment, secure store, or provider login.

        Priority: environment > workspace secure store > active Hugging Face login.
        """
        return self.credential_service.resolve(CredentialProvider.HUGGINGFACE)

    def set_github_token(self, token: str | None):
        """Set or clear a GitHub credential in secure machine-local storage."""
        if token:
            self.credential_service.set(CredentialProvider.GITHUB, token)
            logger.info("GitHub API token configured")
        else:
            self.credential_service.clear(CredentialProvider.GITHUB)
            logger.info("GitHub API token cleared")

    def get_github_token(self) -> str | None:
        """Resolve GitHub auth from environment or workspace secure storage.

        Standard git credential helpers remain available when no token is returned.
        """
        return self.credential_service.resolve(CredentialProvider.GITHUB)

    def get_credential_status(self, provider: CredentialProvider) -> CredentialStatus:
        return self.credential_service.status(provider)

    def migrate_credentials(self) -> CredentialMigrationResult:
        return self.credential_service.migrate_legacy_credentials()

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
