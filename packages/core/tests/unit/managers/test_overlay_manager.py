"""Tests for OverlayManager."""

from pathlib import Path

import tomlkit

from comfygit_core.managers.overlay_manager import OverlayManager


def _write_pyproject(path: Path, defaults: list[str] | None = None) -> None:
    data = {
        "project": {
            "name": "test-env",
            "version": "0.1.0",
            "requires-python": ">=3.11",
            "dependencies": [],
        },
        "tool": {
            "comfygit": {
                "python_version": "3.11",
            }
        },
    }
    if defaults is not None:
        data["tool"]["comfygit"]["overlay-defaults"] = defaults
    with open(path, "w", encoding="utf-8") as f:
        tomlkit.dump(data, f)


def _write_overlay(path: Path, content: str) -> None:
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_migrates_legacy_local_uv_config(tmp_path):
    cec = tmp_path / ".cec"
    cec.mkdir()
    _write_pyproject(cec / "pyproject.toml")

    (cec / ".local-uv-config").write_text(
        """
        constraint-dependencies = ["torch<2.7"]

        [sources]
        sageattention = { path = "/tmp/SageAttention", editable = true }

        [[index]]
        name = "corp"
        url = "https://example.com/simple"
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    manager = OverlayManager(cec)

    assert not (cec / ".local-uv-config").exists()
    assert (cec / "overlays/.local.toml").exists()

    local_overlay = manager.load_overlay(".local")
    payload = local_overlay.to_injection_payload()
    assert payload["sources"]["sageattention"]["path"] == "/tmp/SageAttention"
    assert payload["indexes"][0]["name"] == "corp"
    assert payload["constraints"] == ["torch<2.7"]


def test_collects_overlays_in_expected_order(tmp_path):
    cec = tmp_path / ".cec"
    overlays = cec / "overlays"
    overlays.mkdir(parents=True)
    _write_pyproject(cec / "pyproject.toml", defaults=["beta", "alpha"])

    _write_overlay(
        overlays / ".local.toml",
        """
        [overlay]
        description = "local"
        [sources]
        localpkg = { path = "/tmp/localpkg" }
        """,
    )
    _write_overlay(
        overlays / "alpha.toml",
        """
        [overlay]
        description = "alpha"
        """,
    )
    _write_overlay(
        overlays / "beta.toml",
        """
        [overlay]
        description = "beta"
        """,
    )
    _write_overlay(
        overlays / "gamma.toml",
        """
        [overlay]
        description = "gamma"
        """,
    )

    manager = OverlayManager(cec)

    collected = manager.collect_overlays(
        extra_names=["beta", "gamma"],
        pytorch_config={"sources": {"torch": {"index": "pytorch-cu128"}}},
    )
    assert [overlay.name for overlay in collected] == [
        ".local",
        "alpha",
        "beta",
        "gamma",
        ".pytorch",
    ]


def test_activation_config_overrides_defaults_and_list_marks_active(tmp_path):
    cec = tmp_path / ".cec"
    overlays = cec / "overlays"
    overlays.mkdir(parents=True)
    _write_pyproject(cec / "pyproject.toml", defaults=["alpha"])

    _write_overlay(overlays / "alpha.toml", "[overlay]\ndescription = 'alpha'\n")
    _write_overlay(overlays / "beta.toml", "[overlay]\ndescription = 'beta'\n")

    manager = OverlayManager(cec)
    assert manager.get_active_names() == ["alpha"]

    manager.set_active_names(["beta", "beta"])
    assert manager.get_active_names() == ["beta"]

    listed = manager.list_overlays()
    active_names = [overlay.name for overlay in listed if overlay.is_active]
    assert active_names == ["beta"]


def test_collect_skips_overlay_when_platform_requirements_not_met(tmp_path):
    cec = tmp_path / ".cec"
    overlays = cec / "overlays"
    overlays.mkdir(parents=True)
    _write_pyproject(cec / "pyproject.toml")
    _write_overlay(
        overlays / "gpu-only.toml",
        """
        [overlay]
        requires = ["cuda"]
        """,
    )

    manager = OverlayManager(cec)
    manager._command_exists = lambda command: False  # type: ignore[method-assign]

    collected = manager.collect_overlays(extra_names=["gpu-only"])
    assert collected == []
