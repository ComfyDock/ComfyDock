"""UserContentSymlinkManager - Manages per-environment input/output directories."""
from __future__ import annotations

import shutil
from pathlib import Path

from ..logging.logging_config import get_logger
from ..models.exceptions import CDEnvironmentError
from ..utils.filesystem import rmtree
from ..utils.symlink_utils import (
    create_platform_link,
    is_link,
    is_safe_to_delete,
)

logger = get_logger(__name__)


class UserContentSymlinkManager:
    """Manages per-environment user content directories (input/output).

    Creates symlinks from ComfyUI/input and ComfyUI/output to workspace-level
    directories that persist when environments are deleted.

    Architecture:
        - Input: ComfyUI/input/ → workspace/input/{env_name}/
        - Output: ComfyUI/output/ → workspace/output/{env_name}/

    Unlike models (which are shared across environments), input/output are
    isolated per-environment to prevent cross-contamination of user data.
    """

    def __init__(
        self,
        comfyui_path: Path,
        env_name: str,
        workspace_input_base: Path,
        workspace_output_base: Path,
    ):
        """Initialize UserContentSymlinkManager.

        Args:
            comfyui_path: Path to ComfyUI directory
            env_name: Environment name (for subdirectory creation)
            workspace_input_base: Base workspace input directory (workspace/input/)
            workspace_output_base: Base workspace output directory (workspace/output/)
        """
        self.comfyui_path = comfyui_path
        self.env_name = env_name

        # Workspace targets (per-environment subdirectories)
        self.input_target = workspace_input_base / env_name
        self.output_target = workspace_output_base / env_name

        # ComfyUI symlinks
        self.input_link = comfyui_path / "input"
        self.output_link = comfyui_path / "output"

        # Safe files that can be deleted without warning
        self.safe_files = {".gitkeep", ".gitignore", "Put files here.txt"}

    def create_directories(self) -> None:
        """Create workspace subdirectories for this environment.

        Creates:
            - workspace/input/{env_name}/
            - workspace/output/{env_name}/

        Safe to call multiple times (idempotent).
        """
        self.input_target.mkdir(parents=True, exist_ok=True)
        self.output_target.mkdir(parents=True, exist_ok=True)
        logger.debug(
            f"Created workspace directories for '{self.env_name}': "
            f"input={self.input_target}, output={self.output_target}"
        )

    def create_symlinks(self) -> None:
        """Create input and output symlinks.

        Raises:
            CDEnvironmentError: If workspace directories don't exist or if
                              ComfyUI directories exist with actual content
        """
        # Ensure workspace directories exist
        if not self.input_target.exists():
            raise CDEnvironmentError(
                f"Workspace input directory for '{self.env_name}' does not exist: {self.input_target}\n"
                f"Call create_directories() first"
            )

        if not self.output_target.exists():
            raise CDEnvironmentError(
                f"Workspace output directory for '{self.env_name}' does not exist: {self.output_target}\n"
                f"Call create_directories() first"
            )

        # Create both symlinks
        self._create_single_link(
            self.input_link,
            self.input_target,
            "input"
        )
        self._create_single_link(
            self.output_link,
            self.output_target,
            "output"
        )

    def _create_single_link(
        self,
        link_path: Path,
        target_path: Path,
        name: str
    ) -> None:
        """Create a single symlink with safety checks.

        Args:
            link_path: Where to create symlink (e.g., ComfyUI/input/)
            target_path: What symlink should point to (e.g., workspace/input/env1/)
            name: Directory name for logging/errors ("input" or "output")
        """
        # Handle existing path
        if link_path.exists():
            if is_link(link_path):
                # Already a link - check target
                if link_path.resolve() == target_path.resolve():
                    logger.debug(f"{name} link already points to correct target")
                    return
                else:
                    # Wrong target - recreate
                    logger.info(
                        f"Updating {name} link target: "
                        f"{link_path.resolve()} -> {target_path}"
                    )
                    link_path.unlink()
            else:
                # Real directory - check if safe to delete
                if is_safe_to_delete(link_path, self.safe_files):
                    logger.info(
                        f"Removing ComfyUI default {name}/ directory "
                        f"(empty or placeholder files only)"
                    )
                    rmtree(link_path)
                else:
                    # Has content - needs migration
                    raise CDEnvironmentError(
                        f"{name}/ directory exists with content: {link_path}\n"
                        f"Use migrate_existing_data() to migrate to workspace-level storage"
                    )

        # Ensure parent directory (ComfyUI/) exists
        self.comfyui_path.mkdir(parents=True, exist_ok=True)

        # Create link
        create_platform_link(link_path, target_path, name)
        logger.info(f"Created {name} link: {link_path} -> {target_path}")

    def migrate_existing_data(self) -> dict[str, int]:
        """Migrate existing input/output directories to workspace-level storage.

        This handles upgrading environments created before the symlink feature.
        If ComfyUI/input or ComfyUI/output exist as real directories with content,
        moves their contents to workspace-level and creates symlinks.

        Returns:
            Dict with migration statistics:
                {
                    "input_files_moved": int,
                    "output_files_moved": int,
                }

        Raises:
            CDEnvironmentError: If migration fails
        """
        stats = {
            "input_files_moved": 0,
            "output_files_moved": 0,
        }

        # Ensure workspace directories exist
        self.create_directories()

        # Migrate input
        if self.input_link.exists() and not is_link(self.input_link):
            if not is_safe_to_delete(self.input_link, self.safe_files):
                logger.info("Migrating existing input/ directory to workspace...")
                stats["input_files_moved"] = self._migrate_directory(
                    self.input_link,
                    self.input_target,
                    "input"
                )
            else:
                # Just remove empty/placeholder directory
                rmtree(self.input_link)

        # Migrate output
        if self.output_link.exists() and not is_link(self.output_link):
            if not is_safe_to_delete(self.output_link, self.safe_files):
                logger.info("Migrating existing output/ directory to workspace...")
                stats["output_files_moved"] = self._migrate_directory(
                    self.output_link,
                    self.output_target,
                    "output"
                )
            else:
                # Just remove empty/placeholder directory
                rmtree(self.output_link)

        # Create symlinks after migration
        self.create_symlinks()

        return stats

    def _migrate_directory(
        self,
        source_dir: Path,
        target_dir: Path,
        name: str
    ) -> int:
        """Move contents from source to target and create symlink.

        Args:
            source_dir: Directory with existing content (e.g., ComfyUI/input/)
            target_dir: Workspace directory to move to (e.g., workspace/input/env1/)
            name: Directory name for logging

        Returns:
            Number of items moved
        """
        # Count items before migration
        items = list(source_dir.iterdir())
        item_count = len(items)

        if item_count == 0:
            logger.debug(f"No files to migrate in {name}/")
            rmtree(source_dir)
            return 0

        logger.info(f"Migrating {item_count} items from {name}/ to workspace...")

        # Move each item
        for item in items:
            target_path = target_dir / item.name
            if target_path.exists():
                logger.warning(
                    f"Target already exists, skipping: {item.name}"
                )
                continue

            shutil.move(str(item), str(target_path))
            logger.debug(f"Moved: {item.name}")

        # Remove now-empty source directory
        rmtree(source_dir)
        logger.info(f"Migration complete: {item_count} items moved to {target_dir}")

        return item_count

    def validate_symlinks(self) -> dict[str, bool]:
        """Check if symlinks exist and point to correct targets.

        Returns:
            Dict with validation results:
                {
                    "input": bool,  # True if valid
                    "output": bool,  # True if valid
                }
        """
        return {
            "input": self._validate_single_link(self.input_link, self.input_target, "input"),
            "output": self._validate_single_link(self.output_link, self.output_target, "output"),
        }

    def _validate_single_link(
        self,
        link_path: Path,
        target_path: Path,
        name: str
    ) -> bool:
        """Validate a single symlink."""
        if not link_path.exists():
            logger.warning(f"{name} link does not exist: {link_path}")
            return False

        if not is_link(link_path):
            logger.warning(f"{name}/ is not a link: {link_path}")
            return False

        actual_target = link_path.resolve()
        expected_target = target_path.resolve()

        if actual_target != expected_target:
            logger.warning(
                f"{name} link points to wrong target:\n"
                f"  Expected: {expected_target}\n"
                f"  Actual: {actual_target}"
            )
            return False

        return True

    def remove_symlinks(self) -> None:
        """Remove input and output symlinks safely.

        Note: This only removes symlinks, not the workspace data they point to.
        Workspace data (workspace/input/{env_name}/ and workspace/output/{env_name}/)
        is preserved for manual cleanup or deletion via delete_user_data().

        Raises:
            CDEnvironmentError: If paths exist but are not symlinks
        """
        self._remove_single_link(self.input_link, "input")
        self._remove_single_link(self.output_link, "output")

    def _remove_single_link(self, link_path: Path, name: str) -> None:
        """Remove a single symlink safely."""
        if not link_path.exists():
            return  # Nothing to remove

        if not is_link(link_path):
            raise CDEnvironmentError(
                f"Cannot remove {name}/: not a link\n"
                f"Manual deletion required: {link_path}"
            )

        link_path.unlink()
        logger.info(f"Removed {name} link: {link_path}")

    def get_user_data_size(self) -> dict[str, tuple[int, int]]:
        """Get size of user content for deletion warnings.

        Returns:
            Dict with file counts and sizes in bytes:
                {
                    "input": (file_count, total_bytes),
                    "output": (file_count, total_bytes),
                }
        """
        return {
            "input": self._get_directory_size(self.input_target),
            "output": self._get_directory_size(self.output_target),
        }

    def _get_directory_size(self, path: Path) -> tuple[int, int]:
        """Get file count and total size for directory."""
        if not path.exists():
            return (0, 0)

        total_size = 0
        file_count = 0

        for item in path.rglob("*"):
            if item.is_file():
                file_count += 1
                total_size += item.stat().st_size

        return (file_count, total_size)

    def delete_user_data(self) -> dict[str, int]:
        """Delete workspace user data for this environment.

        WARNING: This permanently deletes user content (input files and generated outputs).
        Should only be called when user explicitly confirms deletion.

        Returns:
            Dict with deletion statistics:
                {
                    "input_files_deleted": int,
                    "output_files_deleted": int,
                }
        """
        stats = {
            "input_files_deleted": 0,
            "output_files_deleted": 0,
        }

        # Delete input directory
        if self.input_target.exists():
            file_count, _ = self._get_directory_size(self.input_target)
            rmtree(self.input_target)
            stats["input_files_deleted"] = file_count
            logger.info(f"Deleted {file_count} input files from {self.input_target}")

        # Delete output directory
        if self.output_target.exists():
            file_count, _ = self._get_directory_size(self.output_target)
            rmtree(self.output_target)
            stats["output_files_deleted"] = file_count
            logger.info(f"Deleted {file_count} output files from {self.output_target}")

        return stats

    def get_status(self) -> dict:
        """Get current symlink status for debugging.

        Returns:
            Dictionary with detailed status for both input and output
        """
        return {
            "input": self._get_single_status(self.input_link, self.input_target, "input"),
            "output": self._get_single_status(self.output_link, self.output_target, "output"),
        }

    def _get_single_status(
        self,
        link_path: Path,
        target_path: Path,
        name: str
    ) -> dict:
        """Get status for a single symlink."""
        if not link_path.exists():
            return {
                "exists": False,
                "is_symlink": False,
                "is_valid": False,
                "target": None,
                "expected_target": str(target_path),
            }

        is_symlink_or_junction = is_link(link_path)
        actual_target = link_path.resolve() if is_symlink_or_junction else None
        is_valid = (
            is_symlink_or_junction
            and actual_target == target_path.resolve()
            if actual_target
            else False
        )

        return {
            "exists": True,
            "is_symlink": is_symlink_or_junction,
            "is_valid": is_valid,
            "target": str(actual_target) if actual_target else None,
            "expected_target": str(target_path),
        }
