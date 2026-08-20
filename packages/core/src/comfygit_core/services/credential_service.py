"""Provider credential resolution and loss-safe legacy migration."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from typing import TYPE_CHECKING

from ..logging.logging_config import get_logger
from ..models.credentials import (
    CredentialMigrationResult,
    CredentialProvider,
    CredentialSource,
    CredentialStatus,
    CredentialStore,
)
from ..models.exceptions import CDCredentialStoreError

if TYPE_CHECKING:
    from ..repositories.workspace_config_repository import WorkspaceConfigRepository

logger = get_logger(__name__)

_PROVIDER_ENVIRONMENT_VARIABLES = {
    CredentialProvider.CIVITAI: ("CIVITAI_API_TOKEN", "CIVITAI_API_KEY"),
    CredentialProvider.HUGGINGFACE: ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"),
    CredentialProvider.GITHUB: ("GITHUB_TOKEN", "GH_TOKEN"),
}


def get_huggingface_native_token() -> str | None:
    """Return the active token managed by ``hf auth login``, when available."""
    try:
        from huggingface_hub import get_token
    except ImportError:
        return None
    return get_token()


class CredentialService:
    """Resolve provider credentials without exposing persistence details to callers."""

    def __init__(
        self,
        config_repository: WorkspaceConfigRepository,
        credential_store: CredentialStore,
        native_resolvers: dict[CredentialProvider, Callable[[], str | None]] | None = None,
    ):
        self.config_repository = config_repository
        self.credential_store = credential_store
        self.native_resolvers = native_resolvers or {}

    def resolve(self, provider: CredentialProvider) -> str | None:
        if value := self._environment_value(provider):
            return value

        self.migrate_legacy_credentials()
        workspace_id = self.config_repository.ensure_workspace_id()
        try:
            if value := self.credential_store.get(workspace_id, provider):
                return value
        except CDCredentialStoreError:
            if value := self.config_repository.get_legacy_credential(provider):
                return value
            return self._native_value(provider)

        if value := self._native_value(provider):
            return value
        return self.config_repository.get_legacy_credential(provider)

    def set(self, provider: CredentialProvider, value: str) -> None:
        workspace_id = self.config_repository.ensure_workspace_id()
        self.credential_store.set(workspace_id, provider, value)
        stored = self.credential_store.get(workspace_id, provider)
        if stored is None or not secrets.compare_digest(value, stored):
            raise CDCredentialStoreError(
                f"Secure storage did not verify the saved {provider.value} credential."
            )
        self.config_repository.clear_legacy_credentials((provider,))

    def clear(self, provider: CredentialProvider) -> None:
        workspace_id = self.config_repository.ensure_workspace_id()
        store_error: CDCredentialStoreError | None = None
        try:
            self.credential_store.delete(workspace_id, provider)
        except CDCredentialStoreError as exc:
            store_error = exc
        self.config_repository.clear_legacy_credentials((provider,))
        if store_error is not None:
            raise store_error

    def status(self, provider: CredentialProvider) -> CredentialStatus:
        if self._environment_value(provider):
            return CredentialStatus(provider, True, CredentialSource.ENVIRONMENT)

        migration = self.migrate_legacy_credentials()
        workspace_id = self.config_repository.ensure_workspace_id()
        try:
            if self.credential_store.get(workspace_id, provider):
                return CredentialStatus(provider, True, CredentialSource.SECURE_STORE)
        except CDCredentialStoreError as exc:
            legacy = self.config_repository.get_legacy_credential(provider)
            if legacy is None:
                native = self._native_value(provider)
                if native is not None:
                    return CredentialStatus(
                        provider=provider,
                        configured=True,
                        source=CredentialSource.PROVIDER_NATIVE,
                        storage_available=False,
                        message=str(exc),
                    )
            return CredentialStatus(
                provider=provider,
                configured=legacy is not None,
                source=(
                    CredentialSource.LEGACY_PLAINTEXT
                    if legacy is not None
                    else CredentialSource.UNAVAILABLE
                ),
                storage_available=False,
                migration_required=legacy is not None,
                message=str(exc),
            )

        if self._native_value(provider):
            return CredentialStatus(provider, True, CredentialSource.PROVIDER_NATIVE)
        if self.config_repository.get_legacy_credential(provider):
            return CredentialStatus(
                provider,
                True,
                CredentialSource.LEGACY_PLAINTEXT,
                migration_required=True,
                message=self._migration_error(provider, migration),
            )
        return CredentialStatus(provider, False, CredentialSource.NONE)

    def migrate_legacy_credentials(self) -> CredentialMigrationResult:
        legacy = self.config_repository.get_legacy_credentials()
        if not legacy:
            return CredentialMigrationResult()

        workspace_id = self.config_repository.ensure_workspace_id()
        stored: list[CredentialProvider] = []
        retained: list[CredentialProvider] = []
        errors: list[str] = []

        for provider, value in legacy.items():
            try:
                self.credential_store.set(workspace_id, provider, value)
                verified = self.credential_store.get(workspace_id, provider)
                if verified is None or not secrets.compare_digest(value, verified):
                    raise CDCredentialStoreError("secure storage read-back verification failed")
                stored.append(provider)
            except CDCredentialStoreError as exc:
                retained.append(provider)
                errors.append(f"{provider.value}: {exc}")

        if stored:
            try:
                self.config_repository.clear_legacy_credentials(tuple(stored))
            except Exception as exc:
                retained.extend(stored)
                errors.append(f"workspace metadata: {exc}")
                stored = []

        return CredentialMigrationResult(
            migrated=tuple(stored),
            retained=tuple(dict.fromkeys(retained)),
            errors=tuple(errors),
        )

    @staticmethod
    def _environment_value(provider: CredentialProvider) -> str | None:
        for name in _PROVIDER_ENVIRONMENT_VARIABLES[provider]:
            if value := os.environ.get(name):
                return value
        return None

    def _native_value(self, provider: CredentialProvider) -> str | None:
        resolver = self.native_resolvers.get(provider)
        if resolver is None:
            return None
        try:
            return resolver()
        except Exception as exc:
            logger.debug("Native %s credential resolution failed: %s", provider.value, exc)
            return None

    @staticmethod
    def _migration_error(
        provider: CredentialProvider,
        result: CredentialMigrationResult,
    ) -> str | None:
        prefix = f"{provider.value}:"
        return next((error for error in result.errors if error.startswith(prefix)), None)
