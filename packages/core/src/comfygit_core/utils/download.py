"""Download and archive extraction utilities."""

import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from ..logging.logging_config import get_logger
from .redaction import redact_sensitive_text, redact_url

logger = get_logger(__name__)


def download_and_extract_archive(url: str, target_path: Path) -> None:
    """Download and extract an archive file with automatic format detection.

    Args:
        url: URL of the archive to download
        target_path: Directory to extract contents to

    Raises:
        OSError: If download fails
        ValueError: If archive format is unsupported or corrupted
    """
    temp_file_path = None
    try:
        # Download file first
        temp_file_path = download_file(url)
        # Extract with format detection
        extract_archive(temp_file_path, target_path)

    except (OSError, ValueError):
        # Re-raise download and extraction errors as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected error during download/extract: {e}")
        raise OSError(f"Unexpected error during download/extract: {e}") from e
    finally:
        # Always clean up temp file
        if temp_file_path and temp_file_path.exists():
            try:
                temp_file_path.unlink()
            except OSError:
                # Log but don't fail if cleanup fails
                logger.warning(f"Failed to clean up temp file: {temp_file_path}")


def download_file(url: str, suffix: str | None = None) -> Path:
    """Download a file to a temporary location.

    Args:
        url: URL to download from
        suffix: Optional file suffix for the temp file

    Returns:
        Path to downloaded file

    Raises:
        OSError: If download fails
    """
    try:
        if not suffix:
            suffix = Path(url).suffix

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            logger.info("Downloading from %s", redact_url(url))

            with urllib.request.urlopen(url) as response:
                # Read in chunks for large files
                chunk_size = 8192
                total_size = 0

                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    tmp_file.write(chunk)
                    total_size += len(chunk)

            tmp_path = Path(tmp_file.name)
            logger.debug(f"Downloaded {total_size / 1024:.1f} KB to {tmp_path}")
            return tmp_path

    except Exception as e:
        safe_error = redact_sensitive_text(e)
        logger.error("Download failed: %s", safe_error)
        raise OSError(f"Download failed: {safe_error}") from e


def extract_archive(archive_path: Path, target_path: Path) -> None:
    """Extract an archive with automatic format detection.

    Tries multiple archive formats until one succeeds:
    - ZIP
    - TAR.GZ (gzipped tar)
    - TAR (plain tar)
    - TAR.BZ2 (bzip2 tar)

    Args:
        archive_path: Path to archive file
        target_path: Directory to extract to

    Raises:
        ValueError: If file is not a supported archive format
        OSError: If file system operation fails (permissions, disk space, etc.)
    """
    # Ensure target directory exists
    target_path.mkdir(parents=True, exist_ok=True)

    # Try different extraction methods
    extractors = [
        (_try_extract_zip, "zip"),
        (_try_extract_tar_gz, "tar.gz"),
        (_try_extract_tar, "tar"),
        (_try_extract_tar_bz2, "tar.bz2"),
    ]

    extraction_errors = []

    for extractor, format_name in extractors:
        try:
            extractor(archive_path, target_path)
            logger.info(f"Successfully extracted as {format_name} format")
            return
        except (zipfile.BadZipFile, tarfile.ReadError):
            # Expected errors for wrong format, continue trying
            continue
        except Exception as e:
            # Unexpected errors, collect for reporting
            extraction_errors.append(f"{format_name}: {e}")

    # If nothing worked, log diagnostic info and raise exception
    _log_extraction_failure(archive_path)
    if extraction_errors:
        # Had OS-level errors during extraction attempts
        error_details = "; ".join(extraction_errors)
        raise OSError(f"Archive extraction failed due to system errors: {error_details}")
    else:
        # No format worked, likely unsupported/corrupted file
        raise ValueError(f"Unsupported or corrupted archive format: {archive_path}")


def _try_extract_zip(archive_path: Path, target_path: Path) -> None:
    """Try to extract as ZIP archive.

    Raises:
        zipfile.BadZipFile: If not a valid ZIP file
        OSError: If extraction fails
    """
    try:
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            zip_ref.extractall(target_path)
    except zipfile.BadZipFile:
        raise
    except Exception as e:
        raise OSError(f"ZIP extraction failed: {e}") from e


def _try_extract_tar_gz(archive_path: Path, target_path: Path) -> None:
    """Try to extract as gzipped TAR archive.

    Raises:
        tarfile.ReadError: If not a valid gzipped TAR file
        OSError: If extraction fails
    """
    try:
        with tarfile.open(archive_path, 'r:gz') as tar:
            tar.extractall(target_path)
    except tarfile.ReadError:
        raise
    except Exception as e:
        raise OSError(f"TAR.GZ extraction failed: {e}") from e


def _try_extract_tar(archive_path: Path, target_path: Path) -> None:
    """Try to extract as plain TAR archive.

    Raises:
        tarfile.ReadError: If not a valid TAR file
        OSError: If extraction fails
    """
    try:
        with tarfile.open(archive_path, 'r:') as tar:
            tar.extractall(target_path)
    except tarfile.ReadError:
        raise
    except Exception as e:
        raise OSError(f"TAR extraction failed: {e}") from e


def _try_extract_tar_bz2(archive_path: Path, target_path: Path) -> None:
    """Try to extract as bzip2 TAR archive.

    Raises:
        tarfile.ReadError: If not a valid bzip2 TAR file
        OSError: If extraction fails
    """
    try:
        with tarfile.open(archive_path, 'r:bz2') as tar:
            tar.extractall(target_path)
    except tarfile.ReadError:
        raise
    except Exception as e:
        raise OSError(f"TAR.BZ2 extraction failed: {e}") from e


def _log_extraction_failure(archive_path: Path) -> None:
    """Log diagnostic information when extraction fails."""
    logger.error(f"Unable to extract archive: {archive_path}")

    # Read first few bytes for debugging
    try:
        with open(archive_path, 'rb') as f:
            header = f.read(32)
            logger.debug(f"File header (first 32 bytes): {header}")
    except Exception:
        pass
