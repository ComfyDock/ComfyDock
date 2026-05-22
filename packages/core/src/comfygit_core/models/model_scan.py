"""Public model-index scan result and progress callback types."""

from dataclasses import dataclass


@dataclass
class ScanResult:
    """Result of model scanning operation."""

    scanned_count: int
    added_count: int
    updated_count: int
    skipped_count: int
    error_count: int
    errors: list[str]
    removed_count: int = 0


class ModelScanProgress:
    """Callback protocol for model scan progress updates."""

    def on_scan_start(self, total_files: int) -> None:
        """Called when scan starts with total file count."""
        pass

    def on_file_processed(self, current: int, total: int, filename: str) -> None:
        """Called after each file is processed."""
        pass

    def on_scan_complete(self, result: ScanResult) -> None:
        """Called when scan completes."""
        pass
