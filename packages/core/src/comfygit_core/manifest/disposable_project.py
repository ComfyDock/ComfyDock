"""Disposable pyproject materialization for uv sync operations."""
from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..integrations.uv_command import UVCommand
    from ..managers.pyproject_manager import PyprojectManager
    from ..models.overlay import OverlayConfig


class DisposableUvProject:
    """Runs uv against a temporary materialized copy of a manifest project."""

    TEMP_PROJECT_ROOT = ".comfygit-tmp"
    TEMP_PROJECT_PREFIX = "uv-project-"

    def __init__(self, pyproject: PyprojectManager, uv_command: UVCommand):
        self.pyproject = pyproject
        self.uv = uv_command

    @property
    def project_path(self) -> Path:
        return self.pyproject.path.parent

    @property
    def temporary_projects_path(self) -> Path:
        return self.project_path / self.TEMP_PROJECT_ROOT

    def cleanup_stale_temporary_projects(self) -> None:
        temp_root = self.temporary_projects_path
        if not temp_root.exists():
            return

        for child in temp_root.iterdir():
            if child.is_dir() and child.name.startswith(self.TEMP_PROJECT_PREFIX):
                shutil.rmtree(child, ignore_errors=True)

    def copy_project_runtime_inputs(self, target_path: Path) -> None:
        """Copy files uv may need to resolve a disposable project."""
        target_path.mkdir(parents=True, exist_ok=True)

        for filename in (
            "pyproject.toml",
            "uv.lock",
            ".python-version",
            "package_config.toml",
            ".pytorch-backend",
            ".overlay-config.toml",
            ".local-uv-config",
        ):
            source = self.project_path / filename
            if source.exists() and source.is_file():
                shutil.copy2(source, target_path / filename)

        overlays_source = self.project_path / "overlays"
        if overlays_source.exists() and overlays_source.is_dir():
            shutil.copytree(overlays_source, target_path / "overlays", dirs_exist_ok=True)

    def make_project(self) -> tuple[Path, PyprojectManager]:
        self.cleanup_stale_temporary_projects()
        self.temporary_projects_path.mkdir(parents=True, exist_ok=True)
        temp_path = Path(
            tempfile.mkdtemp(
                prefix=self.TEMP_PROJECT_PREFIX,
                dir=self.temporary_projects_path,
            )
        )
        self.copy_project_runtime_inputs(temp_path)
        return temp_path, type(self.pyproject)(temp_path / "pyproject.toml")

    def absolutize_relative_source_paths(self, pyproject: PyprojectManager) -> None:
        """Make relative uv source paths in the temp copy resolve like the real project."""
        config = pyproject.load()
        sources = (
            config.get("tool", {})
            .get("uv", {})
            .get("sources", {})
        )
        if not isinstance(sources, dict):
            return

        changed = False

        def rewrite(source_config: dict) -> None:
            nonlocal changed
            path_value = source_config.get("path")
            if not isinstance(path_value, str):
                return
            path = Path(path_value)
            if path.is_absolute():
                return
            source_config["path"] = str((self.project_path / path).resolve())
            changed = True

        for source_config in sources.values():
            if isinstance(source_config, dict):
                rewrite(source_config)
            elif isinstance(source_config, list):
                for item in source_config:
                    if isinstance(item, dict):
                        rewrite(item)

        if changed:
            pyproject.save(config)

    def copy_runtime_lock_from_disposable_project(self, temp_path: Path) -> None:
        temp_lock = temp_path / "uv.lock"
        if temp_lock.exists():
            shutil.copy2(temp_lock, self.project_path / "uv.lock")

    def sync(
        self,
        overlays: list[OverlayConfig],
        *,
        verbose: bool = False,
        output_callback: Callable[[str], None] | None = None,
        extras: list[str] | None = None,
        all_extras: bool = False,
        **flags,
    ) -> str:
        temp_path, temp_pyproject = self.make_project()
        try:
            temp_pyproject.apply_uv_overlays(overlays)
            self.absolutize_relative_source_paths(temp_pyproject)
            temp_uv = self.uv.for_cwd(temp_path)
            result = temp_uv.sync(
                verbose=verbose,
                output_callback=output_callback,
                extra=extras,
                all_extras=all_extras,
                **flags,
            )
            if not flags.get("dry_run"):
                self.copy_runtime_lock_from_disposable_project(temp_path)
            if flags.get("dry_run"):
                return "\n".join(part for part in (result.stdout, result.stderr) if part)
            return result.stdout
        finally:
            shutil.rmtree(temp_path, ignore_errors=True)
