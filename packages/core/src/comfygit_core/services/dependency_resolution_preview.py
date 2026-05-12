"""Preview full-project dependency resolution changes."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import tomlkit
from packaging.utils import canonicalize_name
from packaging.version import parse as parse_version

from ..integrations.uv_command import UVCommand
from ..logging.logging_config import get_logger
from ..managers.overlay_manager import OverlayManager
from ..managers.pyproject_manager import PyprojectManager
from ..managers.pytorch_backend_manager import PyTorchBackendManager
from ..managers.uv_project_manager import UVProjectManager
from ..models.dependency_resolution import (
    DependencyResolutionPreview,
    PackageChangeKind,
    PackageVersionChange,
)
from ..models.exceptions import UVCommandError
from ..models.shared import NodePackage

logger = get_logger(__name__)


class DependencyResolutionPreviewService:
    """Simulate node dependency resolution in a temporary project copy."""

    PROJECT_FILES = (
        "pyproject.toml",
        "uv.lock",
        ".overlay-config.toml",
        ".pytorch-backend",
        ".python-version",
        "package_config.toml",
    )
    PROJECT_DIRS = ("overlays",)

    def __init__(
        self,
        *,
        cec_path: Path,
        workspace_path: Path,
        uv_binary: Path | None = None,
        torch_backend: str | None = None,
    ) -> None:
        self.cec_path = cec_path
        self.workspace_path = workspace_path
        self.uv_binary = uv_binary
        self.torch_backend = torch_backend
        self.uv_cache_path = workspace_path / "uv_cache"
        self.uv_python_path = workspace_path / "uv" / "python"

    def preview_node_package(self, node_package: NodePackage) -> DependencyResolutionPreview:
        """Return the lockfile diff for adding ``node_package``.

        The real project is never mutated. The service copies the minimum project
        files needed for a uv solve into a temporary directory, locks that
        baseline with the same active overlays used by sync, applies the same
        dependency-group mutation used by node installation, re-locks, and
        compares the overlay-aware baseline with the proposed lock.
        """
        if not node_package.requirements:
            return DependencyResolutionPreview(
                success=True,
                node_name=node_package.name,
                requirements=(),
                changes=(),
                lockfile_changed=False,
            )

        with tempfile.TemporaryDirectory(prefix="comfygit-resolution-preview-") as temp_dir:
            temp_project = Path(temp_dir)
            self._copy_project_files(temp_project)
            excluded_names = self._lock_diff_excluded_names(temp_project)

            try:
                self._lock_temp_project(temp_project)
                baseline_lock = (temp_project / "uv.lock").read_bytes()
                before = self._read_lock_packages(
                    temp_project / "uv.lock",
                    excluded_names=excluded_names,
                )
                self._apply_node_package(temp_project, node_package)
                self._lock_temp_project(temp_project)
                after = self._read_lock_packages(
                    temp_project / "uv.lock",
                    excluded_names=excluded_names,
                )
            except UVCommandError as exc:
                return DependencyResolutionPreview(
                    success=False,
                    node_name=node_package.name,
                    requirements=tuple(node_package.requirements),
                    error=str(exc),
                    stderr=exc.stderr or "",
                    warnings=tuple(self._stderr_summary(exc.stderr or str(exc))),
                )
            except Exception as exc:
                logger.exception("Dependency resolution preview failed")
                return DependencyResolutionPreview(
                    success=False,
                    node_name=node_package.name,
                    requirements=tuple(node_package.requirements),
                    error=str(exc),
                    warnings=(str(exc),),
                )

            changes = self._diff_packages(before, after)
            return DependencyResolutionPreview(
                success=True,
                node_name=node_package.name,
                requirements=tuple(node_package.requirements),
                changes=tuple(changes),
                lockfile_changed=self._lockfile_changed(temp_project, baseline_lock),
                baseline_fingerprint=self._packages_fingerprint(before),
                diff_fingerprint=self._changes_fingerprint(changes),
                proposed_fingerprint=self._packages_fingerprint(after),
            )

    def _copy_project_files(self, temp_project: Path) -> None:
        for filename in self.PROJECT_FILES:
            source = self.cec_path / filename
            if source.exists() and source.is_file():
                shutil.copy2(source, temp_project / filename)

        for dirname in self.PROJECT_DIRS:
            source = self.cec_path / dirname
            if source.exists() and source.is_dir():
                shutil.copytree(source, temp_project / dirname)

    def _apply_node_package(self, temp_project: Path, node_package: NodePackage) -> None:
        pyproject = PyprojectManager(temp_project / "pyproject.toml")
        uv = UVCommand(
            binary_path=self.uv_binary,
            project_env=temp_project / ".venv-preview",
            cache_dir=self.uv_cache_path,
            python_install_dir=self.uv_python_path,
            cwd=temp_project,
            torch_backend=self.torch_backend,
        )
        uv_project = UVProjectManager(uv, pyproject)

        group_name = pyproject.nodes.generate_group_name(
            node_package.node_info,
            node_package.identifier,
        )
        uv_project.add_requirements_with_sources(
            node_package.requirements,
            group=group_name,
            no_sync=True,
            raw=True,
        )
        pyproject.nodes.add(node_package.node_info, node_package.identifier)

    def _lock_temp_project(self, temp_project: Path) -> None:
        pyproject = PyprojectManager(temp_project / "pyproject.toml")
        pytorch_manager = PyTorchBackendManager(temp_project)
        overlay_manager = OverlayManager(temp_project)
        uv = UVCommand(
            binary_path=self.uv_binary,
            project_env=temp_project / ".venv-preview",
            cache_dir=self.uv_cache_path,
            python_install_dir=self.uv_python_path,
            cwd=temp_project,
            torch_backend=self.torch_backend,
        )
        pytorch_config: dict[str, Any] | None = None
        if pytorch_manager.has_backend():
            config = pyproject.load()
            python_version = config.get("tool", {}).get("comfygit", {}).get("python_version")
            pytorch_config = pytorch_manager.get_pytorch_config(
                python_version=python_version,
            )

        overlays = overlay_manager.collect_overlays(pytorch_config=pytorch_config)
        if overlays:
            with pyproject.uv_injection_context(overlays=overlays):
                uv.lock()
            return

        uv.lock()

    def _lockfile_changed(self, temp_project: Path, baseline_lock: bytes) -> bool:
        proposed = temp_project / "uv.lock"
        if not proposed.exists():
            return bool(baseline_lock)
        return proposed.read_bytes() != baseline_lock

    def _lock_diff_excluded_names(self, temp_project: Path) -> set[str]:
        """Return lock package names that are not user-meaningful dependency changes."""
        pyproject_path = temp_project / "pyproject.toml"
        if not pyproject_path.exists():
            return set()

        try:
            config = tomlkit.loads(pyproject_path.read_text(encoding="utf-8"))
        except Exception:
            return set()

        project_name = config.get("project", {}).get("name")
        if not isinstance(project_name, str):
            return set()

        return {canonicalize_name(project_name)}

    def _read_lock_packages(
        self,
        lock_path: Path,
        *,
        excluded_names: set[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        if not lock_path.exists():
            return {}

        excluded = excluded_names or set()
        data = tomlkit.loads(lock_path.read_text(encoding="utf-8"))
        packages = data.get("package", [])
        result: dict[str, dict[str, Any]] = {}

        for package in packages:
            if not isinstance(package, dict):
                continue
            name = package.get("name")
            if not isinstance(name, str):
                continue
            key = canonicalize_name(name)
            if key in excluded:
                continue
            result[key] = {
                "name": key,
                "version": self._string_or_none(package.get("version")),
                "fingerprint": repr(self._lock_package_fingerprint(package, lock_path.parent)),
            }

        return result

    def _lock_package_fingerprint(
        self,
        package: dict[str, Any],
        lock_dir: Path,
    ) -> dict[str, Any]:
        """Return meaningful lock fields for diffing installed package behavior."""
        fingerprint: dict[str, Any] = {
            "name": self._string_or_none(package.get("name")),
            "version": self._string_or_none(package.get("version")),
        }

        source = package.get("source")
        if isinstance(source, dict):
            fingerprint["source"] = self._normalize_lock_source(source, lock_dir)

        dependencies = package.get("dependencies")
        if dependencies:
            fingerprint["dependencies"] = self._plain(dependencies)

        optional_dependencies = package.get("optional-dependencies")
        if optional_dependencies:
            fingerprint["optional_dependencies"] = self._plain(optional_dependencies)

        return fingerprint

    def _normalize_lock_source(self, source: dict[str, Any], lock_dir: Path) -> dict[str, Any]:
        normalized = self._plain(source)
        if not isinstance(normalized, dict):
            return {}

        for key in ("editable", "directory", "path"):
            value = normalized.get(key)
            if isinstance(value, str):
                source_path = Path(value)
                if not source_path.is_absolute():
                    source_path = lock_dir / source_path
                normalized[key] = str(source_path.resolve())

        return normalized

    def _diff_packages(
        self,
        before: dict[str, dict[str, Any]],
        after: dict[str, dict[str, Any]],
    ) -> list[PackageVersionChange]:
        changes: list[PackageVersionChange] = []

        for name in sorted(after.keys() - before.keys()):
            changes.append(PackageVersionChange(name, None, after[name]["version"], "added"))

        for name in sorted(before.keys() - after.keys()):
            changes.append(PackageVersionChange(name, before[name]["version"], None, "removed"))

        for name in sorted(before.keys() & after.keys()):
            current = before[name]["version"]
            proposed = after[name]["version"]
            if current != proposed:
                changes.append(
                    PackageVersionChange(
                        name,
                        current,
                        proposed,
                        self._version_change_kind(current, proposed),
                    )
                )
            elif before[name]["fingerprint"] != after[name]["fingerprint"]:
                changes.append(PackageVersionChange(name, current, proposed, "changed"))

        return changes

    def _packages_fingerprint(self, packages: dict[str, dict[str, Any]]) -> str:
        return self._stable_hash(packages)

    def _changes_fingerprint(self, changes: list[PackageVersionChange]) -> str:
        payload = [
            {
                "name": change.name,
                "current": change.current,
                "proposed": change.proposed,
                "kind": change.kind,
            }
            for change in changes
        ]
        return self._stable_hash(payload)

    def _stable_hash(self, value: Any) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _version_change_kind(
        self,
        current: str | None,
        proposed: str | None,
    ) -> PackageChangeKind:
        if current is None or proposed is None:
            return "changed"
        try:
            current_version = parse_version(current)
            proposed_version = parse_version(proposed)
            if proposed_version < current_version:
                return "downgraded"
            if proposed_version > current_version:
                return "upgraded"
        except Exception:
            pass
        return "changed"

    def _string_or_none(self, value: object) -> str | None:
        if value is None:
            return None
        return str(value)

    def _plain(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): self._plain(item) for key, item in sorted(value.items())}
        if isinstance(value, list):
            return [self._plain(item) for item in value]
        return value

    def _stderr_summary(self, stderr: str) -> list[str]:
        lines = [line.strip() for line in stderr.splitlines() if line.strip()]
        if not lines:
            return []
        return lines[-5:]
