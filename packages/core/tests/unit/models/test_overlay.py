"""Tests for overlay TOML model parsing."""

from pathlib import Path

import pytest

from comfygit_core.models.overlay import OverlayConfig


def _write_overlay(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path


def test_overlay_parses_all_supported_fields(tmp_path):
    path = _write_overlay(
        tmp_path,
        "sageattention.toml",
        """
        [overlay]
        description = "SageAttention GPU acceleration"
        kind = "pytorch"
        requires = ["cuda"]

        [dependencies]
        packages = ["sageattention", "torch==2.5.1"]

        [sources]
        sageattention = { git = "https://github.com/thu-ml/SageAttention.git" }

        [settings]
        no-build-isolation-package = ["sageattention", "SAGEATTENTION"]
        override-dependencies = ["triton==3.4.0"]
        environments = ["sys_platform == 'linux'"]

        [[dependency-metadata]]
        name = "sageattention"
        version = "2.1.1"
        requires-dist = ["torch"]

        [constraints]
        packages = ["torch<2.7"]

        [[index]]
        name = "custom"
        url = "https://pypi.example/simple"
        explicit = true
        """,
    )

    overlay = OverlayConfig.from_toml(path)
    payload = overlay.to_injection_payload()

    assert overlay.name == "sageattention"
    assert overlay.is_local is False
    assert overlay.kind == "pytorch"
    assert overlay.requires == ["cuda"]
    assert payload["dependencies"] == ["sageattention", "torch==2.5.1"]
    assert payload["constraints"] == ["torch<2.7"]
    assert payload["sources"]["sageattention"]["git"].startswith("https://")
    assert payload["indexes"][0]["name"] == "custom"
    assert payload["dependency_metadata"][0]["name"] == "sageattention"
    assert payload["no_build_isolation_packages"] == ["sageattention"]
    assert payload["override_dependencies"] == ["triton==3.4.0"]
    assert payload["environments"] == ["sys_platform == 'linux'"]
    assert overlay.is_empty() is False


def test_overlay_parses_minimal_file(tmp_path):
    path = _write_overlay(
        tmp_path,
        ".local.toml",
        """
        [overlay]
        description = "machine local"
        """,
    )

    overlay = OverlayConfig.from_toml(path)

    assert overlay.name == ".local"
    assert overlay.is_local is True
    assert overlay.description == "machine local"
    assert overlay.is_empty() is True


def test_overlay_parses_dependencies_only(tmp_path):
    path = _write_overlay(
        tmp_path,
        "deps.toml",
        """
        [dependencies]
        packages = ["xformers", "triton>=3.0"]
        """,
    )

    overlay = OverlayConfig.from_toml(path)
    payload = overlay.to_injection_payload()

    assert payload["dependencies"] == ["xformers", "triton>=3.0"]
    assert overlay.is_empty() is False


def test_overlay_rejects_malformed_toml(tmp_path):
    path = _write_overlay(
        tmp_path,
        "broken.toml",
        """
        [overlay
        description = "missing bracket"
        """,
    )

    with pytest.raises(ValueError, match="Failed to parse overlay TOML"):
        OverlayConfig.from_toml(path)


def test_overlay_validates_name_kind_and_requires(tmp_path):
    bad_kind = _write_overlay(
        tmp_path,
        "bad-kind.toml",
        """
        [overlay]
        kind = "cuda"
        """,
    )
    with pytest.raises(ValueError, match="Unsupported overlay kind"):
        OverlayConfig.from_toml(bad_kind)

    bad_requires = _write_overlay(
        tmp_path,
        "bad-requires.toml",
        """
        [overlay]
        requires = ["metal"]
        """,
    )
    with pytest.raises(ValueError, match="Unsupported overlay requirement"):
        OverlayConfig.from_toml(bad_requires)

    with pytest.raises(ValueError, match="flat"):
        OverlayConfig.validate_name("group/sageattention")
