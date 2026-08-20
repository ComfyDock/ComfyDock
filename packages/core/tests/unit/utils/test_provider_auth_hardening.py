"""Provider auth and logging hardening tests."""

import os

from comfygit_core.utils.filesystem import harden_private_file
from comfygit_core.utils.provider_urls import is_civitai_url, is_huggingface_url
from comfygit_core.utils.redaction import (
    redact_command,
    redact_sensitive_mapping,
    redact_sensitive_text,
    redact_url,
)


def test_provider_url_detection_uses_hostname_not_url_substrings():
    assert is_civitai_url("https://civitai.com/api/download/models/1")
    assert is_civitai_url("https://www.civitai.com/models/1")
    assert not is_civitai_url("https://example.com/file?next=https://civitai.com/models/1")
    assert not is_civitai_url("https://notcivitai.com/models/1")

    assert is_huggingface_url("https://huggingface.co/user/repo")
    assert is_huggingface_url("https://hf.co/user/repo")
    assert not is_huggingface_url("https://example.com/?repo=huggingface.co/user/repo")


def test_redact_url_masks_sensitive_query_parameters_and_userinfo():
    redacted = redact_url(
        "https://user:secret@example.com/model.safetensors?token=abc&format=SafeTensor"
    )

    assert "secret" not in redacted
    assert "abc" not in redacted
    assert "format=SafeTensor" in redacted
    assert "token=%3Credacted%3E" in redacted


def test_redact_command_masks_common_token_flags():
    assert redact_command(["git", "fetch", "--token", "secret", "--depth", "1"]) == (
        "git fetch --token <redacted> --depth 1"
    )
    assert redact_command(["tool", "--api-key=secret"]) == "tool --api-key=<redacted>"
    assert redact_command(["cg", "config", "--huggingface-token", "secret"]) == (
        "cg config --huggingface-token <redacted>"
    )
    assert redact_command(["cg", "config", "--civitai-key=secret"]) == (
        "cg config --civitai-key=<redacted>"
    )


def test_redact_sensitive_text_masks_prefixed_argument_fields():
    assert redact_sensitive_text("arg_huggingface_token: hf_secret") == (
        "arg_huggingface_token: <redacted>"
    )
    assert redact_sensitive_text("arg_civitai_key=civitai_secret") == (
        "arg_civitai_key=<redacted>"
    )


def test_redact_sensitive_mapping_removes_nested_secret_fields():
    redacted = redact_sensitive_mapping({
        "arg_name": "safe",
        "arg_huggingface_token": "hf_secret",
        "nested": {"authorization": "Bearer secret", "path": "/safe/path"},
    })

    assert redacted == {
        "arg_name": "safe",
        "arg_huggingface_token": "<redacted>",
        "nested": {"authorization": "<redacted>", "path": "/safe/path"},
    }


def test_harden_private_file_sets_owner_only_permissions(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text("{}")
    path.chmod(0o644)

    assert harden_private_file(path)
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
