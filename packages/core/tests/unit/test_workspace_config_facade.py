"""Tests for Workspace configuration facade methods."""

import os
from pathlib import Path

from comfygit_core import Workspace


def test_workspace_token_facades_persist_and_clear_values(monkeypatch, tmp_path):
    for env_name in (
        "CIVITAI_API_TOKEN",
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    ):
        monkeypatch.delenv(env_name, raising=False)

    workspace = Workspace.create(tmp_path / "workspace")

    workspace.set_civitai_token("civitai-token")
    workspace.set_huggingface_token("hf-token")
    workspace.set_github_token("github-token")

    assert workspace.get_civitai_token() == "civitai-token"
    assert workspace.get_huggingface_token() == "hf-token"
    assert workspace.get_github_token() == "github-token"

    workspace.set_civitai_token(None)
    workspace.set_huggingface_token(None)
    workspace.set_github_token(None)

    assert workspace.get_civitai_token() is None
    assert workspace.get_huggingface_token() is None
    assert workspace.get_github_token() is None


def test_workspace_external_uv_cache_facade_persists_and_clears_path(tmp_path):
    workspace = Workspace.create(tmp_path / "workspace")
    cache_path = tmp_path / "uv-cache"

    workspace.set_external_uv_cache(cache_path)

    assert workspace.get_external_uv_cache() == Path(cache_path)

    workspace.set_external_uv_cache(None)

    assert workspace.get_external_uv_cache() is None


def test_workspace_config_file_is_owner_only_when_tokens_are_saved(tmp_path):
    workspace = Workspace.create(tmp_path / "workspace")

    workspace.set_civitai_token("civitai-token")

    if os.name != "nt":
        mode = workspace.paths.workspace_file.stat().st_mode & 0o777
        assert mode == 0o600
