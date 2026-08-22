"""Model scanner behavior for shared model-file symlinks."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from comfygit_core.analyzers.model_scanner import ModelScanner


def _make_model(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"safetensors-placeholder")


@pytest.mark.parametrize("target_location", ["inside", "outside"])
def test_find_model_files_includes_valid_file_symlinks(
    tmp_path: Path,
    target_location: str,
) -> None:
    models_dir = tmp_path / "models"
    alias = models_dir / "vae" / "expected-name.safetensors"
    target = (
        models_dir / "shared" / "actual-name.safetensors"
        if target_location == "inside"
        else tmp_path / "external" / "actual-name.safetensors"
    )
    _make_model(target)
    alias.parent.mkdir(parents=True, exist_ok=True)
    alias.symlink_to(target)

    found = ModelScanner(MagicMock())._find_model_files(models_dir)

    assert alias in found


def test_find_model_files_ignores_broken_symlinks(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    alias = models_dir / "vae" / "missing.safetensors"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(tmp_path / "missing-target.safetensors")

    found = ModelScanner(MagicMock())._find_model_files(models_dir)

    assert alias not in found
