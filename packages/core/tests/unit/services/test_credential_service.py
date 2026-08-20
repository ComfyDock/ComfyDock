"""Credential resolution and loss-safe migration tests."""

import json

import pytest
from comfygit_core.models import (
    CDCredentialStoreError,
    CredentialProvider,
    CredentialSource,
    MemoryCredentialStore,
)
from comfygit_core.repositories.workspace_config_repository import WorkspaceConfigRepository
from comfygit_core.services.credential_service import get_huggingface_native_token


class UnavailableCredentialStore:
    def get(self, workspace_id, provider):
        raise CDCredentialStoreError("keyring unavailable")

    def set(self, workspace_id, provider, value):
        raise CDCredentialStoreError("keyring unavailable")

    def delete(self, workspace_id, provider):
        raise CDCredentialStoreError("keyring unavailable")


class CorruptingCredentialStore(MemoryCredentialStore):
    def get(self, workspace_id, provider):
        value = super().get(workspace_id, provider)
        return f"{value}-corrupt" if value else None


def test_huggingface_native_resolver_uses_public_hub_token_api(monkeypatch):
    monkeypatch.setattr("huggingface_hub.get_token", lambda: "native-token")

    assert get_huggingface_native_token() == "native-token"


def _write_config(path, credentials=None, workspace_id=None):
    path.write_text(json.dumps({
        "version": 1,
        "active_environment": "",
        "created_at": "2026-01-01T00:00:00",
        "workspace_id": workspace_id,
        "global_model_directory": None,
        "api_credentials": credentials,
        "external_uv_cache": None,
    }))


def test_environment_credentials_override_secure_store(monkeypatch, tmp_path):
    config_file = tmp_path / "workspace.json"
    _write_config(config_file, workspace_id="workspace-1")
    store = MemoryCredentialStore()
    store.set("workspace-1", CredentialProvider.HUGGINGFACE, "stored-token")
    repo = WorkspaceConfigRepository(config_file, credential_store=store)
    monkeypatch.setenv("HF_TOKEN", "environment-token")

    assert repo.get_huggingface_token() == "environment-token"
    assert repo.get_credential_status(CredentialProvider.HUGGINGFACE).source == (
        CredentialSource.ENVIRONMENT
    )


def test_legacy_credentials_migrate_only_after_verified_readback(tmp_path):
    config_file = tmp_path / "workspace.json"
    _write_config(
        config_file,
        credentials={
            "civitai_token": "civitai-secret",
            "huggingface_token": "hf-secret",
        },
    )
    store = MemoryCredentialStore()
    repo = WorkspaceConfigRepository(config_file, credential_store=store)

    result = repo.migrate_credentials()

    assert set(result.migrated) == {
        CredentialProvider.CIVITAI,
        CredentialProvider.HUGGINGFACE,
    }
    assert result.complete
    saved = json.loads(config_file.read_text())
    assert saved["workspace_id"]
    assert saved["api_credentials"] is None
    assert "civitai-secret" not in config_file.read_text()
    assert "hf-secret" not in config_file.read_text()


def test_later_config_writes_cannot_reintroduce_migrated_plaintext(tmp_path):
    config_file = tmp_path / "workspace.json"
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    _write_config(config_file, credentials={"civitai_token": "civitai-secret"})
    repo = WorkspaceConfigRepository(
        config_file,
        default_models_path=models_dir,
        credential_store=MemoryCredentialStore(),
    )
    _ = repo.config_file

    assert repo.migrate_credentials().complete
    repo.set_models_directory(models_dir)

    assert "civitai-secret" not in config_file.read_text()
    assert json.loads(config_file.read_text())["api_credentials"] is None


def test_unavailable_store_retains_plaintext_and_reports_pending_migration(tmp_path):
    config_file = tmp_path / "workspace.json"
    _write_config(config_file, credentials={"huggingface_token": "hf-secret"})
    repo = WorkspaceConfigRepository(
        config_file,
        credential_store=UnavailableCredentialStore(),
    )

    result = repo.migrate_credentials()

    assert result.migrated == ()
    assert result.retained == (CredentialProvider.HUGGINGFACE,)
    assert "hf-secret" in config_file.read_text()
    status = repo.get_credential_status(CredentialProvider.HUGGINGFACE)
    assert status.configured
    assert status.source == CredentialSource.LEGACY_PLAINTEXT
    assert status.migration_required
    assert not status.storage_available


def test_failed_readback_never_removes_legacy_plaintext(tmp_path):
    config_file = tmp_path / "workspace.json"
    _write_config(config_file, credentials={"github_token": "github-secret"})
    repo = WorkspaceConfigRepository(
        config_file,
        credential_store=CorruptingCredentialStore(),
    )

    result = repo.migrate_credentials()

    assert result.migrated == ()
    assert result.retained == (CredentialProvider.GITHUB,)
    assert "github-secret" in config_file.read_text()


def test_new_secure_save_failure_does_not_fall_back_to_plaintext(tmp_path):
    config_file = tmp_path / "workspace.json"
    _write_config(config_file)
    repo = WorkspaceConfigRepository(
        config_file,
        credential_store=UnavailableCredentialStore(),
    )

    with pytest.raises(CDCredentialStoreError, match="keyring unavailable"):
        repo.set_civitai_token("new-secret")

    assert "new-secret" not in config_file.read_text()


def test_clear_removes_legacy_plaintext_even_when_secure_store_is_unavailable(tmp_path):
    config_file = tmp_path / "workspace.json"
    _write_config(config_file, credentials={"civitai_token": "legacy-secret"})
    repo = WorkspaceConfigRepository(
        config_file,
        credential_store=UnavailableCredentialStore(),
    )

    with pytest.raises(CDCredentialStoreError, match="keyring unavailable"):
        repo.set_civitai_token(None)

    assert "legacy-secret" not in config_file.read_text()
    assert json.loads(config_file.read_text())["api_credentials"] is None


def test_provider_native_huggingface_token_is_used_after_workspace_store(tmp_path):
    config_file = tmp_path / "workspace.json"
    _write_config(config_file, workspace_id="workspace-1")
    repo = WorkspaceConfigRepository(config_file, credential_store=MemoryCredentialStore())
    repo.credential_service.native_resolvers[CredentialProvider.HUGGINGFACE] = (
        lambda: "native-hf-token"
    )

    assert repo.get_huggingface_token() == "native-hf-token"
    status = repo.get_credential_status(CredentialProvider.HUGGINGFACE)
    assert status.configured
    assert status.source == CredentialSource.PROVIDER_NATIVE


def test_provider_native_token_still_works_when_keyring_is_unavailable(tmp_path):
    config_file = tmp_path / "workspace.json"
    _write_config(config_file, workspace_id="workspace-1")
    repo = WorkspaceConfigRepository(
        config_file,
        credential_store=UnavailableCredentialStore(),
    )
    repo.credential_service.native_resolvers[CredentialProvider.HUGGINGFACE] = (
        lambda: "native-hf-token"
    )

    assert repo.get_huggingface_token() == "native-hf-token"
    status = repo.get_credential_status(CredentialProvider.HUGGINGFACE)
    assert status.configured
    assert status.source == CredentialSource.PROVIDER_NATIVE
    assert not status.storage_available
