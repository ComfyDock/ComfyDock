"""Progress display utilities for downloads and model scanning."""

from collections.abc import Callable

from comfygit_core.models import (
    BatchDownloadCallbacks,
    ModelScanProgress,
    ModelWithLocation,
    ScanResult,
)

from .formatting import format_size


def create_progress_callback() -> Callable[[int, int | None], None]:
    """Create a reusable progress callback for model downloads.

    Returns:
        Callback function that displays download progress
    """
    def progress_callback(downloaded: int, total: int | None):
        """Display progress bar using carriage return."""
        downloaded_mb = downloaded / (1024 * 1024)
        if total:
            total_mb = total / (1024 * 1024)
            pct = (downloaded / total) * 100
            print(f"\rDownloading... {downloaded_mb:.1f} MB / {total_mb:.1f} MB ({pct:.0f}%)", end='', flush=True)
        else:
            print(f"\rDownloading... {downloaded_mb:.1f} MB", end='', flush=True)

    return progress_callback


def show_download_stats(model: ModelWithLocation | None) -> None:
    """Display statistics after successful download.

    Args:
        model: Downloaded and indexed model
    """
    if not model:
        return
    size_str = format_size(model.file_size)
    print(f"✓ Downloaded and indexed: {model.relative_path}")
    print(f"  Size: {size_str}")
    print(f"  Hash: {model.hash}")


def create_batch_download_callbacks() -> BatchDownloadCallbacks:
    """Create CLI callbacks for batch downloads with terminal output.

    Returns:
        BatchDownloadCallbacks configured for CLI rendering
    """
    def on_batch_start(count: int) -> None:
        print(f"\n⬇️  Downloading {count} model(s)...")

    def on_file_start(name: str, idx: int, total: int) -> None:
        print(f"\n[{idx}/{total}] {name}")

    def on_file_complete(name: str, success: bool, error: str | None) -> None:
        if success:
            print("  ✓ Complete")
        else:
            print(f"  ✗ Failed: {error}")

    def on_batch_complete(success: int, total: int) -> None:
        if success == total:
            print(f"\n✅ Downloaded {total} model(s)")
        elif success > 0:
            print(f"\n⚠️  Downloaded {success}/{total} models (some failed)")
        else:
            print(f"\n❌ All downloads failed (0/{total})")

    return BatchDownloadCallbacks(
        on_batch_start=on_batch_start,
        on_file_start=on_file_start,
        on_file_progress=create_progress_callback(),
        on_file_complete=on_file_complete,
        on_batch_complete=on_batch_complete
    )


class ModelSyncProgress(ModelScanProgress):
    """CLI progress display for model scanning with conditional visibility.

    Shows progress bar only when models are being processed (not just scanned).
    """

    def __init__(self):
        self.total_files = 0
        self.shown = False

    def on_scan_start(self, total_files: int) -> None:
        """Called when scan starts."""
        self.total_files = total_files
        # Show initial message - we'll update it as we go
        if total_files > 0:
            print("🔄 Syncing model index...", end='', flush=True)
            self.shown = True

    def on_file_processed(self, current: int, total: int, filename: str) -> None:
        """Update progress bar."""
        if self.shown and total > 100:  # Only show detailed progress for large directories
            print(f"\r🔄 Syncing model index... {current}/{total} files", end='', flush=True)

    def on_scan_complete(self, result: ScanResult) -> None:
        """Show summary only if there were changes."""
        has_changes = result.added_count > 0 or result.updated_count > 0

        if self.shown:
            if has_changes:
                # Clear progress line and show summary
                print("\r\033[K", end='')  # Clear line (carriage return + clear to end of line)
                changes = []
                if result.added_count > 0:
                    changes.append(f"{result.added_count} added")
                if result.updated_count > 0:
                    changes.append(f"{result.updated_count} updated")
                print(f"✓ Model index synced: {', '.join(changes)}")
            else:
                # Clear the line completely if no changes
                print("\r\033[K", end='', flush=True)  # Clear line completely
                # Don't print anything - silent when no changes


def create_model_sync_progress() -> ModelSyncProgress:
    """Create progress callback for model index syncing.

    Returns:
        ModelSyncProgress instance that conditionally displays progress
    """
    return ModelSyncProgress()
