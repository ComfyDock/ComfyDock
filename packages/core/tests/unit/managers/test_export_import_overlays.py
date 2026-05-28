"""Tests for overlay handling in export/import workflows."""

import tarfile
from pathlib import Path
from unittest.mock import MagicMock

import tomlkit
from comfygit_core.managers.export_import_manager import ExportImportManager
from comfygit_core.managers.pyproject_manager import PyprojectManager
from comfygit_core.services.import_analyzer import ImportAnalyzer


def _write_pyproject(path: Path) -> None:
    data = {
        "project": {
            "name": "test-env",
            "version": "0.1.0",
            "requires-python": ">=3.11",
            "dependencies": [],
        },
        "tool": {"comfygit": {"nodes": {}, "workflows": {}, "models": {}}},
    }
    with open(path, "w", encoding="utf-8") as f:
        tomlkit.dump(data, f)


def test_export_includes_shared_overlays_only(tmp_path):
    cec_path = tmp_path / ".cec"
    comfyui_path = tmp_path / "ComfyUI"
    cec_path.mkdir()
    comfyui_path.mkdir()
    _write_pyproject(cec_path / "pyproject.toml")
    (cec_path / ".python-version").write_text("3.11\n", encoding="utf-8")

    overlays_dir = cec_path / "overlays"
    overlays_dir.mkdir()
    (overlays_dir / "shared.toml").write_text("[overlay]\n", encoding="utf-8")
    (overlays_dir / ".local.toml").write_text("[overlay]\n", encoding="utf-8")
    (cec_path / ".overlay-config.toml").write_text('active = ["shared"]\n', encoding="utf-8")

    manager = ExportImportManager(cec_path, comfyui_path)
    output = tmp_path / "env.tar.gz"
    manager.create_export(output, PyprojectManager(cec_path / "pyproject.toml"))

    with tarfile.open(output, "r:gz") as tar:
        names = sorted(tar.getnames())

    assert "overlays/shared.toml" in names
    assert "overlays/.local.toml" not in names
    assert ".overlay-config.toml" not in names


def test_import_analyzer_reports_shared_overlays(tmp_path):
    cec_path = tmp_path / ".cec"
    cec_path.mkdir()
    _write_pyproject(cec_path / "pyproject.toml")

    overlays_dir = cec_path / "overlays"
    overlays_dir.mkdir()
    (overlays_dir / "alpha.toml").write_text("[overlay]\n", encoding="utf-8")
    (overlays_dir / ".local.toml").write_text("[overlay]\n", encoding="utf-8")

    model_repo = MagicMock()
    model_repo.get_model.return_value = None
    node_repo = MagicMock()
    analyzer = ImportAnalyzer(model_repo, node_repo)

    analysis = analyzer.analyze_import(cec_path)

    assert analysis.total_overlays == 1
    assert analysis.overlays == ["alpha"]
