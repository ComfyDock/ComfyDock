"""Typed provider credential contracts exposed by ComfyGit Core."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class CredentialProvider(str, Enum):
    CIVITAI = "civitai"
    HUGGINGFACE = "huggingface"
    GITHUB = "github"


class CredentialSource(str, Enum):
    ENVIRONMENT = "environment"
    SECURE_STORE = "secure_store"
    PROVIDER_NATIVE = "provider_native"
    LEGACY_PLAINTEXT = "legacy_plaintext"
    UNAVAILABLE = "unavailable"
    NONE = "none"


class CredentialStore(Protocol):
    """Persistence boundary for workspace-scoped provider credentials."""

    def get(self, workspace_id: str, provider: CredentialProvider) -> str | None: ...

    def set(self, workspace_id: str, provider: CredentialProvider, value: str) -> None: ...

    def delete(self, workspace_id: str, provider: CredentialProvider) -> None: ...


@dataclass(frozen=True)
class CredentialStatus:
    provider: CredentialProvider
    configured: bool
    source: CredentialSource
    storage_available: bool = True
    migration_required: bool = False
    message: str | None = None


@dataclass(frozen=True)
class CredentialMigrationResult:
    migrated: tuple[CredentialProvider, ...] = ()
    retained: tuple[CredentialProvider, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.retained and not self.errors


@dataclass
class MemoryCredentialStore:
    """In-memory credential store for tests and explicitly ephemeral adapters."""

    values: dict[tuple[str, CredentialProvider], str] = field(default_factory=dict)

    def get(self, workspace_id: str, provider: CredentialProvider) -> str | None:
        return self.values.get((workspace_id, provider))

    def set(self, workspace_id: str, provider: CredentialProvider, value: str) -> None:
        self.values[(workspace_id, provider)] = value

    def delete(self, workspace_id: str, provider: CredentialProvider) -> None:
        self.values.pop((workspace_id, provider), None)
