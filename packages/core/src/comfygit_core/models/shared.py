"""Core shared data models"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from comfygit_core.models.registry import RegistryNodeInfo

from ..utils.model_categories import get_model_category
from .exceptions import ComfyDockError

if TYPE_CHECKING:
    from comfygit_core.models.manifest import ManifestModel

NODE_CRITICALITY_REQUIRED = "required"
NODE_CRITICALITY_OPTIONAL = "optional"
NODE_CRITICALITY_VALUES = frozenset({NODE_CRITICALITY_REQUIRED, NODE_CRITICALITY_OPTIONAL})


def normalize_node_criticality(value: str | None) -> str:
    """Return a valid custom-node criticality, defaulting omitted values to required."""
    if value is None:
        return NODE_CRITICALITY_REQUIRED
    if value not in NODE_CRITICALITY_VALUES:
        allowed = ", ".join(sorted(NODE_CRITICALITY_VALUES))
        raise ValueError(f"Invalid node criticality: {value!r}. Expected one of: {allowed}")
    return value


@dataclass
class NodeInfo:
    """Complete information about a custom node across its lifecycle.

    This dataclass represents a custom node from initial user input through resolution,
    persistence in pyproject.toml, and final installation to the filesystem. Since custom
    nodes have no cross-dependencies, all version/URL information is pinned directly in
    pyproject.toml (no separate lock file needed).

    Lifecycle phases:

    1. User Input → Resolution:
       - User provides: registry_id OR repository URL OR local directory name
       - System resolves to complete NodeInfo with all applicable fields populated

    2. Persistence (pyproject.toml):
       - All resolved fields stored in [tool.comfygit.nodes.<identifier>]
       - Explicitly pins version and download location for reproducibility

    3. Installation (filesystem sync):
       - Uses download_url (registry) or repository+version (git) to fetch code
       - Installs to custom_nodes/<name>/

    Field usage by source type:

    Registry nodes:
        name: Directory name from registry metadata
        registry_id: Comfy Registry package ID (required for re-resolution)
        version: Registry version string (e.g., "2.50")
        download_url: Direct download URL from registry API
        source: "registry"
        dependency_sources: UV sources added for node's Python deps

    GitHub nodes:
        name: Repository name from GitHub API
        repository: Full git clone URL (https://github.com/user/repo)
        version: Git commit hash for pinning exact version
        registry_id: Optional, if node also exists in registry (for dual-source)
        source: "git"
        dependency_sources: UV sources added for node's Python deps

    Development nodes (local):
        name: Directory name from filesystem
        version: Always "dev"
        source: "development"
        dependency_sources: UV sources added for node's Python deps
        (All other fields None - code already exists locally)
    """

    # Core identification (always present)
    name: str  # Directory name in custom_nodes/

    # Source-specific identifiers (mutually exclusive by source type)
    registry_id: str | None = None      # Comfy Registry package ID
    repository: str | None = None       # Git clone URL

    # Resolution data (populated during node resolution)
    version: str | None = None          # Registry version, git commit hash, or "dev"
    download_url: str | None = None     # Direct download URL (registry nodes only)

    # Metadata
    source: str = "unknown"             # "registry", "git", "development", or "unknown"
    dependency_sources: list[str] | None = None  # UV source names added for this node's deps
    criticality: str = NODE_CRITICALITY_REQUIRED  # "required" or "optional"

    # Git reference fields for dev nodes (optional, used for sharing)
    branch: str | None = None           # Branch to track (e.g., "dev", "main")
    pinned_commit: str | None = None    # Commit hash for exact portable reconstruction

    def __post_init__(self) -> None:
        self.criticality = normalize_node_criticality(self.criticality)

    @property
    def identifier(self) -> str:
        """Get the best identifier for this node."""
        return self.name

    @classmethod
    def from_registry_node(cls, registry_node_info: RegistryNodeInfo):
        return cls(
            name=registry_node_info.name,
            registry_id=registry_node_info.id,
            repository=registry_node_info.repository,  # Preserve repository for git fallback
            version=registry_node_info.latest_version.version if registry_node_info.latest_version else None,
            download_url=registry_node_info.latest_version.download_url if registry_node_info.latest_version else None,
            source="registry"
        )

    @classmethod
    def from_global_package(cls, package, version: str | None = None):
        """Create NodeInfo from GlobalNodePackage (cached mappings data).

        Args:
            package: GlobalNodePackage from node mappings repository
            version: Specific version to use, or None for latest

        Returns:
            NodeInfo instance
        """
        from packaging.version import InvalidVersion, Version

        # Determine version to use
        if version is None:
            # Get latest version using semantic version comparison
            if package.versions:
                try:
                    version = max(package.versions.keys(), key=Version)
                except InvalidVersion:
                    # Fall back to string comparison if versions aren't valid semver
                    version = max(package.versions.keys())
            else:
                version = None

        # Get version-specific data
        version_data = None
        download_url = None
        if version and package.versions:
            version_data = package.versions.get(version)
            if version_data:
                download_url = version_data.download_url

        return cls(
            name=package.display_name or package.id,
            registry_id=package.id,
            repository=package.repository,
            version=version,
            download_url=download_url,
            source="registry"
        )

    @classmethod
    def from_pyproject_config(cls, pyproject_config: dict, node_identifier: str) -> "NodeInfo | None":
        if not pyproject_config:
            return None
        node_config = pyproject_config.get(node_identifier)
        if not node_config:
            return None
        name = node_config.get("name")
        if not name:
            return None
        return cls(
            name=name,
            version=node_config.get("version"),
            source=node_config.get("source", "unknown"),
            download_url=node_config.get("download_url"),
            registry_id=node_config.get("registry_id"),
            repository=node_config.get("repository"),
            dependency_sources=node_config.get("dependency_sources"),
            criticality=normalize_node_criticality(node_config.get("criticality")),
            branch=node_config.get("branch"),
            pinned_commit=node_config.get("pinned_commit"),
        )

@dataclass
class NodePackage:
    """Complete package for a node including info and requirements."""
    node_info: NodeInfo
    requirements: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.node_info.name

    @property
    def identifier(self) -> str:
        """Get the best identifier for this node."""
        return self.node_info.registry_id or self.node_info.name


@dataclass
class UpdateResult:
    """Result from updating a node."""
    node_name: str
    source: str  # 'development', 'registry', 'git'
    changed: bool = False
    message: str = ""

    # For development nodes
    requirements_added: list[str] = field(default_factory=list)
    requirements_removed: list[str] = field(default_factory=list)

    # For registry/git nodes
    old_version: str | None = None
    new_version: str | None = None

@dataclass
class NodeRemovalResult:
    """Result from removing a node."""
    identifier: str
    name: str
    source: str  # 'development', 'registry', 'git'
    filesystem_action: str  # 'disabled', 'deleted'
    sync_succeeded: bool = True
    sync_error: str | None = None
    needs_sync: bool = False


@dataclass
class NodeDevLinkResult:
    """Result from linking a custom node to a local development checkout."""

    identifier: str
    name: str
    source_path: str
    link_path: str
    backup_path: str | None = None
    already_linked: bool = False
    requirements_changed: bool = False
    needs_restart: bool = True


# Progress and Utility Models

@dataclass
class ProgressContext:
    """Context for nested progress tracking."""
    task: str
    start_time: float
    total_items: int | None = None
    current_item: int = 0


# Model Management Models

@dataclass
class TrackedDirectory:
    """Tracked model directory configuration."""
    id: str
    path: str
    added_at: str
    last_sync: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'TrackedDirectory':
        """Create instance from dictionary."""
        return cls(**data)

@dataclass
class ModelInfo:
    """Core model identity (unique by hash)."""
    file_size: int
    blake3_hash: str | None = None
    sha256_hash: str | None = None
    short_hash: str = ""

    def validate(self) -> None:
        """Validate model information."""
        if self.file_size <= 0:
            raise ComfyDockError("File size must be positive")
        # blake3_hash can be empty initially - will be filled when needed

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'ModelInfo':
        """Create instance from dictionary."""
        return cls(**data)


@dataclass
class ModelLocation:
    """A location where a model exists in the filesystem."""
    model_hash: str
    relative_path: str
    filename: str
    mtime: float
    last_seen: int
    id: int | None = None
    base_directory: str | None = None
    observation_state: str | None = None
    present: bool | None = None
    changed: bool | None = None
    is_symlink: bool | None = None
    symlink_target: str | None = None
    target_present: bool | None = None
    independently_usable: bool | None = None
    observed_size: int | None = None
    observed_mtime: float | None = None

    def validate(self) -> None:
        """Validate model location."""
        if not self.model_hash:
            raise ComfyDockError("Model hash cannot be empty")
        if not self.filename:
            raise ComfyDockError("Filename cannot be empty")
        if not self.relative_path:
            raise ComfyDockError("Relative path cannot be empty")

    @property
    def full_path(self) -> str | None:
        """Return the absolute indexed path when the base directory is known."""
        if not self.base_directory:
            return None
        return str(Path(self.base_directory) / self.relative_path)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        for key in (
            "observation_state",
            "present",
            "changed",
            "is_symlink",
            "symlink_target",
            "target_present",
            "independently_usable",
            "observed_size",
            "observed_mtime",
        ):
            if result[key] is None:
                result.pop(key)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'ModelLocation':
        """Create instance from dictionary."""
        return cls(
            id=data.get("id"),
            model_hash=data["model_hash"],
            base_directory=data.get("base_directory"),
            relative_path=data["relative_path"],
            filename=data["filename"],
            mtime=data["mtime"],
            last_seen=data["last_seen"],
            observation_state=data.get("observation_state"),
            present=data.get("present"),
            changed=data.get("changed"),
            is_symlink=data.get("is_symlink"),
            symlink_target=data.get("symlink_target"),
            target_present=data.get("target_present"),
            independently_usable=data.get("independently_usable"),
            observed_size=data.get("observed_size"),
            observed_mtime=data.get("observed_mtime"),
        )


@dataclass
class ModelWithLocation:
    """Combined model and location information for convenience."""
    hash: str
    file_size: int
    relative_path: str
    filename: str
    mtime: float
    last_seen: int
    base_directory: str | None = None
    blake3_hash: str | None = None
    sha256_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def category(self) -> str:
        """Get model category based on relative path.

        Returns the ComfyUI standard directory category (e.g., 'checkpoints', 'loras', 'vae')
        or 'custom' if the model is not in a standard directory.

        Returns:
            Category name or 'custom'
        """
        return get_model_category(self.relative_path)

    def validate(self) -> None:
        """Validate model with location entry."""
        if not self.hash:
            raise ComfyDockError("Hash cannot be empty")
        if not self.filename:
            raise ComfyDockError("Filename cannot be empty")
        if self.file_size <= 0:
            raise ComfyDockError("File size must be positive")
        if not self.relative_path:
            raise ComfyDockError("Relative path cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'ModelWithLocation':
        """Create instance from dictionary."""
        return cls(**data)


@dataclass
class ModelSourceStatus:
    """Status of a model's download sources."""
    model: "ManifestModel"
    available_locally: bool


@dataclass
class ModelSourceResult:
    """Result of adding a source to a model."""
    success: bool
    model: "ManifestModel | None" = None  # The model object (populated on success)
    error: str | None = None
    identifier: str | None = None  # Original identifier (hash or filename)
    model_hash: str | None = None  # Resolved hash
    source_type: str | None = None  # "civitai", "huggingface", "custom"
    url: str | None = None  # Added URL
    matches: list["ManifestModel"] | None = None  # For ambiguous filename errors


@dataclass
class ModelIndexSource:
    """A source URL recorded in the workspace model index."""
    type: str
    url: str
    metadata: dict[str, Any] = field(default_factory=dict)
    added_time: int = 0
    model_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelIndexSource":
        """Create instance from a repository source row."""
        return cls(
            type=str(data.get("type") or "custom"),
            url=str(data.get("url") or ""),
            metadata=dict(data.get("metadata") or {}),
            added_time=int(data.get("added_time") or 0),
            model_hash=data.get("model_hash"),
        )


@dataclass
class ModelIndexStats:
    """Summary counts for the workspace model index."""
    total_models: int = 0
    total_locations: int = 0
    total_sources: int = 0

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> "ModelIndexStats":
        """Create instance from a repository stats row."""
        return cls(
            total_models=int(data.get("total_models", 0)),
            total_locations=int(data.get("total_locations", 0)),
            total_sources=int(data.get("total_sources", 0)),
        )


@dataclass
class ModelDetails:
    """Complete model information including all locations and sources."""
    model: ModelWithLocation
    all_locations: list[ModelLocation]
    sources: list[ModelIndexSource]


@dataclass
class ModelDeleteResult:
    """Result of deleting model files and their index locations."""
    model_hash: str
    filename: str
    deleted_paths: list[str] = field(default_factory=list)
    missing_paths: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    remaining_locations: int = 0

    @property
    def status(self) -> str:
        return "partial" if self.errors else "success"


@dataclass
class ModelWithoutSourceInfo:
    """Information about a model missing source URLs during export."""
    filename: str
    hash: str
    workflows: list[str] = field(default_factory=list)


# Manager Status Models


@dataclass
class ManagerStatus:
    """Status of comfygit-manager installation in an environment.

    Used to check current installation state and determine if migration/update is needed.
    """
    current_version: str | None  # Version from pyproject.toml or detected from filesystem
    latest_version: str | None   # Latest version from ComfyUI Registry
    update_available: bool       # True if latest > current
    is_legacy: bool              # True if symlinked to workspace system_nodes
    is_tracked: bool             # True if tracked in pyproject.toml
    status: str = "unknown"      # "headless", "legacy", "not_installed", "outdated", "up_to_date"


@dataclass
class ManagerUpdateResult:
    """Result from updating comfygit-manager."""
    changed: bool                # Whether any change was made
    was_migration: bool = False  # True if migrated from legacy symlink
    old_version: str | None = None
    new_version: str | None = None
    message: str = ""


@dataclass
class LegacyCleanupResult:
    """Result from cleaning up legacy workspace artifacts."""
    success: bool                     # Whether cleanup was performed
    removed_path: str | None = None   # Path that was removed (as string)
    legacy_environments: list[str] = field(default_factory=list)  # Envs still using legacy
    message: str = ""
