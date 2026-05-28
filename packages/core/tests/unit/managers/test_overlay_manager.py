"""Tests for OverlayManager."""

from pathlib import Path

import tomlkit
from comfygit_core.managers.overlay_manager import OverlayManager
from comfygit_core.models.overlay import OverlayConfig


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
    payload = local_overlay.to_uv_payload()
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
        skip_optional=False,
    )
    assert [overlay.name for overlay in collected] == [
        ".local",
        "alpha",
        "beta",
        "gamma",
        ".pytorch",
    ]


def test_collect_overlays_skip_optional_returns_only_pytorch_overlay(tmp_path):
    cec = tmp_path / ".cec"
    overlays = cec / "overlays"
    overlays.mkdir(parents=True)
    _write_pyproject(cec / "pyproject.toml", defaults=["sageattention"])

    _write_overlay(
        overlays / "sageattention.toml",
        """
        [overlay]
        description = "sageattention"
        kind = "shared"
        [dependencies]
        packages = ["sageattention>=2.2.0"]
        """,
    )

    manager = OverlayManager(cec)
    collected = manager.collect_overlays(
        pytorch_config={"sources": {"torch": {"index": "pytorch-cu128"}}},
        skip_optional=True,
    )

    assert [overlay.name for overlay in collected] == [".pytorch"]
    assert all(overlay.kind == "pytorch" for overlay in collected)


def test_collect_overlays_skip_optional_excludes_local_overlay_with_no_kind(tmp_path):
    cec = tmp_path / ".cec"
    overlays = cec / "overlays"
    overlays.mkdir(parents=True)
    _write_pyproject(cec / "pyproject.toml")

    _write_overlay(
        overlays / ".local.toml",
        """
        [overlay]
        description = "local"
        [dependencies]
        packages = ["sageattention>=2.2.0"]
        """,
    )

    manager = OverlayManager(cec)
    collected = manager.collect_overlays(
        pytorch_config={"sources": {"torch": {"index": "pytorch-cu128"}}},
        skip_optional=True,
    )

    assert [overlay.name for overlay in collected] == [".pytorch"]


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


def test_list_overlays_marks_only_dot_local_implicit_active(tmp_path):
    cec = tmp_path / ".cec"
    overlays = cec / "overlays"
    overlays.mkdir(parents=True)
    _write_pyproject(cec / "pyproject.toml")

    _write_overlay(overlays / ".local.toml", "[overlay]\ndescription = 'local'\n")
    _write_overlay(overlays / ".dev.toml", "[overlay]\ndescription = 'dev local'\n")

    manager = OverlayManager(cec)

    listed = {overlay.name: overlay for overlay in manager.list_overlays()}
    assert listed[".local"].is_local is True
    assert listed[".local"].is_active is True
    assert listed[".dev"].is_local is True
    assert listed[".dev"].is_active is False

    manager.set_active_names([".dev"])
    listed_after_activation = {overlay.name: overlay for overlay in manager.list_overlays()}
    assert listed_after_activation[".dev"].is_active is True


def test_bundled_stock_overlays_parse_with_markers(tmp_path):
    cec = tmp_path / ".cec"
    cec.mkdir()
    _write_pyproject(cec / "pyproject.toml")

    manager = OverlayManager(cec)
    stock_dir = manager._stock_overlays_dir

    assert stock_dir.exists()

    sageattention = OverlayConfig.from_toml(stock_dir / "sageattention.toml")
    triton = OverlayConfig.from_toml(stock_dir / "triton.toml")
    xformers = OverlayConfig.from_toml(stock_dir / "xformers.toml")

    assert sageattention.name == "sageattention"
    assert xformers.name == "xformers"
    assert triton.name == "triton"
    assert "triton>=3.0 ; sys_platform == 'linux'" in sageattention.dependencies
    assert "triton-windows>=3.2 ; sys_platform == 'win32'" in triton.dependencies


def test_list_overlays_includes_stock_with_stock_flag(tmp_path):
    cec = tmp_path / ".cec"
    cec.mkdir()
    _write_pyproject(cec / "pyproject.toml")

    manager = OverlayManager(cec)
    listed = {overlay.name: overlay for overlay in manager.list_overlays()}

    assert listed["sageattention"].is_stock is True
    assert listed["sageattention"].is_local is False
    assert listed["xformers"].is_stock is True
    assert listed["triton"].is_stock is True


def test_resolve_and_load_stock_overlay_when_not_present_locally(tmp_path):
    cec = tmp_path / ".cec"
    cec.mkdir()
    _write_pyproject(cec / "pyproject.toml")
    manager = OverlayManager(cec)

    resolved = manager.resolve_overlay_name("SAGEATTENTION")
    assert resolved == "sageattention"

    overlay = manager.load_overlay("triton")
    assert overlay.name == "triton"
    assert "triton>=3.0 ; sys_platform == 'linux'" in overlay.dependencies


def test_env_local_overlay_takes_precedence_over_stock_overlay(tmp_path):
    cec = tmp_path / ".cec"
    overlays = cec / "overlays"
    overlays.mkdir(parents=True)
    _write_pyproject(cec / "pyproject.toml")
    _write_overlay(
        overlays / "triton.toml",
        """
        [overlay]
        description = "local override"
        kind = "shared"

        [dependencies]
        packages = ["triton==9.9.9"]
        """,
    )

    manager = OverlayManager(cec)
    loaded = manager.load_overlay("triton")
    listed = [overlay for overlay in manager.list_overlays() if overlay.name == "triton"]

    assert loaded.description == "local override"
    assert loaded.dependencies == ["triton==9.9.9"]
    assert len(listed) == 1
    assert listed[0].is_stock is False


def test_set_active_names_accepts_stock_overlay(tmp_path):
    cec = tmp_path / ".cec"
    cec.mkdir()
    _write_pyproject(cec / "pyproject.toml")

    manager = OverlayManager(cec)
    manager.set_active_names(["sageattention"])

    assert manager.get_active_names() == ["sageattention"]
