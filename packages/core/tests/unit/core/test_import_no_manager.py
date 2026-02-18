"""Unit-style coverage for --no-manager import behavior."""

import tarfile
from pathlib import Path

from comfygit_core.core.environment import Environment


def _create_import_tarball(base_dir: Path, pyproject_content: str) -> Path:
    export_content = base_dir / "export_content"
    export_content.mkdir()
    (export_content / "pyproject.toml").write_text(pyproject_content, encoding="utf-8")

    tarball = base_dir / "import_headless.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(export_content / "pyproject.toml", arcname="pyproject.toml")
    return tarball


def test_finalize_import_no_manager_skips_manager_registration(
    test_workspace, tmp_path, mock_comfyui_clone, mock_github_api, mock_pytorch_probe, monkeypatch
):
    """finalize_import(no_manager=True) should not call _register_imported_manager."""
    pyproject_content = """
[project]
name = "comfygit-env-test"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "v0.3.20"
python_version = "3.12"
nodes = {}
"""
    tarball = _create_import_tarball(tmp_path, pyproject_content)

    def _fail_register(self):  # pragma: no cover - assertion path
        raise AssertionError("_register_imported_manager should not be called in headless mode")

    monkeypatch.setattr(Environment, "_register_imported_manager", _fail_register)

    env = test_workspace.import_environment(
        tarball_path=tarball,
        name="import-no-manager",
        model_strategy="skip",
        no_manager=True,
    )

    config = env.pyproject.load()
    assert config["tool"]["comfygit"]["headless"] is True

