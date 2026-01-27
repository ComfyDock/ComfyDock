"""ModelSymlinkManager - Creates and manages symlink from ComfyUI/models to global models directory."""
from __future__ import annotations

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


class ModelSymlinkManager:
    """Manages symlink/junction from ComfyUI/models to global models directory."""

    def __init__(self, comfyui_path: Path, global_models_path: Path):
        """Initialize ModelSymlinkManager.

        Args:
            comfyui_path: Path to ComfyUI directory
            global_models_path: Path to global models directory
        """
        self.comfyui_path = comfyui_path
        self.global_models_path = global_models_path
        self.models_link_path = comfyui_path / "models"

    def create_symlink(self) -> None:
        """Create symlink/junction from ComfyUI/models to global models.

        Raises:
            CDEnvironmentError: If global models directory doesn't exist, or if models/
                               exists with actual content
        """
        # Check global models directory exists
        if not self.global_models_path.exists():
            raise CDEnvironmentError(
                f"Global models directory does not exist: {self.global_models_path}\n"
                f"Create it first: mkdir -p {self.global_models_path}"
            )

        # Handle existing models/ path
        if self.models_link_path.exists():
            if is_link(self.models_link_path):
                # Already a link - check target
                if self._resolve_link() == self.global_models_path.resolve():
                    logger.debug("Link already points to correct target")
                    return
                else:
                    # Wrong target - recreate
                    logger.info(
                        f"Updating link target: {self._resolve_link()} → {self.global_models_path}"
                    )
                    self.models_link_path.unlink()
            else:
                # Real directory - check if safe to delete
                safe_files = {".gitkeep", ".gitignore", "Put models here.txt"}
                if is_safe_to_delete(self.models_link_path, safe_files):
                    logger.info(
                        "Removing ComfyUI default models/ directory (empty or placeholder files only)"
                    )
                    rmtree(self.models_link_path)
                else:
                    raise CDEnvironmentError(
                        f"models/ directory exists with content: {self.models_link_path}\n"
                        f"Manual action required:\n"
                        f"  1. Backup if needed: mv {self.models_link_path} {self.models_link_path}.backup\n"
                        f"  2. Remove: rm -rf {self.models_link_path}\n"
                        f"  3. Retry: cg repair"
                    )

        # Ensure parent directory (ComfyUI/) exists
        self.comfyui_path.mkdir(parents=True, exist_ok=True)

        # Create platform-appropriate link
        create_platform_link(self.models_link_path, self.global_models_path, "models")
        logger.info(
            f"Created model link: {self.models_link_path} → {self.global_models_path}"
        )

    def validate_symlink(self) -> bool:
        """Check if link exists and points to correct target.

        Returns:
            True if link is valid, False otherwise
        """
        if not self.models_link_path.exists():
            return False

        if not is_link(self.models_link_path):
            logger.warning(f"models/ is not a link: {self.models_link_path}")
            return False

        target = self._resolve_link()
        if target != self.global_models_path.resolve():
            logger.warning(
                f"Link points to wrong target:\n"
                f"  Expected: {self.global_models_path}\n"
                f"  Actual: {target}"
            )
            return False

        return True

    def remove_symlink(self) -> None:
        """Remove symlink/junction safely.

        Raises:
            CDEnvironmentError: If models/ is not a link (prevents accidental data loss)
        """
        if not self.models_link_path.exists():
            return  # Nothing to remove

        if not is_link(self.models_link_path):
            raise CDEnvironmentError(
                f"Cannot remove models/: not a link\n"
                f"Manual deletion required: {self.models_link_path}"
            )

        try:
            self.models_link_path.unlink()
            logger.info(f"Removed model link: {self.models_link_path}")
        except Exception as e:
            raise CDEnvironmentError(f"Failed to remove link: {e}") from e

    def get_status(self) -> dict:
        """Get current link status for debugging.

        Returns:
            Dictionary with status information
        """
        if not self.models_link_path.exists():
            return {
                "exists": False,
                "is_symlink": False,
                "is_valid": False,
                "target": None,
            }

        is_symlink_or_junction = is_link(self.models_link_path)
        target = self._resolve_link() if is_symlink_or_junction else None
        is_valid = (
            is_symlink_or_junction and target == self.global_models_path.resolve()
            if target
            else False
        )

        return {
            "exists": True,
            "is_symlink": is_symlink_or_junction,
            "is_valid": is_valid,
            "target": str(target) if target else None,
        }

    def _resolve_link(self) -> Path:
        """Get symlink target path.

        Returns:
            Resolved path of symlink target
        """
        # Use resolve() which works for both symlinks and junctions
        return self.models_link_path.resolve()
