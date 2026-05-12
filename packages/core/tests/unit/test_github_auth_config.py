"""Tests for GitHub token configuration and lookup."""

import json

from comfygit_core.models.workspace_config import APICredentials, WorkspaceConfig
from comfygit_core.repositories.workspace_config_repository import WorkspaceConfigRepository


def _write_workspace_config(config_file, api_credentials=None):
    config_file.write_text(json.dumps({
        "version": 1,
        "active_environment": "",
        "created_at": "2026-01-01T00:00:00",
        "global_model_directory": None,
        "api_credentials": api_credentials,
    }))


def test_api_credentials_round_trips_github_token():
    config = WorkspaceConfig(
        version=1,
        active_environment="",
        created_at="2026-01-01T00:00:00",
        global_model_directory=None,
        api_credentials=APICredentials(github_token="ghp_test"),
    )

    data = WorkspaceConfig.to_dict(config)
    restored = WorkspaceConfig.from_dict(data)

    assert data["api_credentials"]["github_token"] == "ghp_test"
    assert restored.api_credentials
    assert restored.api_credentials.github_token == "ghp_test"


def test_get_github_token_prefers_environment(monkeypatch, tmp_path):
    config_file = tmp_path / "workspace.json"
    _write_workspace_config(config_file, api_credentials={"github_token": "config-token"})
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")

    repo = WorkspaceConfigRepository(config_file)

    assert repo.get_github_token() == "env-token"


def test_get_github_token_uses_gh_token_fallback(monkeypatch, tmp_path):
    config_file = tmp_path / "workspace.json"
    _write_workspace_config(config_file)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "gh-token")

    repo = WorkspaceConfigRepository(config_file)

    assert repo.get_github_token() == "gh-token"


def test_set_github_token_persists_and_clears(tmp_path):
    config_file = tmp_path / "workspace.json"
    _write_workspace_config(config_file)
    repo = WorkspaceConfigRepository(config_file)

    repo.set_github_token("saved-token")
    assert repo.get_github_token() == "saved-token"

    saved = json.loads(config_file.read_text())
    assert saved["api_credentials"]["github_token"] == "saved-token"

    repo.set_github_token(None)
    assert repo.get_github_token() is None
