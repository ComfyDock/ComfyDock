"""Export/Import manager for bundling and extracting environments."""
from __future__ import annotations

import shutil
import tarfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

from ..logging.logging_config import get_logger

if TYPE_CHECKING:
    from .pyproject_manager import PyprojectManager

logger = get_logger(__name__)


def _tar_extractall_supports_filter(tar: tarfile.TarFile) -> bool:
    """Return whether this Python version supports tar extraction filters."""
    return "filter" in tar.extractall.__code__.co_varnames


def _validate_tar_member(member: tarfile.TarInfo, target_root: Path) -> None:
    """Validate a tar member before extraction on Python versions without filters."""
    member_name = member.name
    posix_path = PurePosixPath(member_name)
    windows_path = PureWindowsPath(member_name)

    if posix_path.is_absolute() or windows_path.is_absolute():
        raise ValueError(f"Archive contains an absolute path: {member_name}")

    if ".." in posix_path.parts or ".." in windows_path.parts:
        raise ValueError(f"Archive contains an unsafe relative path: {member_name}")

    if not (member.isfile() or member.isdir()):
        raise ValueError(f"Archive contains an unsupported entry type: {member_name}")

    destination = (target_root / member_name).resolve()
    if destination != target_root and target_root not in destination.parents:
        raise ValueError(f"Archive entry escapes target directory: {member_name}")


def _safe_extractall(tar: tarfile.TarFile, target_path: Path) -> None:
    """Extract a tarball using Python's data filter or a strict local fallback."""
    if _tar_extractall_supports_filter(tar):
        tar.extractall(target_path, filter="data")
        return

    target_root = target_path.resolve()
    for member in tar.getmembers():
        _validate_tar_member(member, target_root)

    for member in tar.getmembers():
        destination = target_root / member.name
        if member.isdir():
            destination.mkdir(parents=True, exist_ok=True)
            continue

        source = tar.extractfile(member)
        if source is None:
            raise ValueError(f"Archive file entry cannot be read: {member.name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)


class ExportImportManager:
    """Manages environment export and import operations."""

    def __init__(self, cec_path: Path, comfyui_path: Path):
        self.cec_path = cec_path
        self.comfyui_path = comfyui_path

    def create_export(
        self,
        output_path: Path,
        pyproject_manager: PyprojectManager
    ) -> Path:
        """Create export tarball.

        Args:
            output_path: Output .tar.gz file path
            pyproject_manager: PyprojectManager for reading config

        Returns:
            Path to created tarball
        """
        logger.info(f"Creating export at {output_path}")

        with tarfile.open(output_path, "w:gz") as tar:
            # Add pyproject.toml
            pyproject_path = self.cec_path / "pyproject.toml"
            if pyproject_path.exists():
                tar.add(pyproject_path, arcname="pyproject.toml")

            # Note: uv.lock is NOT exported - it's platform-specific due to PyTorch variants
            # Each machine re-resolves based on .pytorch-backend

            # Add .python-version
            python_version_path = self.cec_path / ".python-version"
            if python_version_path.exists():
                tar.add(python_version_path, arcname=".python-version")

            # Add package_config.toml (package substitutions and exclusions)
            package_config_path = self.cec_path / "package_config.toml"
            if package_config_path.exists():
                tar.add(package_config_path, arcname="package_config.toml")

            # Add workflows
            workflows_path = self.cec_path / "workflows"
            if workflows_path.exists():
                for workflow_file in sorted(workflows_path.glob("*.json")):
                    tar.add(workflow_file, arcname=f"workflows/{workflow_file.name}")

            # Add captured API prompts for workflow execution contracts.
            workflow_api_path = self.cec_path / "workflow_api"
            if workflow_api_path.exists():
                for api_file in sorted(workflow_api_path.rglob("*.json")):
                    if not api_file.is_file():
                        continue
                    relative = api_file.relative_to(workflow_api_path)
                    tar.add(api_file, arcname=f"workflow_api/{relative.as_posix()}")

            # Add shared overlays (tracked). Local overlays are dot-prefixed and excluded.
            overlays_path = self.cec_path / "overlays"
            if overlays_path.exists():
                for overlay_file in sorted(overlays_path.glob("*.toml")):
                    if overlay_file.name.startswith("."):
                        continue
                    tar.add(overlay_file, arcname=f"overlays/{overlay_file.name}")

            # NOTE: Dev nodes are NO LONGER bundled.
            # They use git references (repository/branch/pinned_commit) instead.
            # This enables team collaboration on custom nodes without large bundles.
            # See: auto_populate_dev_node_git_info() which captures git info during export.

        logger.info(f"Export created successfully: {output_path}")
        return output_path

    def extract_import(self, tarball_path: Path, target_cec_path: Path) -> None:
        """Extract import tarball to target .cec directory.

        Args:
            tarball_path: Path to .tar.gz file
            target_cec_path: Target .cec directory (must not exist)

        Raises:
            ValueError: If target already exists
        """
        if target_cec_path.exists():
            raise ValueError(f"Target path already exists: {target_cec_path}")

        logger.info(f"Extracting import from {tarball_path}")

        # Create target directory
        target_cec_path.mkdir(parents=True)

        # Extract tarball with path traversal protections on all supported Python versions.
        with tarfile.open(tarball_path, "r:gz") as tar:
            _safe_extractall(tar, target_cec_path)

        logger.info(f"Import extracted successfully to {target_cec_path}")

    def _add_filtered_directory(self, tar: tarfile.TarFile, source_path: Path, arcname: str):
        """Add directory to tarball, filtering by .gitignore.

        Args:
            tar: Open tarfile
            source_path: Source directory
            arcname: Archive name prefix
        """
        # Simple implementation - add all files (MVP)
        # TODO: Add .gitignore filtering if needed
        for item in source_path.rglob("*"):
            if item.is_file():
                # Skip __pycache__ and .pyc files
                if "__pycache__" in item.parts or item.suffix == ".pyc":
                    continue
                relative = item.relative_to(source_path)
                tar.add(item, arcname=f"{arcname}/{relative}")
