# models/exceptions.py

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ..utils.conflict_analyzer import ConflictAnalysis


class ComfyDockError(Exception):
    """Base exception for ComfyDock errors."""
    pass

# ====================================================
# Workspace exceptions
# ====================================================

class CDWorkspaceNotFoundError(ComfyDockError):
    """Workspace doesn't exist."""
    pass

class CDWorkspaceExistsError(ComfyDockError):
    """Workspace already exists."""
    pass

class CDWorkspaceError(ComfyDockError):
    """Workspace-related errors."""
    pass

# ===================================================
# Environment exceptions
# ===================================================

class CDEnvironmentError(ComfyDockError):
    """Environment-related errors."""
    pass

class CDEnvironmentNotFoundError(ComfyDockError):
    """Environment doesn't exist."""
    pass

class CDEnvironmentExistsError(ComfyDockError):
    """Environment already exists."""
    pass

# ===================================================
# Resolution exceptions
# ==================================================

class CDResolutionError(ComfyDockError):
    """Resolution errors."""
    pass

# ===================================================
# Node exceptions
# ===================================================

class CDNodeNotFoundError(ComfyDockError):
    """Raised when Node not found."""
    pass

@dataclass
class NodeAction:
    """Represents a possible action to resolve an error."""
    action_type: Literal[
        'remove_node',
        'add_node_dev',
        'add_node_force',
        'add_node_version',
        'rename_directory',
        'update_node',
        'add_constraint',
        'skip_node'
    ]

    # Parameters needed for the action
    node_identifier: str | None = None
    node_name: str | None = None
    directory_name: str | None = None
    new_name: str | None = None
    package_name: str | None = None  # For add_constraint action

    # Human-readable description (client-agnostic)
    description: str = ""


@dataclass
class NodeConflictContext:
    """Context about what conflicted and why."""
    conflict_type: Literal[
        'already_tracked',
        'directory_exists_non_git',
        'directory_exists_no_remote',
        'same_repo_exists',
        'different_repo_exists',
        'dev_node_replacement',
        'user_cancelled'
    ]

    node_name: str
    identifier: str | None = None
    existing_identifier: str | None = None
    filesystem_path: str | None = None
    local_remote_url: str | None = None
    expected_remote_url: str | None = None
    is_development: bool = False

    # Suggested actions
    suggested_actions: list[NodeAction] = field(default_factory=list)


class CDNodeConflictError(ComfyDockError):
    """Raised when Node has conflicts with enhanced context."""

    def __init__(self, message: str, context: NodeConflictContext | None = None):
        super().__init__(message)
        self.context = context

    def get_actions(self) -> list[NodeAction]:
        """Get suggested actions for resolving this conflict."""
        return self.context.suggested_actions if self.context else []


@dataclass
class DependencyConflictContext:
    """Context about dependency conflicts during node installation."""

    # The node being added
    node_name: str

    # Broad failure class used by frontends to decide whether a dependency
    # review preview is useful.
    conflict_kind: str = "resolution_conflict"

    # Parsed conflict information
    conflicting_packages: list[tuple[str, str]] = field(default_factory=list)  # Package pairs that conflict
    conflict_descriptions: list[str] = field(default_factory=list)  # Simplified conflict messages

    # Raw UV stderr for verbose mode
    raw_stderr: str = ""

    # Suggested resolutions
    suggested_actions: list[NodeAction] = field(default_factory=list)

    # Deep conflict analysis (optional - only populated when analysis succeeds)
    conflict_analysis: "ConflictAnalysis | None" = None


class CDDependencyConflictError(ComfyDockError):
    """Raised when dependency resolution fails during node installation."""

    def __init__(self, message: str, context: DependencyConflictContext | None = None):
        super().__init__(message)
        self.context = context

    def get_actions(self) -> list[NodeAction]:
        """Get suggested actions for resolving this conflict."""
        return self.context.suggested_actions if self.context else []


class CDDependencyPreviewStaleError(ComfyDockError):
    """Raised when a reviewed dependency preview no longer matches current state."""
    pass

# ===================================================
# Registry exceptions
# ===================================================

class CDRegistryError(ComfyDockError):
    """Base class for registry errors."""
    pass

class CDRegistryAuthError(CDRegistryError):
    """Authentication/authorization errors with registry."""
    pass

class CDRegistryServerError(CDRegistryError):
    """Registry server errors (5xx)."""
    pass

class CDRegistryConnectionError(CDRegistryError):
    """Network/connection errors to registry."""
    pass

class CDRegistryDataError(ComfyDockError):
    """Registry data is not available or cannot be loaded.

    This error indicates that registry node mappings are missing or corrupted.
    Recovery typically involves downloading or updating the registry data.
    """

    def __init__(
        self,
        message: str,
        cache_path: str | None = None,
        can_retry: bool = True
    ):
        super().__init__(message)
        self.cache_path = cache_path
        self.can_retry = can_retry

# ===================================================
# Pyproject exceptions
# ===================================================

class CDPyprojectError(ComfyDockError):
    """Errors related to pyproject.toml operations."""
    pass

class CDPyprojectNotFoundError(CDPyprojectError):
    """pyproject.toml file not found."""
    pass

class CDPyprojectInvalidError(CDPyprojectError):
    """pyproject.toml file is invalid or corrupted."""
    pass

# ===================================================
# Dependency exceptions
# ===================================================

class CDDependencyError(ComfyDockError):
    """Dependency-related errors."""
    pass

class CDPackageSyncError(CDDependencyError):
    """Package synchronization errors."""
    pass

# ===================================================
# Index exceptions
# ===================================================

class CDIndexError(ComfyDockError):
    """Index configuration errors."""
    pass

# ===================================================
# Process/Command exceptions
# ===================================================

class CDProcessError(ComfyDockError):
    """Raised when subprocess command execution fails."""

    def __init__(
        self,
        message: str,
        command: list[str] | None = None,
        stderr: str | None = None,
        stdout: str | None = None,
        returncode: int | None = None,
    ):
        super().__init__(message)
        self.command = command
        self.stderr = stderr
        self.stdout = stdout
        self.returncode = returncode


# ===================================================
# UV exceptions
# ==================================================

class UVNotInstalledError(ComfyDockError):
    """Raised when UV is not installed."""
    pass


class UVCommandError(ComfyDockError):
    """Raised when UV command execution fails."""

    def __init__(
        self,
        message: str,
        command: list[str] | None = None,
        stderr: str | None = None,
        stdout: str | None = None,
        returncode: int | None = None,
    ):
        super().__init__(message)
        self.command = command
        self.stderr = stderr
        self.stdout = stdout
        self.returncode = returncode

    def __str__(self) -> str:
        """Include stderr/stdout in string representation for better error messages."""
        parts = [super().__str__()]

        if self.stderr and self.stderr.strip():
            parts.append(f"\nStderr: {self.stderr.strip()}")

        if self.stdout and self.stdout.strip():
            parts.append(f"\nStdout: {self.stdout.strip()}")

        return "".join(parts)


# ===================================================
# Export/Import exceptions
# ===================================================

@dataclass
class ExportErrorContext:
    """Context about an export failure."""
    uncommitted_workflows: list[str] = field(default_factory=list)
    uncommitted_git_changes: bool = False
    has_unresolved_issues: bool = False


class CDExportError(ComfyDockError):
    """Export operation failed with detailed context."""

    def __init__(self, message: str, context: ExportErrorContext | None = None):
        super().__init__(message)
        self.context = context

    @property
    def uncommitted_workflows(self) -> list[str] | None:
        """Get list of uncommitted workflows for backward compatibility."""
        return self.context.uncommitted_workflows if self.context else None


# ===================================================
# Model Download exceptions
# ===================================================

@dataclass
class DownloadErrorContext:
    """Detailed context about a download failure."""
    provider: str  # 'civitai', 'huggingface', 'custom'
    error_category: str  # 'auth_missing', 'auth_invalid', 'forbidden', 'not_found', 'network', 'server', 'unknown'
    http_status: int | None
    url: str
    has_configured_auth: bool  # Was auth configured (even if invalid)?
    raw_error: str  # Original error message for debugging

    def get_user_message(self) -> str:
        """Generate user-friendly error message."""
        if self.provider == "civitai":
            if self.error_category == "auth_missing":
                return (
                    f"CivitAI model requires authentication (HTTP {self.http_status}). "
                    "No API key found. Get your key from https://civitai.com/user/account "
                    "and add it with: cg config --civitai-key <your-key>"
                )
            elif self.error_category == "auth_invalid":
                return (
                    f"CivitAI authentication failed (HTTP {self.http_status}). "
                    "Your API key may be invalid or expired. "
                    "Update it with: cg config --civitai-key <your-key>"
                )
            elif self.error_category == "forbidden":
                return (
                    f"CivitAI access forbidden (HTTP {self.http_status}). "
                    "This model may require special permissions or may not be publicly available."
                )
            elif self.error_category == "not_found":
                return f"CivitAI model not found (HTTP {self.http_status}). The URL may be incorrect or the model was removed."

        elif self.provider == "huggingface":
            if self.error_category == "auth_missing":
                return (
                    f"HuggingFace model requires authentication (HTTP {self.http_status}). "
                    f"Configure your token in Settings → API Credentials, or set the HF_TOKEN environment variable. "
                    f"Get your token from: https://huggingface.co/settings/tokens"
                )
            elif self.error_category == "auth_invalid":
                return (
                    f"HuggingFace authentication failed (HTTP {self.http_status}). "
                    f"Your token may be invalid or expired. Update it in Settings → API Credentials, "
                    f"or check your HF_TOKEN environment variable. "
                    f"Get a new token from: https://huggingface.co/settings/tokens"
                )
            elif self.error_category == "not_found":
                return f"HuggingFace model not found (HTTP {self.http_status}). Check the URL is correct."

        # Generic provider or fallback
        if self.error_category == "network":
            return f"Network error downloading from {self.provider}: {self.raw_error}"
        elif self.error_category == "server":
            return f"Server error from {self.provider} (HTTP {self.http_status}). Try again later."
        elif self.http_status:
            return f"Download failed from {self.provider} (HTTP {self.http_status}): {self.raw_error}"
        else:
            return f"Download failed from {self.provider}: {self.raw_error}"


class CDModelDownloadError(ComfyDockError):
    """Model download error with provider-specific context."""

    def __init__(
        self,
        message: str,
        context: DownloadErrorContext | None = None,
        failures: list[tuple[str, str]] | None = None
    ):
        super().__init__(message)
        self.context = context
        self.failures = failures or []

    def get_user_message(self) -> str:
        """Get user-friendly error message."""
        if self.context:
            return self.context.get_user_message()
        return str(self)
