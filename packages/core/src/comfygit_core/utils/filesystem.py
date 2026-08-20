"""Filesystem manipulation utilities."""

import inspect
import os
import platform
import shutil
import stat
import time
from pathlib import Path

from ..logging.logging_config import get_logger

logger = get_logger(__name__)
_SUPPORTS_RMTREE_ONEXC = "onexc" in inspect.signature(shutil.rmtree).parameters


def harden_private_file(path: Path) -> bool:
    """Best-effort owner-only permissions for a local sensitive file.

    Returns ``True`` when owner-only POSIX permissions are in effect or when the
    platform does not expose POSIX mode bits. Missing files return ``False``.
    """
    if not path.exists():
        return False
    if os.name == "nt":
        return True
    try:
        path.chmod(0o600)
    except OSError as exc:
        logger.debug("Could not harden private file permissions for %s: %s", path, exc)
        return False
    return (path.stat().st_mode & 0o777) == 0o600


def _windows_long_path(path: Path) -> str:
    """Return a Windows long-path string for filesystem APIs."""
    path_text = str(path.resolve())
    if path_text.startswith("\\\\?\\"):
        return path_text
    if path_text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path_text.lstrip("\\")
    return "\\\\?\\" + path_text


def _handle_remove_readonly(func, path, exc_info):
    """Handle Windows readonly/locked files during deletion.

    Args:
        func: Function that failed (e.g., os.unlink)
        path: Path that couldn't be removed
        exc_info: Exception info tuple
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        time.sleep(0.05)  # Brief delay for handle release
        func(path)
    except Exception as e:
        raise e


def rmtree(path: Path, ignore_errors: bool = False) -> None:
    """Cross-platform directory removal with Windows readonly handling.

    On Windows, git directories often have readonly files that cause
    shutil.rmtree() to fail. This wrapper handles those cases.

    Args:
        path: Directory to remove
        ignore_errors: If True, suppress all errors
    """
    if not path.exists():
        return

    if platform.system() == "Windows":
        rmtree_path = _windows_long_path(path)
        if _SUPPORTS_RMTREE_ONEXC:
            shutil.rmtree(rmtree_path, ignore_errors=ignore_errors, onexc=_handle_remove_readonly)
        else:
            shutil.rmtree(rmtree_path, ignore_errors=ignore_errors, onerror=_handle_remove_readonly)
    else:
        shutil.rmtree(path, ignore_errors=ignore_errors)


def flatten_if_single_dir(path: Path) -> bool:
    """Flatten directory structure if it contains a single nested directory.

    Some archives contain: archive.tar.gz/NodeName-v1.0/*
    We want to flatten to just: NodeName/*

    Args:
        path: Path to check and potentially flatten

    Returns:
        True if flattened, False otherwise
    """
    try:
        contents = list(path.iterdir())

        # If there's exactly one directory and no files
        if len(contents) == 1 and contents[0].is_dir():
            single_dir = contents[0]

            logger.info(f"Flattening nested directory: {single_dir.name}")

            # Move all contents up one level
            for item in single_dir.iterdir():
                dest = path / item.name
                # Handle conflicts by removing destination first
                if dest.exists():
                    if dest.is_dir():
                        rmtree(dest)
                    else:
                        dest.unlink()
                shutil.move(str(item), str(dest))

            # Remove the now-empty nested directory
            single_dir.rmdir()
            return True

    except Exception as e:
        logger.warning(f"Could not flatten directory: {e}")

    return False


def ensure_clean_directory(path: Path) -> None:
    """Ensure a directory exists and is empty.

    Args:
        path: Directory path to prepare
    """
    if path.exists():
        if path.is_dir():
            rmtree(path)
        else:
            path.unlink()

    path.mkdir(parents=True, exist_ok=True)


def safe_copy_tree(src: Path, dest: Path) -> bool:
    """Safely copy a directory tree, handling existing destinations.

    Args:
        src: Source directory
        dest: Destination directory

    Returns:
        True if successful, False otherwise
    """
    try:
        # Remove destination if it exists
        if dest.exists():
            if dest.is_dir():
                rmtree(dest)
            else:
                dest.unlink()

        # Ensure parent directory exists
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Copy the tree
        shutil.copytree(src, dest)
        return True

    except Exception as e:
        logger.error(f"Failed to copy {src} to {dest}: {e}")
        return False


def get_directory_size(path: Path) -> int:
    """Get total size of a directory in bytes.

    Args:
        path: Directory path

    Returns:
        Total size in bytes
    """
    if not path.exists() or not path.is_dir():
        return 0

    total_size = 0
    for item in path.rglob("*"):
        if item.is_file():
            total_size += item.stat().st_size

    return total_size


def find_file_in_tree(root: Path, filename: str) -> Path | None:
    """Find a file anywhere in a directory tree.

    Args:
        root: Root directory to search
        filename: Name of file to find

    Returns:
        Path to first matching file or None
    """
    for path in root.rglob(filename):
        if path.is_file():
            return path
    return None


def calculate_directory_size(path: Path) -> int:
    """Calculate total size of a directory tree in bytes.

    Args:
        path: Directory path to calculate size for

    Returns:
        Total size in bytes
    """
    total_size = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = Path(dirpath) / filename
                if filepath.exists():
                    total_size += filepath.stat().st_size
    except Exception as e:
        logger.warning(f"Could not calculate directory size: {e}")

    return total_size


def get_venv_python(env_path: Path) -> Path | None:
    """Get the Python executable path for a virtual environment.

    Cross-platform detection of Python executable in venv.

    Args:
        env_path: Path to the environment directory

    Returns:
        Path to Python executable or None if not found
    """
    # Try Unix/Linux/Mac path first
    venv_python = env_path / ".venv" / "bin" / "python"
    if venv_python.exists():
        return venv_python

    # Try Windows path
    venv_python = env_path / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return venv_python

    return None
