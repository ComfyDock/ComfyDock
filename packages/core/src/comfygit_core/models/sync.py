"""Simplified sync models for ComfyGit - workflow sync removed."""

from dataclasses import dataclass, field


@dataclass
class UVSyncOutcome:
    """Typed outcome from uv dependency synchronization."""

    packages_synced: bool = False
    dependency_groups_installed: list[str] = field(default_factory=list)
    dependency_groups_failed: list[tuple[str, str]] = field(default_factory=list)
    dependency_groups_skipped: list[str] = field(default_factory=list)
    attempts: int = 0

    def to_dict(self) -> dict[str, object]:
        """Serialize for JSON/logging edges."""
        return {
            "packages_synced": self.packages_synced,
            "dependency_groups_installed": list(self.dependency_groups_installed),
            "dependency_groups_failed": list(self.dependency_groups_failed),
            "dependency_groups_skipped": list(self.dependency_groups_skipped),
            "attempts": self.attempts,
        }


@dataclass
class SyncResult:
    """Result from environment sync operation - no workflow sync anymore."""

    # Package sync
    packages_synced: bool = False

    # Dependency groups
    dependency_groups_installed: list[str] = field(default_factory=list)  # Group names
    dependency_groups_failed: list[tuple[str, str]] = field(default_factory=list)  # (group_name, error)
    dependency_groups_skipped: list[str] = field(default_factory=list)

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
