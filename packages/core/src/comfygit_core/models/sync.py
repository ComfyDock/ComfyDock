"""Simplified sync models for ComfyGit - workflow sync removed."""

from dataclasses import dataclass, field


@dataclass
class SyncResult:
    """Result from environment sync operation - no workflow sync anymore."""

    # Package sync
    packages_synced: bool = False

    # Dependency groups
    dependency_groups_installed: list[str] = field(default_factory=list)  # Group names
    dependency_groups_failed: list[tuple[str, str]] = field(default_factory=list)  # (group_name, error)

    # Node sync
    nodes_installed: list[str] = field(default_factory=list)
    nodes_removed: list[str] = field(default_factory=list)
    nodes_updated: list[str] = field(default_factory=list)

    # Model paths
    model_paths_configured: bool = False

    # Model downloads
    models_downloaded: list[str] = field(default_factory=list)  # Filenames
    models_failed: list[tuple[str, str]] = field(default_factory=list)  # (filename, error)

    # Overall status
    success: bool = True
    errors: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """Check if any changes were made during sync."""
        return (
            self.packages_synced or
            bool(self.nodes_installed) or
            bool(self.nodes_removed) or
            bool(self.nodes_updated)
        )
