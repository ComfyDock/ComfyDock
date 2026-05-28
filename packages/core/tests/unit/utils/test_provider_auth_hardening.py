"""Provider auth and logging hardening tests."""

from comfygit_core.utils.provider_urls import is_civitai_url, is_huggingface_url
from comfygit_core.utils.redaction import redact_command, redact_url


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
