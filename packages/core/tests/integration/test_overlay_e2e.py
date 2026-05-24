"""End-to-end integration coverage for the overlay pipeline."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path
from types import SimpleNamespace

from comfygit_cli.env_commands import EnvironmentCommands
from comfygit_core.managers.export_import_manager import ExportImportManager
from comfygit_core.managers.pyproject_manager import PyprojectManager


def _write_overlay(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _capture_disposable_sync(test_env, observe) -> None:
    class _FakeUV:
        python_executable = Path("/tmp/fake-python")
        binary = "uv"

        def for_cwd(self, cwd):
            self.cwd = cwd
            return self

        def sync(self, **kwargs):
            materialized = PyprojectManager(self.cwd / "pyproject.toml").load(force_reload=True)
            observe(materialized)
            return SimpleNamespace(stdout="ok")

    fake_uv = _FakeUV()
    test_env.uv_manager.uv = fake_uv
    test_env.uv_manager.disposable_project.uv = fake_uv


def test_full_sync_cycle_with_shared_overlay_materializes_then_keeps_tracked_manifest_clean(test_env):
    overlay_path = test_env.cec_path / "overlays" / "shared.toml"
    _write_overlay(
        overlay_path,
        """
        [dependencies]
        packages = ["requests>=2.31"]

        [sources]
        requests = { index = "custom" }
        """,
    )
    test_env.overlay_manager.set_active_names(["shared"])

    observed = {}
    original = test_env.pyproject.snapshot()

    def _observe(materialized):
        observed["dependencies"] = list(materialized["project"]["dependencies"])
        observed["request_source"] = materialized["tool"]["uv"]["sources"]["requests"]["index"]

    _capture_disposable_sync(test_env, _observe)

    test_env.uv_manager.sync_project()

    assert "requests>=2.31" in observed["dependencies"]
    assert observed["request_source"] == "custom"
    assert test_env.pyproject.snapshot() == original


def test_full_sync_cycle_with_local_overlay_always_active(test_env):
    local_overlay = test_env.cec_path / "overlays" / ".local.toml"
    _write_overlay(
        local_overlay,
        """
        [dependencies]
        packages = ["localpkg>=1.0"]

        [sources]
        localpkg = { path = "/tmp/localpkg", editable = true }
        """,
    )

    observed = {}
    original = test_env.pyproject.snapshot()

    def _observe(materialized):
        observed["dependencies"] = list(materialized["project"]["dependencies"])
        observed["source_path"] = materialized["tool"]["uv"]["sources"]["localpkg"]["path"]

    _capture_disposable_sync(test_env, _observe)

    test_env.uv_manager.sync_project()

    assert "localpkg>=1.0" in observed["dependencies"]
    assert observed["source_path"] == "/tmp/localpkg"
    assert test_env.pyproject.snapshot() == original


def test_migration_flow_creates_local_overlay_and_materializes(test_env):
    legacy_path = test_env.cec_path / ".local-uv-config"
    legacy_path.write_text(
        """
        constraint-dependencies = ["torch<2.7"]

        [sources]
        sageattention = { path = "/tmp/SageAttention", editable = true }
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    # Trigger migration
    overlays = test_env.overlay_manager.collect_overlays()
    assert overlays
    assert not legacy_path.exists()
    migrated_local = test_env.cec_path / "overlays" / ".local.toml"
    assert migrated_local.exists()

    observed = {}

    def _observe(materialized):
        observed["source_path"] = materialized["tool"]["uv"]["sources"]["sageattention"]["path"]
        observed["constraints"] = list(materialized["tool"]["uv"]["constraint-dependencies"])

    _capture_disposable_sync(test_env, _observe)
    test_env.uv_manager.sync_project()

    assert observed["source_path"] == "/tmp/SageAttention"
    assert "torch<2.7" in observed["constraints"]


def test_export_import_includes_only_shared_overlays(test_env, tmp_path):
    overlays_dir = test_env.cec_path / "overlays"
    _write_overlay(overlays_dir / "shared.toml", "[overlay]\ndescription = 'shared'\n")
    _write_overlay(overlays_dir / ".local.toml", "[overlay]\ndescription = 'local'\n")
    (test_env.cec_path / ".overlay-config.toml").write_text("active = ['shared']\n", encoding="utf-8")

    export_manager = ExportImportManager(test_env.cec_path, test_env.comfyui_path)
    tar_path = tmp_path / "overlay-export.tar.gz"
    export_manager.create_export(tar_path, PyprojectManager(test_env.cec_path / "pyproject.toml"))

    with tarfile.open(tar_path, "r:gz") as tar:
        names = set(tar.getnames())
    assert "overlays/shared.toml" in names
    assert "overlays/.local.toml" not in names
    assert ".overlay-config.toml" not in names

    target_cec = tmp_path / ".cec-imported"
    export_manager.extract_import(tar_path, target_cec)
    assert (target_cec / "overlays" / "shared.toml").exists()
    assert not (target_cec / "overlays" / ".local.toml").exists()


def test_cli_overlay_commands_end_to_end(test_env, monkeypatch, capsys):
    cmd = EnvironmentCommands()
    monkeypatch.setattr(cmd, "_get_env", lambda args: test_env)

    cmd.overlay_create(argparse.Namespace(target_env="test-env", name="cli-shared"))
    created_path = test_env.cec_path / "overlays" / "cli-shared.toml"
    assert created_path.exists()

    cmd.overlay_enable(argparse.Namespace(target_env="test-env", name="cli-shared"))
    activation = test_env.overlay_manager.get_active_names()
    assert "cli-shared" in activation

    cmd.overlay_list(argparse.Namespace(target_env="test-env"))
    listed_output = capsys.readouterr().out
    assert "Available overlays:" in listed_output
    assert "cli-shared (shared, active)" in listed_output

    cmd.overlay_show(argparse.Namespace(target_env="test-env", name="cli-shared"))
    show_output = capsys.readouterr().out
    assert "Overlay: cli-shared (shared)" in show_output
    assert "[overlay]" in show_output

    cmd.overlay_disable(argparse.Namespace(target_env="test-env", name="cli-shared"))
    assert "cli-shared" not in test_env.overlay_manager.get_active_names()


def test_multi_overlay_merge_order_and_pytorch_precedence(test_env):
    overlays_dir = test_env.cec_path / "overlays"
    _write_overlay(
        overlays_dir / "alpha.toml",
        """
        [sources]
        packagex = { url = "https://alpha.example/simple" }
        torch = { index = "alpha-index" }

        [constraints]
        packages = ["packagex==1.0.0"]
        """,
    )
    _write_overlay(
        overlays_dir / "beta.toml",
        """
        [sources]
        packagex = { url = "https://beta.example/simple" }
        torch = { index = "beta-index" }

        [constraints]
        packages = ["packagex==2.0.0"]
        """,
    )
    _write_overlay(
        overlays_dir / "gamma.toml",
        """
        [sources]
        packagex = { url = "https://gamma.example/simple" }
        torch = { index = "gamma-index" }

        [constraints]
        packages = ["packagex==3.0.0"]
        """,
    )

    test_env.overlay_manager.set_active_names(["beta", "alpha"])

    class _FakePyTorchManager:
        def get_pytorch_config(self, backend_override=None, python_version=None):
            return {
                "sources": {"torch": {"index": "pytorch-cu128"}},
                "constraints": ["torch==2.6.0+cu128"],
                "indexes": [
                    {
                        "name": "pytorch-cu128",
                        "url": "https://download.pytorch.org/whl/cu128",
                        "explicit": True,
                    }
                ],
            }

    observed = {}
    original = test_env.pyproject.snapshot()

    def _observe(materialized):
        observed["packagex_source"] = materialized["tool"]["uv"]["sources"]["packagex"]["url"]
        observed["torch_source"] = materialized["tool"]["uv"]["sources"]["torch"]["index"]
        observed["constraints"] = list(materialized["tool"]["uv"]["constraint-dependencies"])

    _capture_disposable_sync(test_env, _observe)

    collected = test_env.overlay_manager.collect_overlays(
        extra_names=["gamma"],
        pytorch_config=_FakePyTorchManager().get_pytorch_config(),
    )
    assert [overlay.name for overlay in collected] == ["alpha", "beta", "gamma", ".pytorch"]

    test_env.uv_manager.sync_project(
        overlay_names=["gamma"],
        pytorch_manager=_FakePyTorchManager(),
    )

    assert observed["packagex_source"] == "https://gamma.example/simple"
    assert observed["torch_source"] == "pytorch-cu128"
    assert observed["constraints"][-2:] == ["packagex==3.0.0", "torch==2.6.0+cu128"]
    assert test_env.pyproject.snapshot() == original
