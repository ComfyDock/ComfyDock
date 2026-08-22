"""ModelScanner - Model file discovery, hashing, and indexing operations."""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from ..configs.model_config import ModelConfig
from ..logging.logging_config import get_logger
from ..models.exceptions import ComfyDockError
from ..models.model_scan import ModelScanProgress, ScanResult

if TYPE_CHECKING:
    from ..repositories.model_repository import ModelRepository

logger = get_logger(__name__)


class ModelProcessResult(Enum):
    """Result of processing a single model file."""
    ADDED = "added"
    UPDATED_PATH = "updated_path"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    SKIPPED_SAME_FILE = "skipped_same"
    COLLISION_RESOLVED = "collision_resolved"


# Extensions that are definitely not model files
EXCLUDED_EXTENSIONS = {
    '.txt', '.md',
    '.lock', '.gitignore', '.gitattributes',
    '.log', '.html', '.xml',
    '.py', '.js', '.ts', '.sh', '.bat', '.ps1',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg',
    '.mp4', '.avi', '.mov', '.webm', '.mp3', '.wav',
    '.zip', '.tar', '.gz', '.rar', '.7z',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx',
    '.DS_Store', '.env',
}

# Minimum file size in bytes
MIN_MODEL_SIZE = 8

# Minimum file size for model files (8 bytes)


class ModelScanner:
    """Model file discovery, hashing, and indexing operations."""

    def __init__(self, index_manager: ModelRepository, model_config: ModelConfig | None = None):
        """Initialize ModelScanner.

        Args:
            index_manager: ModelIndexManager for database operations
            model_config: ModelConfig for extension filtering, loads default if None
        """
        self.index_manager = index_manager
        self.model_config = model_config or ModelConfig.load()
        self.quiet = False

    def scan_directory(self, models_dir: Path, quiet: bool = False, progress: ModelScanProgress | None = None) -> ScanResult:
        """Scan single models directory for all model files.

        Args:
            models_dir: Path to models directory to scan
            quiet: Suppress logging
            progress: Optional progress callback

        Returns:
            ScanResult with operation statistics
        """
        self.quiet = quiet

        if not models_dir.exists():
            raise ComfyDockError(f"Models directory does not exist: {models_dir}")
        if not models_dir.is_dir():
            raise ComfyDockError(f"Models path is not a directory: {models_dir}")

        if not self.quiet:
            logger.info(f"Scanning models directory: {models_dir}")

        # Get existing locations from this directory to check for changes (mtime optimization)
        existing_locations = {loc['relative_path']: loc for loc in self.index_manager.get_all_locations(models_dir)}

        # Find all potential model files
        model_files = self._find_model_files(models_dir) or []

        result = ScanResult(len(model_files), 0, 0, 0, 0, [])

        # Notify progress of scan start
        if progress:
            progress.on_scan_start(len(model_files))

        # Process each model file
        for idx, file_path in enumerate(model_files, 1):
            try:
                relative_path = file_path.relative_to(models_dir).as_posix()
                file_stat = file_path.stat()

                # Check if file has changed
                existing = existing_locations.get(relative_path)
                if existing and existing['mtime'] == file_stat.st_mtime:
                    result.skipped_count += 1
                    if progress:
                        progress.on_file_processed(idx, len(model_files), file_path.name)
                    continue

                # Process the model file
                process_result = self._process_model_file(file_path, models_dir)
                self._update_result_counters(result, process_result)

                # Notify progress after processing
                if progress:
                    progress.on_file_processed(idx, len(model_files), file_path.name)

            except Exception as e:
                error_msg = f"Error processing {file_path}: {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)
                result.error_count += 1

        # Clean up stale locations
        removed_count = self.index_manager.clean_stale_locations(models_dir)
        result.removed_count = removed_count

        if removed_count > 0 and not self.quiet:
            logger.info(f"Cleaned up {removed_count} stale locations")

        if not self.quiet:
            logger.info(f"Scan complete: {result.added_count} added, {result.updated_count} updated, {result.skipped_count} skipped")

        # Notify progress of completion
        if progress:
            progress.on_scan_complete(result)

        return result

    def _process_model_file(self, file_path: Path, models_dir: Path) -> ModelProcessResult:
        """Process a model file and add it to the index.

        Args:
            file_path: Path to the model file
            models_dir: Base models directory

        Returns:
            Result of the processing operation
        """
        try:
            # Get file info
            file_stat = file_path.stat()
            relative_path = file_path.relative_to(models_dir).as_posix()
            filename = file_path.name

            # Calculate hash
            short_hash = self.index_manager.calculate_short_hash(file_path)

            # Check if model already exists
            if self.index_manager.has_model(short_hash):
                # Model exists, just add/update the location
                self.index_manager.add_location(short_hash, models_dir, relative_path, filename, file_stat.st_mtime)
                if not self.quiet:
                    logger.debug(f"Updated location for existing model: {relative_path}")
                return ModelProcessResult.UPDATED_PATH
            else:
                # New model - add to both tables
                self.index_manager.ensure_model(short_hash, file_stat.st_size)
                self.index_manager.add_location(short_hash, models_dir, relative_path, filename, file_stat.st_mtime)
                if not self.quiet:
                    logger.debug(f"Added new model: {relative_path}")
                return ModelProcessResult.ADDED

        except Exception as e:
            logger.error(f"Error processing model file {file_path}: {e}")
            raise

    def _update_result_counters(self, result: ScanResult, process_result: ModelProcessResult) -> None:
        """Update ScanResult counters based on processing result."""
        match process_result:
            case ModelProcessResult.ADDED:
                result.added_count += 1
            case ModelProcessResult.UPDATED_PATH:
                result.updated_count += 1
            case ModelProcessResult.SKIPPED_SAME_FILE:
                result.skipped_count += 1

    def _find_model_files(self, path: Path) -> list[Path]:
        """Find and filter valid model files in directory."""
        model_files = []
        total_found = 0
        skipped_hidden = 0
        skipped_not_file = 0
        skipped_small = 0
        skipped_validation = 0
        skipped_error = 0

        for file_path in path.rglob("*"):
            total_found += 1

            # Skip hidden directories (check only relative path parts, not absolute)
            try:
                relative_path = file_path.relative_to(path)
                if any(part.startswith('.') for part in relative_path.parts):
                    skipped_hidden += 1
                    continue
            except ValueError:
                # File not under base path - skip
                skipped_error += 1
                continue

            try:
                # Model libraries commonly use file symlinks to share large
                # weights between ComfyUI installations or expose a loader's
                # expected filename as an alias. ``Path.stat()`` and the hash
                # reader intentionally follow a valid file symlink, while the
                # indexed location remains the alias path under ``models/``.
                # Broken links and links to directories still fail is_file().
                if not file_path.is_file():
                    skipped_not_file += 1
                    continue

                # Skip small files
                file_size = file_path.stat().st_size
                if file_size < MIN_MODEL_SIZE:
                    skipped_small += 1
                    if not self.quiet:
                        logger.debug(f"Skipped (too small: {file_size} bytes): {file_path.name}")
                    continue

                # Apply config-based validation
                if not self._is_valid_model_file(file_path, path):
                    skipped_validation += 1
                    if not self.quiet:
                        logger.debug(f"Skipped (validation failed): {file_path.relative_to(path)}")
                    continue

                if not self.quiet:
                    logger.debug(f"Found valid model: {file_path.relative_to(path)}")
                model_files.append(file_path)

            except (OSError, PermissionError) as e:
                skipped_error += 1
                if not self.quiet:
                    logger.debug(f"Skipped (error: {e}): {file_path.name}")
                continue

        if not self.quiet:
            logger.debug(
                f"File scan summary: {total_found} total, {len(model_files)} valid, "
                f"{skipped_hidden} hidden, {skipped_not_file} not-file, "
                f"{skipped_small} small, {skipped_validation} validation-failed, {skipped_error} errors"
            )
        return model_files

    def _is_valid_model_file(self, file_path: Path, base_dir: Path) -> bool:
        """Check if file is valid based on directory-specific rules."""

        # Always exclude obviously non-model files
        if file_path.suffix.lower() in EXCLUDED_EXTENSIONS:
            if not self.quiet:
                logger.debug(f"  Excluded extension {file_path.suffix}: {file_path.name}")
            return False

        # Get the relative path to determine directory structure
        try:
            relative_path = file_path.relative_to(base_dir)
            if len(relative_path.parts) > 0:
                # First directory after base is the model type directory
                model_dir = relative_path.parts[0]

                if self.model_config.is_standard_directory(model_dir):
                    # Standard directory - use specific extensions
                    valid_extensions = self.model_config.get_extensions_for_directory(model_dir)
                    is_valid = file_path.suffix.lower() in valid_extensions
                    if not is_valid and not self.quiet:
                        logger.debug(
                            f"  Invalid extension for {model_dir}/: {file_path.suffix} "
                            f"(valid: {valid_extensions}) - {file_path.name}"
                        )
                    return is_valid
                else:
                    # Non-standard directory - be permissive (already excluded obvious non-models)
                    if not self.quiet:
                        logger.debug(f"  Non-standard directory {model_dir}/, allowing: {file_path.name}")
                    return True
        except ValueError as e:
            # File not under base_dir? Shouldn't happen with rglob
            if not self.quiet:
                logger.debug(f"  ValueError getting relative path: {e} - {file_path}")
            return False

        # Fallback: check against default extensions
        is_valid = file_path.suffix.lower() in self.model_config.default_extensions
        if not is_valid and not self.quiet:
            logger.debug(f"  Not in default extensions: {file_path.suffix} - {file_path.name}")
        return is_valid
