"""Tests for UV no-build-isolation support."""
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import MagicMock

import tomlkit

from comfygit_core.managers.overlay_manager import OverlayManager
from comfygit_core.managers.pyproject_manager import PyprojectManager
from comfygit_core.managers.uv_project_manager import UVProjectManager


def _make_manager():
    tmpdir = TemporaryDirectory()
    base = Path(tmpdir.name)
    pyproject_path = base / "pyproject.toml"

    config = {
        "project": {
            "name": "test-project",
            "version": "0.1.0",
            "requires-python": ">=3.12",
            "dependencies": [],
        },
        "tool": {
            "comfygit": {
                "python_version": "3.12",
            }
        }
    }
    with open(pyproject_path, "w") as f:
        tomlkit.dump(config, f)

    pyproject = PyprojectManager(pyproject_path)
    uv = MagicMock()
    uv.add.return_value = SimpleNamespace(stdout="ok")

    overlay_manager = OverlayManager(pyproject_path.parent)
    return tmpdir, UVProjectManager(uv, pyproject, overlay_manager=overlay_manager), uv


def test_no_build_isolation_updates_pyproject():
    """Should add package to no-build-isolation-package list."""
    tmpdir, manager, _ = _make_manager()
    try:
        manager.add_dependency(packages=["flash-attn"], no_build_isolation=True)
        config = manager.pyproject.load()
        packages = config.get("tool", {}).get("uv", {}).get("no-build-isolation-package", [])
        assert packages == ["flash-attn"]
    finally:
        tmpdir.cleanup()


def test_no_build_isolation_with_git_url():
    """Should extract package name from git URL."""
    tmpdir, manager, _ = _make_manager()
    try:
        manager.add_dependency(
            packages=["git+https://github.com/thu-ml/SageAttention.git"],
            no_build_isolation=True,
        )
        config = manager.pyproject.load()
        packages = config.get("tool", {}).get("uv", {}).get("no-build-isolation-package", [])
        assert "sageattention" in packages
    finally:
        tmpdir.cleanup()


def test_no_build_isolation_with_group_flag():
    """Should work with --group flag and still update pyproject."""
    tmpdir, manager, uv = _make_manager()
    try:
        manager.add_dependency(
            packages=["deepspeed"],
            group="optional-cuda",
            no_build_isolation=True,
        )
        uv.add.assert_called_once_with(
            packages=["deepspeed"],
            requirements_file=None,
            upgrade=False,
            group="optional-cuda",
            dev=False,
            optional=None,
            editable=False,
            bounds=None,
        )
        config = manager.pyproject.load()
        packages = config.get("tool", {}).get("uv", {}).get("no-build-isolation-package", [])
        assert "deepspeed" in packages
    finally:
        tmpdir.cleanup()
