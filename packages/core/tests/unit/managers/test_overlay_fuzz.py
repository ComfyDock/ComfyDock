"""Fuzz and edge-case tests for overlay parsing, collection, and materialization."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import tomlkit
from comfygit_core.managers.overlay_manager import OverlayManager
from comfygit_core.managers.pyproject_manager import PyprojectManager
from comfygit_core.managers.uv_project_manager import UVProjectManager
from comfygit_core.manifest import overlays as manifest_overlays
from comfygit_core.models.overlay import OverlayConfig


def _write_pyproject(path: Path, dependencies: list[str] | None = None) -> None:
    config = {
        "project": {
            "name": "test-env",
            "version": "0.1.0",
            "requires-python": ">=3.11",
            "dependencies": dependencies or [],
        },
        "tool": {
            "comfygit": {
                "python_version": "3.11",
            }
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        tomlkit.dump(config, f)


def _write_overlay(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path


class _FakeUV:
    def __init__(self) -> None:
        self.python_executable = Path("/tmp/fake-python")
        self.binary = "uv"

    def sync(self, **kwargs):
        return SimpleNamespace(stdout="")


def test_overlay_parser_handles_empty_unknown_and_missing_sections(tmp_path):
    empty_path = _write_overlay(
        tmp_path / "empty.toml",
        """
        [overlay]
        description = "empty"
        """,
    )
    empty_overlay = OverlayConfig.from_toml(empty_path)
    assert empty_overlay.is_empty() is True

    unknown_path = _write_overlay(
        tmp_path / "unknown.toml",
        """
        [overlay]
        description = "unknown sections"

        [dependencies]
        packages = ["requests"]

        [unsupported]
        foo = "bar"

        [[unsupported-array]]
        x = 1
        """,
    )
    unknown_overlay = OverlayConfig.from_toml(unknown_path)
    assert unknown_overlay.dependencies == ["requests"]
    assert unknown_overlay.description == "unknown sections"

    missing_overlay_section = _write_overlay(
        tmp_path / "deps-only.toml",
        """
        [dependencies]
        packages = ["xformers"]
        """,
    )
    deps_only_overlay = OverlayConfig.from_toml(missing_overlay_section)
    assert deps_only_overlay.dependencies == ["xformers"]


def test_overlay_parser_handles_empty_lists_unicode_and_long_lists(tmp_path):
    empty_lists = _write_overlay(
        tmp_path / "empty-lists.toml",
        """
        [dependencies]
        packages = []

        [settings]
        no-build-isolation-package = []
        """,
    )
    parsed_empty = OverlayConfig.from_toml(empty_lists)
    assert parsed_empty.is_empty() is True

    unicode_overlay = _write_overlay(
        tmp_path / "unicode.toml",
        """
        [dependencies]
        packages = ["café"]
        """,
    )
    parsed_unicode = OverlayConfig.from_toml(unicode_overlay)
    assert parsed_unicode.dependencies == ["café"]

    long_packages = [f"pkg{i}" for i in range(150)]
    long_overlay = _write_overlay(
        tmp_path / "long.toml",
        "\n".join(
            [
                "[dependencies]",
                "packages = [",
                *[f'  "{name}",' for name in long_packages],
                "]",
            ]
        ),
    )
    parsed_long = OverlayConfig.from_toml(long_overlay)
    assert len(parsed_long.dependencies) == 150


def test_overlay_parser_rejects_malformed_toml(tmp_path):
    bad = _write_overlay(
        tmp_path / "bad.toml",
        """
        [overlay
        description = "missing bracket"
        """,
    )
    with pytest.raises(ValueError, match="Failed to parse overlay TOML"):
        OverlayConfig.from_toml(bad)


def test_duplicate_dependencies_are_deduplicated_during_materialization(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject_path)
    manager = PyprojectManager(pyproject_path)

    overlay = OverlayConfig(
        name="dup",
        path=tmp_path / "dup.toml",
        dependencies=["torch", "torch", "Torch"],
    )

    manager.apply_uv_overlays([overlay])
    materialized = manager.load(force_reload=True)
    deps = [dep for dep in materialized["project"]["dependencies"] if dep.lower() == "torch"]
    assert len(deps) == 1
    assert deps[0].lower() == "torch"


def test_marker_qualified_overlay_replaces_base_dep(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject_path, dependencies=["triton", "numpy>=1.0"])
    manager = PyprojectManager(pyproject_path)

    overlay = OverlayConfig(
        name="marker",
        path=tmp_path / "marker.toml",
        dependencies=["triton>=3.0 ; sys_platform == 'linux'"],
    )

    manager.apply_uv_overlays([overlay])
    materialized = manager.load(force_reload=True)
    deps = materialized["project"]["dependencies"]
    assert "triton>=3.0 ; sys_platform == 'linux'" in deps
    assert "triton" not in deps
    assert "numpy>=1.0" in deps


def test_version_tightening_overlay_replaces_base_dep(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject_path, dependencies=["torch>=2.0"])
    manager = PyprojectManager(pyproject_path)

    overlay = OverlayConfig(
        name="tighten",
        path=tmp_path / "tighten.toml",
        dependencies=["torch==2.1.0"],
    )

    manager.apply_uv_overlays([overlay])
    materialized = manager.load(force_reload=True)
    deps = materialized["project"]["dependencies"]
    assert "torch==2.1.0" in deps
    assert "torch>=2.0" not in deps


def test_extras_overlay_replaces_base_dep(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject_path, dependencies=["torch"])
    manager = PyprojectManager(pyproject_path)

    overlay = OverlayConfig(
        name="extras",
        path=tmp_path / "extras.toml",
        dependencies=["torch[cuda]>=2.1"],
    )

    manager.apply_uv_overlays([overlay])
    materialized = manager.load(force_reload=True)
    deps = materialized["project"]["dependencies"]
    assert "torch[cuda]>=2.1" in deps
    assert "torch" not in deps


def test_multiple_overlays_last_wins(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject_path, dependencies=["triton"])
    manager = PyprojectManager(pyproject_path)

    overlay_one = OverlayConfig(
        name="one",
        path=tmp_path / "one.toml",
        dependencies=["triton>=2.0"],
    )
    overlay_two = OverlayConfig(
        name="two",
        path=tmp_path / "two.toml",
        dependencies=["triton>=3.0 ; sys_platform == 'linux'"],
    )

    manager.apply_uv_overlays([overlay_one, overlay_two])
    materialized = manager.load(force_reload=True)
    deps = materialized["project"]["dependencies"]
    assert "triton>=3.0 ; sys_platform == 'linux'" in deps
    assert "triton>=2.0" not in deps
    assert "triton" not in deps


def test_exact_duplicate_still_deduped(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject_path)
    manager = PyprojectManager(pyproject_path)

    overlay = OverlayConfig(
        name="dup",
        path=tmp_path / "dup.toml",
        dependencies=["torch", "torch", "Torch"],
    )

    manager.apply_uv_overlays([overlay])
    materialized = manager.load(force_reload=True)
    deps = [dep for dep in materialized["project"]["dependencies"] if dep.lower() == "torch"]
    assert len(deps) == 1
    assert deps[0].lower() == "torch"


def test_merge_last_wins_for_sources_indexes_constraints_and_case(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject_path, dependencies=["numpy>=1.0"])
    manager = PyprojectManager(pyproject_path)

    base = manager.load()
    base.setdefault("tool", {})["uv"] = {
        "sources": {"sageattention": {"url": "https://base.example"}},
        "constraint-dependencies": ["sageattention==0.9.0"],
        "index": [{"name": "gpu", "url": "https://gpu.old/simple"}],
    }
    manager.save(base)

    overlay_one = OverlayConfig(
        name="one",
        path=tmp_path / "one.toml",
        sources={"SageAttention": {"url": "https://first.example/simple"}},
        constraints=["SageAttention==1.0.0"],
        indexes=[{"name": "gpu", "url": "https://gpu.first/simple"}],
    )
    overlay_two = OverlayConfig(
        name="two",
        path=tmp_path / "two.toml",
        sources={"sageattention": {"url": "https://second.example/simple"}},
        constraints=["sageattention==2.0.0"],
        indexes=[{"name": "gpu", "url": "https://gpu.second/simple"}],
    )

    manager.apply_uv_overlays([overlay_one, overlay_two])
    materialized = manager.load(force_reload=True)
    uv_config = materialized["tool"]["uv"]

    matching_source_keys = [
        key for key in uv_config["sources"]
        if key.lower().replace("-", "").replace("_", "") == "sageattention"
    ]
    assert len(matching_source_keys) == 1
    assert uv_config["sources"][matching_source_keys[0]]["url"] == "https://second.example/simple"
    assert uv_config["constraint-dependencies"][-1] == "sageattention==2.0.0"
    assert uv_config["index"][-1]["url"] == "https://gpu.second/simple"


def test_empty_overlay_in_merge_chain_has_no_effect(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject_path)
    manager = PyprojectManager(pyproject_path)

    empty_overlay = OverlayConfig(name="empty", path=tmp_path / "empty.toml")
    populated_overlay = OverlayConfig(
        name="populated",
        path=tmp_path / "populated.toml",
        sources={"example": {"url": "https://example.com/simple"}},
    )

    manager.apply_uv_overlays([empty_overlay, populated_overlay])
    materialized = manager.load(force_reload=True)
    assert materialized["tool"]["uv"]["sources"]["example"]["url"] == "https://example.com/simple"


def test_collect_overlays_orders_pytorch_last_and_pytorch_wins(tmp_path):
    cec_path = tmp_path / ".cec"
    overlays_dir = cec_path / "overlays"
    overlays_dir.mkdir(parents=True)
    _write_pyproject(cec_path / "pyproject.toml")
    _write_overlay(overlays_dir / "beta.toml", "[sources]\ntorch = { index = 'custom-beta' }\n")
    _write_overlay(overlays_dir / "alpha.toml", "[sources]\ntorch = { index = 'custom-alpha' }\n")
    _write_overlay(overlays_dir / "gamma.toml", "[constraints]\npackages = ['torch==2.4.0']\n")

    manager = OverlayManager(cec_path)
    manager.set_active_names(["beta", "alpha"])
    overlays = manager.collect_overlays(
        extra_names=["gamma"],
        pytorch_config={
            "sources": {"torch": {"index": "pytorch-cu128"}},
            "constraints": ["torch==2.6.0+cu128"],
            "indexes": [{"name": "pytorch-cu128", "url": "https://download.pytorch.org/whl/cu128"}],
        },
    )

    assert [overlay.name for overlay in overlays] == ["alpha", "beta", "gamma", ".pytorch"]

    pyproject = PyprojectManager(cec_path / "pyproject.toml")
    pyproject.apply_uv_overlays(overlays)
    materialized = pyproject.load(force_reload=True)
    assert materialized["tool"]["uv"]["sources"]["torch"]["index"] == "pytorch-cu128"
    assert materialized["tool"]["uv"]["constraint-dependencies"][-1] == "torch==2.6.0+cu128"


def test_materialization_handles_empty_pyproject_existing_fields_and_strip_without_existing_pytorch(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        """
        [project]
        name = "test-env"
        version = "0.1.0"
        requires-python = ">=3.11"
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    manager = PyprojectManager(pyproject_path)

    overlay = OverlayConfig(
        name="full",
        path=tmp_path / "full.toml",
        dependencies=["requests>=2.0"],
        sources={"requests": {"index": "custom"}},
        settings={"no-build-isolation-package": ["requests"]},
        dependency_metadata=[{"name": "requests", "version": "2.0.0"}],
        constraints=["requests<3"],
        indexes=[{"name": "custom", "url": "https://example.com/simple"}],
    )
    pytorch_overlay = OverlayConfig(
        name=".pytorch",
        path=tmp_path / ".pytorch.toml",
        kind="pytorch",
        sources={"torch": {"index": "pytorch-cu128"}},
        constraints=["torch==2.6.0+cu128"],
        indexes=[{"name": "pytorch-cu128", "url": "https://download.pytorch.org/whl/cu128"}],
        is_local=True,
    )

    manager.apply_uv_overlays([overlay, pytorch_overlay])
    materialized = manager.load(force_reload=True)
    assert "requests>=2.0" in materialized["project"]["dependencies"]
    assert materialized["tool"]["uv"]["sources"]["requests"]["index"] == "custom"
    assert materialized["tool"]["uv"]["sources"]["torch"]["index"] == "pytorch-cu128"
    assert materialized["tool"]["uv"]["no-build-isolation-package"] == ["requests"]
    assert materialized["tool"]["uv"]["dependency-metadata"][0]["name"] == "requests"
    assert any(index["name"] == "custom" for index in materialized["tool"]["uv"]["index"])


def test_materialization_leaves_file_unchanged_when_overlay_application_fails(tmp_path, monkeypatch):
    pyproject_path = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject_path, dependencies=["numpy>=1.0"])
    manager = PyprojectManager(pyproject_path)
    original = pyproject_path.read_text(encoding="utf-8")
    overlay = OverlayConfig(
        name="boom",
        path=tmp_path / "boom.toml",
        dependencies=["requests>=2.0"],
    )

    def fail_apply(*_args, **_kwargs):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(manifest_overlays, "inject_overlay_payload", fail_apply)

    with pytest.raises(RuntimeError, match="forced failure"):
        manager.apply_uv_overlays([overlay])

    assert pyproject_path.read_text(encoding="utf-8") == original


def test_activation_handles_unknown_entries_with_warning_and_preserves_local_precedence(tmp_path, caplog):
    cec_path = tmp_path / ".cec"
    overlays_dir = cec_path / "overlays"
    overlays_dir.mkdir(parents=True)
    _write_pyproject(cec_path / "pyproject.toml")
    _write_overlay(overlays_dir / ".local.toml", "[dependencies]\npackages = ['localpkg']\n")
    _write_overlay(overlays_dir / "shared.toml", "[dependencies]\npackages = ['sharedpkg']\n")
    (cec_path / ".overlay-config.toml").write_text(
        "active = ['missing-overlay', 'shared']\n",
        encoding="utf-8",
    )

    manager = OverlayManager(cec_path)
    caplog.set_level("WARNING")
    collected = manager.collect_overlays()

    assert [overlay.name for overlay in collected] == [".local", "shared"]
    assert any("Skipping unknown overlay 'missing-overlay'" in record.message for record in caplog.records)


def test_activation_config_overrides_defaults(tmp_path):
    cec_path = tmp_path / ".cec"
    overlays_dir = cec_path / "overlays"
    overlays_dir.mkdir(parents=True)
    pyproject = cec_path / "pyproject.toml"
    _write_pyproject(pyproject)

    config = tomlkit.loads(pyproject.read_text(encoding="utf-8"))
    config["tool"]["comfygit"]["overlay-defaults"] = ["alpha"]
    pyproject.write_text(tomlkit.dumps(config), encoding="utf-8")

    _write_overlay(overlays_dir / "alpha.toml", "[dependencies]\npackages = ['alpha']\n")
    _write_overlay(overlays_dir / "beta.toml", "[dependencies]\npackages = ['beta']\n")
    (cec_path / ".overlay-config.toml").write_text("active = ['beta']\n", encoding="utf-8")

    manager = OverlayManager(cec_path)
    assert manager.get_active_names() == ["beta"]
    assert [overlay.name for overlay in manager.collect_overlays()] == ["beta"]


def test_overlay_collection_ignores_unknown_self_reference_fields(tmp_path):
    cec_path = tmp_path / ".cec"
    overlays_dir = cec_path / "overlays"
    overlays_dir.mkdir(parents=True)
    _write_pyproject(cec_path / "pyproject.toml")
    _write_overlay(
        overlays_dir / "loop.toml",
        """
        [overlay]
        extends = "loop"

        [dependencies]
        packages = ["requests>=2.0"]
        """,
    )

    manager = OverlayManager(cec_path)
    overlays = manager.collect_overlays(extra_names=["loop"])
    assert [overlay.name for overlay in overlays] == ["loop"]


def test_cli_overlay_name_validation_errors_surface_from_sync(tmp_path):
    cec_path = tmp_path / ".cec"
    cec_path.mkdir(parents=True)
    _write_pyproject(cec_path / "pyproject.toml")

    pyproject = PyprojectManager(cec_path / "pyproject.toml")
    overlay_manager = OverlayManager(cec_path)
    uv_manager = UVProjectManager(_FakeUV(), pyproject, overlay_manager=overlay_manager)

    with pytest.raises(ValueError, match="Unknown overlay"):
        uv_manager.sync_project(overlay_names=["does-not-exist"])


def test_migration_skips_malformed_legacy_file_with_warning(tmp_path, caplog):
    cec_path = tmp_path / ".cec"
    cec_path.mkdir(parents=True)
    _write_pyproject(cec_path / "pyproject.toml")
    (cec_path / ".local-uv-config").write_text("[sources\nbad = true\n", encoding="utf-8")

    caplog.set_level("WARNING")
    manager = OverlayManager(cec_path)

    assert manager is not None
    assert (cec_path / ".local-uv-config").exists()
    assert not (cec_path / "overlays" / ".local.toml").exists()
    assert any("Skipping .local-uv-config migration due to parse error" in record.message for record in caplog.records)


def test_migration_keeps_existing_local_overlay_when_both_files_exist(tmp_path):
    cec_path = tmp_path / ".cec"
    overlays_dir = cec_path / "overlays"
    overlays_dir.mkdir(parents=True)
    _write_pyproject(cec_path / "pyproject.toml")
    (cec_path / ".local-uv-config").write_text("[sources]\na = { path = '/tmp/a' }\n", encoding="utf-8")
    existing_local = _write_overlay(
        overlays_dir / ".local.toml",
        """
        [sources]
        b = { path = "/tmp/b" }
        """,
    )
    original = existing_local.read_text(encoding="utf-8")

    OverlayManager(cec_path)

    assert not (cec_path / ".local-uv-config").exists()
    assert existing_local.read_text(encoding="utf-8") == original


def test_migration_removes_empty_legacy_file_without_creating_local_overlay(tmp_path):
    cec_path = tmp_path / ".cec"
    cec_path.mkdir(parents=True)
    _write_pyproject(cec_path / "pyproject.toml")
    (cec_path / ".local-uv-config").write_text("", encoding="utf-8")

    OverlayManager(cec_path)

    assert not (cec_path / ".local-uv-config").exists()
    assert not (cec_path / "overlays" / ".local.toml").exists()
