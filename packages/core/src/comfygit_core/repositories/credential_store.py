"""Operating-system-backed credential persistence."""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from ..models.credentials import CredentialProvider
from ..models.exceptions import CDCredentialStoreError

KEYRING_SERVICE = "comfygit"


class KeyringCredentialStore:
    """Store workspace credentials in the active operating-system keyring."""

    @staticmethod
    def _account(workspace_id: str, provider: CredentialProvider) -> str:
        return f"workspace:{workspace_id}:provider:{provider.value}"

    def get(self, workspace_id: str, provider: CredentialProvider) -> str | None:
        try:
            return keyring.get_password(KEYRING_SERVICE, self._account(workspace_id, provider))
        except KeyringError as exc:
            raise CDCredentialStoreError(
                f"Secure credential storage is unavailable for {provider.value}. "
                "Configure an operating-system keyring or use a provider environment variable."
            ) from exc

    def set(self, workspace_id: str, provider: CredentialProvider, value: str) -> None:
        try:
            keyring.set_password(KEYRING_SERVICE, self._account(workspace_id, provider), value)
        except KeyringError as exc:
            raise CDCredentialStoreError(
                f"Could not save the {provider.value} credential in secure storage. "
                "Configure an operating-system keyring or use a provider environment variable."
            ) from exc

    def delete(self, workspace_id: str, provider: CredentialProvider) -> None:
        try:
            keyring.delete_password(KEYRING_SERVICE, self._account(workspace_id, provider))
        except PasswordDeleteError:
            return
        except KeyringError as exc:
            raise CDCredentialStoreError(
                f"Could not clear the {provider.value} credential from secure storage."
            ) from exc
