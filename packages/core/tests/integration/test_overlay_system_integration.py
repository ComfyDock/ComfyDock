"""Integration tests for overlay collection and materialization flows."""

from __future__ import annotations

from textwrap import dedent


def _write_overlay(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


def test_collect_overlays_order_is_deterministic(test_env):
    """Overlay collection should follow local -> active(sorted) -> extra -> pytorch."""
    overlays_dir = test_env.cec_path / "overlays"

    _write_overlay(
        overlays_dir / ".local.toml",
        """
        [overlay]
        description = "local"

        [dependencies]
        packages = []
        """,
    )
    _write_overlay(overlays_dir / "beta.toml", "[dependencies]\npackages = []\n")
    _write_overlay(overlays_dir / "alpha.toml", "[dependencies]\npackages = []\n")
    _write_overlay(overlays_dir / "extra.toml", "[dependencies]\npackages = []\n")

    test_env.overlay_manager.set_active_names(["beta", "alpha", "beta"])

    overlays = test_env.overlay_manager.collect_overlays(
        extra_names=["alpha", "extra"],
        pytorch_config={
            "indexes": [
                {"name": "pytorch-cpu", "url": "https://download.pytorch.org/whl/cpu"}
            ]
        },
    )

    assert [overlay.name for overlay in overlays] == [
        ".local",
        "alpha",
        "beta",
        "extra",
        ".pytorch",
    ]


def test_overlay_materialization_applies_fields(test_env):
    """Materialization should apply overlay fields and strip local sources."""
    config = test_env.pyproject.load()
    config.setdefault("tool", {}).setdefault("uv", {})
    config["tool"]["uv"]["sources"] = {
        "editable-local": {"path": "../local-package", "editable": True}
    }
    test_env.pyproject.save(config)

    overlays_dir = test_env.cec_path / "overlays"
    _write_overlay(
        overlays_dir / ".local.toml",
        """
        [overlay]
        description = "full overlay"

        [dependencies]
        packages = ["requests>=2.31"]

        [sources]
        overlay-package = { git = "https://github.com/astral-sh/uv.git" }

        [settings]
        no-build-isolation-package = ["Flash_Attn", "flash-attn"]
        override-dependencies = ["idna<4"]
        environments = ["python_version >= '3.11'"]

        [constraints]
        packages = ["urllib3<3"]

        [[dependency-metadata]]
        name = "overlay-package"
        version = "1.0.0"
        requires-dist = ["requests"]

        [[index]]
        name = "overlay-index"
        url = "https://pypi.org/simple"
        explicit = false
        """,
    )

    overlays = test_env.overlay_manager.collect_overlays()

    test_env.pyproject.apply_uv_overlays(overlays)
    materialized = test_env.pyproject.load(force_reload=True)
    uv_config = materialized["tool"]["uv"]

    assert "requests>=2.31" in materialized["project"]["dependencies"]
    assert "editable-local" not in uv_config["sources"]
    assert "overlay-package" in uv_config["sources"]
    assert "urllib3<3" in uv_config["constraint-dependencies"]
    assert any(index.get("name") == "overlay-index" for index in uv_config["index"])
    assert uv_config["no-build-isolation-package"] == ["Flash_Attn"]
    assert "idna<4" in uv_config["override-dependencies"]
    assert "python_version >= '3.11'" in uv_config["environments"]
    assert any(
        entry.get("name") == "overlay-package"
        for entry in uv_config["dependency-metadata"]
    )
