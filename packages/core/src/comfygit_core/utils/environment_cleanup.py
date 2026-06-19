"""Cross-platform environment directory cleanup utilities."""
from pathlib import Path
from uuid import uuid4

from ..logging.logging_config import get_logger
from .filesystem import rmtree

logger = get_logger(__name__)

# Marker file indicating environment creation completed successfully
COMPLETION_MARKER = ".complete"
DELETED_ENVIRONMENT_PREFIX = ".comfygit-deleted-"


def _quarantine_environment_directory(env_path: Path) -> Path:
    """Move a hard-to-delete environment aside so its original name is reusable."""
    for _ in range(10):
        quarantine_path = (
            env_path.parent
            / f"{DELETED_ENVIRONMENT_PREFIX}{env_path.name}-{uuid4().hex[:8]}"
        )
        if quarantine_path.exists():
            continue
        env_path.rename(quarantine_path)
        return quarantine_path

    raise FileExistsError(f"Could not choose a quarantine path for {env_path}")


def _quarantine_after_failed_delete(env_path: Path, original_error: OSError) -> bool:
    """Best-effort fallback for Windows locks that block direct deletion."""
    if not env_path.exists():
        return True

    try:
        quarantine_path = _quarantine_environment_directory(env_path)
    except OSError as quarantine_error:
        logger.warning(
            "Failed to quarantine environment directory after delete error: %s",
            quarantine_error,
        )
        return False

    logger.warning(
        "Moved environment directory to %s after delete failed: %s",
        quarantine_path,
        original_error,
    )
    try:
        rmtree(quarantine_path, ignore_errors=True)
    except Exception as cleanup_error:
        logger.debug("Deferred quarantined environment cleanup failed: %s", cleanup_error)

    return not env_path.exists()


def remove_environment_directory(env_path: Path) -> None:
    """Remove environment directory with platform-specific handling.

    This handles Windows file locks and permission issues that commonly
    occur when Python processes or uv operations are interrupted.

    Args:
        env_path: Path to environment directory

    Raises:
        PermissionError: If deletion fails due to permissions
        OSError: If deletion fails for other reasons
    """
    if not env_path.exists():
        return

    try:
        rmtree(env_path)
        if env_path.exists():
            raise OSError(f"directory still exists after cleanup: {env_path}")
        logger.debug(f"Removed environment directory: {env_path}")
    except PermissionError as e:
        if _quarantine_after_failed_delete(env_path, e):
            return
        raise PermissionError(
            f"Cannot delete '{env_path.name}': files may be in use. "
            f"Try closing applications using this environment."
        ) from e
    except OSError as e:
        if _quarantine_after_failed_delete(env_path, e):
            return
        raise OSError(f"Failed to delete environment '{env_path.name}': {e}") from e


def cleanup_partial_environment(env_path: Path) -> bool:
    """Clean up partial environment after creation failure.

    Uses platform-specific cleanup and provides user feedback on failure.

    Args:
        env_path: Path to partial environment directory

    Returns:
        True if cleanup succeeded, False if manual intervention needed
    """
    if not env_path.exists():
        return True

    logger.debug(f"Cleaning up partial environment at {env_path}")

    try:
        remove_environment_directory(env_path)
        return True
    except (PermissionError, OSError) as e:
        logger.warning(f"Failed to clean up partial environment: {e}")
        return False


def mark_environment_complete(cec_path: Path) -> None:
    """Mark environment as fully initialized.

    Creates a completion marker file that list_environments() uses to
    filter out partial/broken environments.

    Args:
        cec_path: Path to .cec directory
    """
    marker_file = cec_path / COMPLETION_MARKER
    marker_file.touch()
    logger.debug(f"Marked environment as complete: {marker_file}")


def is_environment_complete(cec_path: Path) -> bool:
    """Check if environment was fully initialized.

    Args:
        cec_path: Path to .cec directory

    Returns:
        True if environment has completion marker
    """
    return (cec_path / COMPLETION_MARKER).exists()
