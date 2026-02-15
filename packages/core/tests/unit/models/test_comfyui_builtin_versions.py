"""Tests for version-indexed ComfyUI builtin model logic."""

from comfygit_core.models.comfyui_builtin_versions import (
    ComfyUIBuiltinVersions,
    normalize_version_tag,
)


def _build_db() -> ComfyUIBuiltinVersions:
    return ComfyUIBuiltinVersions.from_dict(
        {
            "version": "test",
            "generated_at": "1970-01-01T00:00:00Z",
            "comfyui_versions_processed": [
                "v0.3.0",
                "v0.3.10",
                "v0.3.20",
                "v0.3.30",
                "v0.3.40",
            ],
            "stats": {},
            "builtins": {
                "IntroducedLaterNode": {
                    "introduced_in": "v0.3.20",
                    "category": "core",
                },
                "RemovedNode": {
                    "introduced_in": "v0.3.0",
                    "removed_in": "v0.3.20",
                    "category": "core",
                },
                "NonMonotonicNode": {
                    "introduced_in": "v0.3.0",
                    "present_in": [
                        "v0.3.0-v0.3.10",
                        "v0.3.30+",
                    ],
                    "category": "api",
                },
            },
        }
    )


def test_normalize_version_tag_handles_git_describe():
    assert normalize_version_tag("v0.3.20-7-gabcdef0") == "v0.3.20"
    assert normalize_version_tag("0.3.20") == "v0.3.20"
    assert normalize_version_tag("main") is None


def test_version_gate_info_requires_newer_comfyui():
    db = _build_db()
    info = db.get_version_gate_info("IntroducedLaterNode", "v0.3.10")

    assert info is not None
    assert info.required_version == "v0.3.20"
    assert info.reason == "requires_newer_comfyui"
    assert ">= v0.3.20" in info.message


def test_version_gate_info_for_removed_builtin():
    db = _build_db()
    info = db.get_version_gate_info("RemovedNode", "v0.3.30")

    assert info is not None
    assert info.reason == "removed_builtin"
    assert info.required_version is None
    assert "removed in v0.3.20" in info.message


def test_non_monotonic_present_in_gap_is_version_gated():
    db = _build_db()
    info = db.get_version_gate_info("NonMonotonicNode", "v0.3.20")

    assert info is not None
    assert info.required_version == "v0.3.30"
    assert ">= v0.3.30" in info.message
