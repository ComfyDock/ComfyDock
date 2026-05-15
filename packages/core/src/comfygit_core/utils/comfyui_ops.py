from pathlib import Path

from ..logging.logging_config import get_logger
from .common import run_command
from .git import git_clone

logger = get_logger(__name__)


def validate_comfyui_installation(comfyui_path: Path) -> bool:
    """Check if a directory contains a valid ComfyUI installation.

    Args:
        comfyui_path: Path to check

    Returns:
        True if valid ComfyUI installation, False otherwise
    """
    # Check for essential ComfyUI files
    required_files = ["main.py", "nodes.py", "folder_paths.py"]

    for file in required_files:
        if not (comfyui_path / file).exists():
            return False

    # Check for essential directories
    required_dirs = ["comfy", "models"]

    for dir_name in required_dirs:
        if not (comfyui_path / dir_name).is_dir():
            return False

    return True


def get_comfyui_version(comfyui_path: Path) -> str:
    """Detect ComfyUI version from git tags."""
    comfyui_version = "unknown"
    try:
        git_dir = comfyui_path / ".git"
        if git_dir.exists():
            result = run_command(
                ["git", "describe", "--tags", "--always"], cwd=comfyui_path
            )
            if result.returncode == 0:
                comfyui_version = result.stdout.strip()
    except Exception as e:
        logger.debug(f"Could not detect ComfyUI version from {comfyui_path}: {e}")

    return comfyui_version


def resolve_comfyui_version(
    version_spec: str | None,
    github_client
) -> tuple[str, str, str | None]:
    """Resolve version specification to concrete version.

    Args:
        version_spec: User input ("latest", "v0.3.20", "abc123", "main", None)
        github_client: GitHub client for API calls

    Returns:
        Tuple of (version_to_clone, version_type, commit_sha)
        - version_to_clone: What to pass to git clone
        - version_type: "release" | "commit" | "branch"
        - commit_sha: Actual commit SHA (None if not yet cloned)

    Examples:
        None → ("v0.3.20", "release", None)  # Latest release
        "latest" → ("v0.3.20", "release", None)
        "v0.3.15" → ("v0.3.15", "release", None)
        "abc123" → ("abc123", "commit", None)
        "master" → ("master", "branch", None)
    """
    COMFYUI_REPO = "https://github.com/comfyanonymous/ComfyUI.git"

    # Handle None or "latest" - fetch latest release
    if version_spec is None or version_spec == "latest":
        repo_info = github_client.get_repository_info(COMFYUI_REPO)
        if repo_info and repo_info.latest_release:
            return (repo_info.latest_release, "release", None)
        else:
            logger.warning("No releases found, falling back to master branch")
            return ("master", "branch", None)

    # Handle release tags (starts with 'v')
    if version_spec.startswith('v'):
        # Validate release exists
        if github_client.validate_version_exists(COMFYUI_REPO, version_spec):
            return (version_spec, "release", None)
        else:
            logger.warning(f"Release {version_spec} not found on GitHub")
            raise ValueError(f"ComfyUI release {version_spec} does not exist")

    # Handle branch alias (ComfyUI only has master branch)
    if version_spec == "master":
        return (version_spec, "branch", None)

    # Assume commit hash
    return (version_spec, "commit", None)


def clone_comfyui(target_path: Path, version: str | None = None) -> str | None:
    """Clone ComfyUI repository to a target path.

    Args:
        target_path: Where to clone ComfyUI
        version: Optional specific version/tag/commit to checkout

    Returns:
        ComfyUI version string (commit hash or tag)

    Raises:
        RuntimeError: If cloning fails
    """
    # Clone the repository with shallow clone for speed
    git_clone(
        "https://github.com/comfyanonymous/ComfyUI.git",
        target_path,
        depth=1,
        ref=version,
        timeout=5 * 60,
    )
    return get_comfyui_version(target_path)
