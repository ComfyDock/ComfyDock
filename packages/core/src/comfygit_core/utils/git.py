"""Low-level git utilities for repository operations."""

import os
import re
import shutil
import subprocess
from pathlib import Path

from comfygit_core.models.exceptions import CDProcessError

from ..logging.logging_config import get_logger
from .common import run_command

logger = get_logger(__name__)


# =============================================================================
# Error Handling Utilities
# =============================================================================

def _is_not_found_error(error: CDProcessError) -> bool:
    """Check if a git error indicates something doesn't exist.

    Args:
        error: The CDProcessError from a git command

    Returns:
        True if this is a "not found" type error
    """
    not_found_messages = [
        "does not exist",
        "invalid object",
        "bad revision",
        "path not in",
        "unknown revision",
        "not a valid object",
        "pathspec"
    ]
    error_text = ((error.stderr or "") + str(error)).lower()
    return any(msg in error_text for msg in not_found_messages)


def _git(cmd: list[str], repo_path: Path,
         check: bool = True,
         not_found_msg: str | None = None,
         capture_output: bool = True,
         text: bool = True) -> subprocess.CompletedProcess:
    """Run git command with consistent error handling.

    Args:
        cmd: Git command arguments (without 'git' prefix)
        repo_path: Path to git repository
        check: Whether to raise exception on non-zero exit
        not_found_msg: Custom message for "not found" errors
        capture_output: Whether to capture stdout/stderr
        text: Whether to return text output

    Returns:
        CompletedProcess result

    Raises:
        ValueError: For "not found" type errors
        OSError: For other git command failures
    """
    try:
        return run_command(
            ["git"] + cmd,
            cwd=repo_path,
            check=check,
            capture_output=capture_output,
            text=text
        )
    except CDProcessError as e:
        if _is_not_found_error(e):
            raise ValueError(not_found_msg or "Git object not found") from e
        raise OSError(f"Git command failed: {e}") from e

# =============================================================================
# Configuration Operations
# =============================================================================

def git_config_get(repo_path: Path, key: str) -> str | None:
    """Get a git config value.

    Args:
        repo_path: Path to git repository
        key: Config key (e.g., "user.name")

    Returns:
        Config value or None if not set
    """
    result = _git(["config", key], repo_path, check=False)
    return result.stdout.strip() if result.returncode == 0 else None

def git_config_set(repo_path: Path, key: str, value: str) -> None:
    """Set a git config value locally.

    Args:
        repo_path: Path to git repository
        key: Config key (e.g., "user.name")
        value: Value to set

    Raises:
        OSError: If git config command fails
    """
    _git(["config", key, value], repo_path)

# =============================================================================
# URL Detection & Normalization
# =============================================================================

def is_git_url(url: str) -> bool:
    """Check if string is any git-style URL.

    Args:
        url: String to check

    Returns:
        True if URL appears to be a git repository URL
    """
    return url.startswith(('https://', 'http://', 'git@', 'ssh://'))

def is_github_url(url: str) -> bool:
    """Check if string is specifically a GitHub URL.

    Args:
        url: String to check

    Returns:
        True if URL is a GitHub repository URL
    """
    return url.startswith(('https://github.com/', 'git@github.com:', 'ssh://git@github.com/'))

def normalize_github_url(url: str) -> str:
    """Normalize GitHub URL to canonical https://github.com/owner/repo format.

    Handles various GitHub URL formats:
    - HTTPS: https://github.com/owner/repo.git
    - SSH: git@github.com:owner/repo.git
    - SSH URL: ssh://git@github.com/owner/repo.git

    Args:
        url: GitHub URL in any format

    Returns:
        Normalized URL in https://github.com/owner/repo format
    """
    if not url:
        return ""

    # Remove .git suffix
    url = re.sub(r"\.git$", "", url)

    # Parse URL
    from urllib.parse import urlparse
    parsed = urlparse(url)

    # Handle different GitHub URL formats
    if parsed.hostname in ("github.com", "www.github.com"):
        # Extract owner/repo from path
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) >= 2:
            owner, repo = path_parts[0], path_parts[1]
            return f"https://github.com/{owner}/{repo}"

    # For SSH URLs like git@github.com:owner/repo
    if url.startswith("git@github.com:"):
        repo_path = url.replace("git@github.com:", "")
        repo_path = re.sub(r"\.git$", "", repo_path)
        return f"https://github.com/{repo_path}"

    # For SSH URLs like ssh://git@github.com/owner/repo
    if url.startswith("ssh://git@github.com/"):
        repo_path = url.replace("ssh://git@github.com/", "")
        repo_path = re.sub(r"\.git$", "", repo_path)
        return f"https://github.com/{repo_path}"

    return url

# =============================================================================
# Repository Information
# =============================================================================

def parse_github_url(url: str) -> tuple[str, str, str | None] | None:
    """Parse GitHub URL to extract owner, repo name, and optional commit/ref.

    Args:
        url: GitHub repository URL

    Returns:
        Tuple of (owner, repo, commit) or None if invalid.
        commit will be None if no specific commit is specified.
    """
    # Handle URLs with commit/tree/blob paths like:
    # https://github.com/owner/repo/tree/commit-hash
    # https://github.com/owner/repo/commit/commit-hash
    github_match = re.match(
        r"(?:https?://github\.com/|git@github\.com:)([^/]+)/([^/\.]+)(?:\.git)?(?:/(?:tree|commit|blob)/([^/]+))?",
        url,
    )
    if github_match:
        owner = github_match.group(1)
        repo = github_match.group(2)
        commit = github_match.group(3)  # Will be None if not present
        return (owner, repo, commit)
    return None

def parse_git_url_with_subdir(url: str) -> tuple[str, str | None]:
    """Parse git URL with optional subdirectory specification.

    Supports syntax: <git_url>#<subdirectory_path>

    Examples:
        "https://github.com/user/repo"
        → ("https://github.com/user/repo", None)

        "https://github.com/user/repo#examples/example1"
        → ("https://github.com/user/repo", "examples/example1")

        "git@github.com:user/repo.git#workflows/prod"
        → ("git@github.com:user/repo.git", "workflows/prod")

    Args:
        url: Git URL with optional #subdirectory suffix

    Returns:
        Tuple of (base_git_url, subdirectory_path or None)
    """
    if '#' not in url:
        return url, None

    # Split on last # to handle edge cases
    base_url, subdir = url.rsplit('#', 1)

    # Normalize subdirectory path
    subdir = subdir.strip('/')

    if not subdir:
        # URL ended with # but no path
        return base_url, None

    return base_url, subdir

def git_rev_parse(repo_path: Path, ref: str = "HEAD", abbrev_ref: bool = False) -> str | None:
    """Parse a git reference to get its value.

    Args:
        repo_path: Path to git repository
        ref: Reference to parse (default: HEAD)
        abbrev_ref: If True, get abbreviated ref name

    Returns:
        Parsed reference value or None if command fails
    """
    cmd = ["rev-parse"]
    if abbrev_ref:
        cmd.append("--abbrev-ref")
    cmd.append(ref)

    result = _git(cmd, repo_path, check=False)
    return result.stdout.strip() if result.returncode == 0 else None

def git_describe_tags(repo_path: Path, exact_match: bool = False, abbrev: int | None = None) -> str | None:
    """Describe HEAD using tags.

    Args:
        repo_path: Path to git repository
        exact_match: If True, only exact tag match
        abbrev: If 0, only exact matches; if specified, abbreviate to N commits

    Returns:
        Tag description or None if no tags found
    """
    cmd = ["describe", "--tags"]
    if exact_match:
        cmd.append("--exact-match")
    if abbrev is not None:
        cmd.append(f"--abbrev={abbrev}")

    result = _git(cmd, repo_path, check=False)
    return result.stdout.strip() if result.returncode == 0 else None

def git_remote_get_url(repo_path: Path, remote: str = "origin") -> str | None:
    """Get URL of a git remote.

    Args:
        repo_path: Path to git repository
        remote: Remote name (default: origin)

    Returns:
        Remote URL or None if not found
    """
    result = _git(["remote", "get-url", remote], repo_path, check=False)
    return result.stdout.strip() if result.returncode == 0 else None

# =============================================================================
# Basic Git Operations
# =============================================================================

def git_init(repo_path: Path) -> None:
    """Initialize a git repository with 'main' as the default branch.

    Args:
        repo_path: Path to initialize as git repository

    Raises:
        OSError: If git initialization fails
    """
    _git(["init", "--initial-branch=main"], repo_path)

def git_diff(repo_path: Path, file_path: Path) -> str:
    """Get git diff for a specific file.

    Args:
        repo_path: Path to git repository
        file_path: Path to file to diff

    Returns:
        Git diff output as string

    Raises:
        OSError: If git diff command fails
    """
    result = _git(["diff", str(file_path)], repo_path)
    return result.stdout

def git_commit(repo_path: Path, message: str, add_all: bool = True) -> None:
    """Commit changes with optional staging.

    Args:
        repo_path: Path to git repository
        message: Commit message
        add_all: Whether to stage all changes first

    Raises:
        OSError: If git commands fail
    """
    if add_all:
        _git(["add", "."], repo_path)

    # Check if there are any changes to commit
    status = _git(["status", "--porcelain"], repo_path)
    if not status.stdout.strip():
        # No changes to commit - this is not an error
        return

    _git(["commit", "-m", message], repo_path)

# =============================================================================
# Advanced Git Operations
# =============================================================================

def git_show(repo_path: Path, ref: str, file_path: Path, is_text: bool = True) -> str:
    """Show file content from a specific git ref.

    Args:
        repo_path: Path to git repository
        ref: Git reference (commit, branch, tag)
        file_path: Path to file to show
        is_text: Whether to treat file as text

    Returns:
        File content as string

    Raises:
        OSError: If git show command fails
        ValueError: If ref or file doesn't exist
    """
    cmd = ["show", f"{ref}:{file_path}"]
    if is_text:
        cmd.append("--text")
    result = _git(cmd, repo_path, not_found_msg=f"Git ref '{ref}' or file '{file_path}' does not exist")
    return result.stdout


def git_history(
    repo_path: Path,
    file_path: Path | None = None,
    pretty: str | None = None,
    max_count: int | None = None,
    follow: bool = False,
    oneline: bool = False,
    rev_range: str | None = None,
) -> str:
    """Get git history for a specific file.

    Args:
        repo_path: Path to git repository
        file_path: Path to file to get history for
        oneline: Whether to show one-line format
        follow: Whether to follow renames
        max_count: Maximum number of commits to return
        pretty: Git pretty format
        rev_range: Git revision range (e.g. "origin/main..HEAD")

    Returns:
        Git log output as string

    Raises:
        OSError: If git log command fails
    """
    cmd = ["log"]
    if follow:
        cmd.append("--follow")
    if oneline:
        cmd.append("--oneline")
    if max_count:
        cmd.append(f"--max-count={max_count}")
    if pretty:
        cmd.append(f"--pretty={pretty}")
    if rev_range:
        cmd.append(rev_range)
    if file_path:
        cmd.append("--")
        cmd.append(str(file_path))
    result = _git(cmd, repo_path)
    return result.stdout


def git_clone(
    url: str,
    target_path: Path,
    depth: int = 1,
    ref: str | None = None,
    timeout: int = 30,
) -> None:
    """Clone a git repository to a target path.

    Args:
        url: Git repository URL
        target_path: Directory to clone to
        depth: Clone depth (1 for shallow clone)
        ref: Optional specific ref (branch/tag/commit) to checkout
        timeout: Command timeout in seconds

    Raises:
        OSError: If git clone or checkout fails
        ValueError: If URL is invalid or ref doesn't exist
    """
    # Build clone command
    cmd = ["clone"]

    # For commit hashes, we need to clone without --depth and then checkout
    # For branches/tags, we can use --branch with depth
    is_commit_hash = ref and len(ref) == 40 and all(c in '0123456789abcdef' for c in ref.lower())

    if depth > 0 and not is_commit_hash:
        cmd.extend(["--depth", str(depth)])

    if ref and not is_commit_hash and not ref.startswith("refs/"):
        # If a specific branch/tag is requested, clone it directly
        cmd.extend(["--branch", ref])

    cmd.extend([url, str(target_path)])

    # Execute clone
    _git(cmd, Path.cwd(), not_found_msg=f"Git repository URL '{url}' does not exist")

    # If a specific commit hash was requested, checkout to it
    if is_commit_hash and ref:
        _git(["checkout", ref], target_path, not_found_msg=f"Commit '{ref}' does not exist")
    elif ref and ref.startswith("refs/"):
        # Handle refs/ style references
        _git(["checkout", ref], target_path, not_found_msg=f"Reference '{ref}' does not exist")

    logger.info(f"Successfully cloned {url} to {target_path}")

def git_clone_subdirectory(
    url: str,
    target_path: Path,
    subdir: str,
    depth: int = 1,
    ref: str | None = None,
    timeout: int = 30,
) -> None:
    """Clone a git repository and extract a specific subdirectory.

    Clones the entire repository to a temporary location, validates
    the subdirectory exists, then copies only that subdirectory to
    the target path.

    Args:
        url: Git repository URL (without #subdir)
        target_path: Directory to extract subdirectory contents to
        subdir: Subdirectory path within repository (e.g., "examples/example1")
        depth: Clone depth (1 for shallow clone)
        ref: Optional specific ref (branch/tag/commit) to checkout
        timeout: Command timeout in seconds

    Raises:
        OSError: If git clone fails
        ValueError: If subdirectory doesn't exist in repository
    """
    import tempfile

    # Clone to temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_repo = Path(temp_dir) / "repo"

        logger.info(f"Cloning {url} to temporary location for subdirectory extraction")
        git_clone(url, temp_repo, depth=depth, ref=ref, timeout=timeout)

        # Validate subdirectory exists
        subdir_path = temp_repo / subdir
        if not subdir_path.exists():
            # List available top-level directories for helpful error message
            available_dirs = [d.name for d in temp_repo.iterdir() if d.is_dir() and not d.name.startswith('.')]
            raise ValueError(
                f"Subdirectory '{subdir}' does not exist in repository. "
                f"Available top-level directories: {', '.join(available_dirs)}"
            )

        if not subdir_path.is_dir():
            raise ValueError(f"Path '{subdir}' exists but is not a directory")

        # Validate it's a ComfyGit environment
        pyproject_path = subdir_path / "pyproject.toml"
        if not pyproject_path.exists():
            raise ValueError(
                f"Subdirectory '{subdir}' does not contain pyproject.toml - "
                f"not a valid ComfyGit environment"
            )

        # Copy subdirectory contents to target
        logger.info(f"Extracting subdirectory '{subdir}' to {target_path}")
        shutil.copytree(subdir_path, target_path, dirs_exist_ok=True)

        logger.info(f"Successfully extracted {url}#{subdir} to {target_path}")

def git_checkout(repo_path: Path,
                target: str = "HEAD",
                files: list[str] | None = None,
                unstage: bool = False) -> None:
    """Universal checkout function for commits, branches, or specific files.

    Args:
        repo_path: Path to git repository
        target: What to checkout (commit, branch, tag)
        files: Specific files to checkout (None for all)
        unstage: Whether to unstage files after checkout

    Raises:
        OSError: If git command fails
        ValueError: If target doesn't exist
    """
    cmd = ["checkout", target]
    if files:
        cmd.extend(["--"] + files)

    _git(cmd, repo_path, not_found_msg=f"Git target '{target}' does not exist")

    # Optionally unstage files to leave them as uncommitted changes
    if unstage and files:
        _git(["reset", "HEAD"] + files, repo_path)
    elif unstage and not files:
        _git(["reset", "HEAD", "."], repo_path)

# =============================================================================
# Status & Change Tracking
# =============================================================================

def git_status_porcelain(repo_path: Path) -> list[tuple[str, str, str]]:
    """Get git status in porcelain format, parsed.

    Args:
        repo_path: Path to git repository

    Returns:
        List of tuples: (index_status, working_status, filename)
        Status characters follow git's convention:
        - 'M' = modified, 'A' = added, 'D' = deleted
        - '?' = untracked, ' ' = unmodified
    """
    result = _git(["status", "--porcelain"], repo_path)
    entries = []

    if result.stdout:
        for line in result.stdout.strip().split('\n'):
            if line and len(line) >= 3:
                index_status = line[0]
                working_status = line[1]
                filename = line[2:].lstrip()

                # Handle quoted filenames (spaces/special chars)
                if filename.startswith('"') and filename.endswith('"'):
                    filename = filename[1:-1].encode().decode('unicode_escape')

                entries.append((index_status, working_status, filename))

    return entries

def get_staged_changes(repo_path: Path) -> list[str]:
    """Get list of files that are staged (git added) but not committed.

    Args:
        repo_path: Path to the git repository

    Returns:
        List of file paths that are staged

    Raises:
        OSError: If git command fails
    """
    result = _git(["diff", "--cached", "--name-only"], repo_path)

    if result.stdout:
        return result.stdout.strip().split('\n')

    return []


def get_uncommitted_changes(repo_path: Path) -> list[str]:
    """Get list of files that have uncommitted changes (staged or unstaged).

    Args:
        repo_path: Path to the git repository

    Returns:
        List of file paths with uncommitted changes

    Raises:
        OSError: If git command fails
    """
    result = _git(["status", "--porcelain"], repo_path)

    if result.stdout:
        changes = []
        for line in result.stdout.strip().split('\n'):
            if line and len(line) >= 3:
                # Git status --porcelain format: "XY filename"
                # X = index status, Y = working tree status
                # But the spacing varies based on content:
                # "M  filename" = staged (M + space + space + filename)
                # " M filename" = unstaged (space + M + space + filename)
                # "MM filename" = both staged and unstaged

                # The first 2 characters are always status flags
                # Everything after position 2 contains spaces + filename
                remaining = line[2:]    # Everything after status characters

                # Skip any leading whitespace to get to filename
                filename = remaining.lstrip()
                if filename:  # Make sure filename is not empty
                    changes.append(filename)
        return changes

    return []

def git_ls_tree(repo_path: Path, ref: str, recursive: bool = False) -> str:
    """List files in a git tree object.

    Args:
        repo_path: Path to git repository
        ref: Git reference (commit, branch, tag)
        recursive: If True, recursively list all files

    Returns:
        Output with file paths, one per line

    Raises:
        OSError: If git command fails
        ValueError: If ref doesn't exist
    """
    cmd = ["ls-tree"]
    if recursive:
        cmd.append("-r")
    cmd.extend(["--name-only", ref])

    result = _git(cmd, repo_path, not_found_msg=f"Git ref '{ref}' does not exist")
    return result.stdout

def git_ls_files(repo_path: Path) -> str:
    """List all files tracked by git in the current working tree.

    Args:
        repo_path: Path to git repository

    Returns:
        Output with file paths, one per line

    Raises:
        OSError: If git command fails
    """
    result = _git(["ls-files"], repo_path)
    return result.stdout

# =============================================================================
# Pull/Push/Remote Operations
# =============================================================================

def git_fetch(
    repo_path: Path,
    remote: str = "origin",
    timeout: int = 30,
) -> str:
    """Fetch from remote.

    Args:
        repo_path: Path to git repository
        remote: Remote name (default: origin)
        timeout: Command timeout in seconds

    Returns:
        Fetch output

    Raises:
        ValueError: If remote doesn't exist
        OSError: If fetch fails (network, auth, etc.)
    """
    # Validate remote exists first
    remote_url = git_remote_get_url(repo_path, remote)
    if not remote_url:
        raise ValueError(
            f"Remote '{remote}' not configured. "
            f"Add with: cg remote add {remote} <url>"
        )

    cmd = ["fetch", remote]
    result = _git(cmd, repo_path)
    return result.stdout


def git_merge(
    repo_path: Path,
    ref: str,
    ff_only: bool = False,
    timeout: int = 30,
    strategy_option: str | None = None,
    allow_unrelated_histories: bool = False,
) -> str:
    """Merge a ref into current branch.

    Args:
        repo_path: Path to git repository
        ref: Ref to merge (e.g., "origin/main")
        ff_only: Only allow fast-forward merges (default: False)
        timeout: Command timeout in seconds
        strategy_option: Optional strategy option (e.g., "ours" or "theirs" for -X flag)
        allow_unrelated_histories: Allow merging unrelated histories (default: False)

    Returns:
        Merge output

    Raises:
        ValueError: If merge would conflict (when ff_only=True)
        OSError: If merge fails (including merge conflicts)
    """
    cmd = ["merge"]
    if ff_only:
        cmd.append("--ff-only")
    if strategy_option:
        cmd.extend(["-X", strategy_option])
    if allow_unrelated_histories:
        cmd.append("--allow-unrelated-histories")
    cmd.append(ref)

    try:
        result = _git(cmd, repo_path)
        return result.stdout
    except OSError as e:
        # _git() converts CDProcessError to OSError, but we can access the original via __cause__
        original_error = e.__cause__ if isinstance(e.__cause__, CDProcessError) else None

        # Check both error message and stderr for conflict indicators
        error_str = str(e).lower()
        stderr_str = ""
        returncode = None

        if original_error:
            stderr_str = (original_error.stderr or "").lower()
            returncode = original_error.returncode

        combined_error = error_str + " " + stderr_str

        if ff_only and "not possible to fast-forward" in combined_error:
            raise ValueError(
                f"Cannot fast-forward merge {ref}. "
                "Remote has diverged - resolve manually."
            ) from e

        # Check for unrelated histories error
        if "unrelated histories" in combined_error:
            raise OSError(
                f"Cannot merge {ref}: refusing to merge unrelated histories.\n"
                "Use --force to allow merging unrelated histories."
            ) from e

        # Check for merge conflict indicators (git uses "CONFLICT" in stderr)
        # Exit code 1 from git merge typically indicates a conflict
        if "conflict" in combined_error or returncode == 1:
            raise OSError(
                f"Merge conflict with {ref}. Resolve manually:\n"
                "  1. cd <env>/.cec\n"
                "  2. git status\n"
                "  3. Resolve conflicts and commit"
            ) from e
        raise


def git_pull(
    repo_path: Path,
    remote: str = "origin",
    branch: str | None = None,
    ff_only: bool = False,
    timeout: int = 30,
    strategy_option: str | None = None,
    force: bool = False,
) -> dict:
    """Fetch and merge from remote (pull operation).

    Args:
        repo_path: Path to git repository
        remote: Remote name (default: origin)
        branch: Branch name (default: auto-detect current branch)
        ff_only: Only allow fast-forward merges (default: False)
        timeout: Command timeout in seconds
        strategy_option: Optional strategy option (e.g., "ours" or "theirs" for -X flag)
        force: If True, allow unrelated histories merge (default: False)

    Returns:
        Dict with keys: 'fetch_output', 'merge_output', 'branch'

    Raises:
        ValueError: If remote doesn't exist, detached HEAD, or merge conflicts
        OSError: If fetch/merge fails
    """
    # Auto-detect current branch if not specified
    if not branch:
        branch = git_current_branch(repo_path)

    # Fetch first
    fetch_output = git_fetch(repo_path, remote, timeout)

    # Then merge
    merge_ref = f"{remote}/{branch}"
    merge_output = git_merge(
        repo_path,
        merge_ref,
        ff_only,
        timeout,
        strategy_option,
        allow_unrelated_histories=force,
    )

    return {
        'fetch_output': fetch_output,
        'merge_output': merge_output,
        'branch': branch,
    }


def git_push(
    repo_path: Path,
    remote: str = "origin",
    branch: str | None = None,
    force: bool = False,
    force_unsafe: bool = False,
    timeout: int = 30,
) -> str:
    """Push commits to remote.

    Args:
        repo_path: Path to git repository
        remote: Remote name (default: origin)
        branch: Branch to push (default: current branch)
        force: Use --force-with-lease first, then retry with --force if needed
        force_unsafe: Use --force directly (skip --force-with-lease)
        timeout: Command timeout in seconds

    Returns:
        Push output

    Raises:
        ValueError: If remote doesn't exist
        OSError: If push fails (auth, conflicts, network)
    """
    # Validate remote exists
    remote_url = git_remote_get_url(repo_path, remote)
    if not remote_url:
        raise ValueError(
            f"Remote '{remote}' not configured. "
            f"Add with: cg remote add {remote} <url>"
        )

    # If force pushing, fetch first to update remote refs for --force-with-lease
    if force and not force_unsafe:
        try:
            git_fetch(repo_path, remote, timeout)
        except Exception:
            # If fetch fails, continue anyway - user wants to force push
            pass

    cmd = ["push", remote]

    if branch:
        cmd.append(branch)

    if force_unsafe:
        # Dangerous: use --force directly
        cmd.append("--force")
    elif force:
        # Safe: use --force-with-lease (will fail if remote changed since last fetch)
        cmd.append("--force-with-lease")

    try:
        result = _git(cmd, repo_path)
        return result.stdout
    except OSError as e:
        # _git() converts CDProcessError to OSError
        original_error = e.__cause__ if isinstance(e.__cause__, CDProcessError) else None
        error_msg = str(e).lower()
        stderr_str = ""

        if original_error:
            stderr_str = (original_error.stderr or "").lower()

        combined_error = error_msg + " " + stderr_str

        if "permission denied" in combined_error or "authentication" in combined_error:
            raise OSError(
                "Authentication failed. Check SSH key or HTTPS credentials."
            ) from e

        # If --force-with-lease failed due to stale refs, and force=True, retry with --force
        if force and not force_unsafe and ("stale info" in combined_error or "rejected" in combined_error):
            logger.warning("--force-with-lease failed, retrying with --force")
            return git_push(repo_path, remote, branch, force=True, force_unsafe=True, timeout=timeout)

        if "rejected" in combined_error:
            raise OSError(
                "Push rejected - remote has changes. Run: cg pull first"
            ) from e

        raise OSError(f"Push failed: {e}") from e


def git_current_branch(repo_path: Path) -> str:
    """Get current branch name.

    Args:
        repo_path: Path to git repository

    Returns:
        Branch name (e.g., "main")

    Raises:
        ValueError: If in detached HEAD state
    """
    result = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    branch = result.stdout.strip()

    if branch == "HEAD":
        raise ValueError(
            "Detached HEAD state - cannot pull/push. "
            "Checkout a branch: git checkout main"
        )

    return branch


def git_reset_hard(repo_path: Path, commit: str) -> None:
    """Reset repository to specific commit, discarding all changes.

    Used for atomic rollback when pull+repair fails.

    Args:
        repo_path: Path to git repository
        commit: Commit SHA to reset to

    Raises:
        OSError: If git reset fails
    """
    _git(["reset", "--hard", commit], repo_path)


def git_remote_add(repo_path: Path, name: str, url: str) -> None:
    """Add a git remote.

    Args:
        repo_path: Path to git repository
        name: Remote name (e.g., "origin")
        url: Remote URL

    Raises:
        OSError: If remote already exists or add fails
    """
    # Check if remote already exists
    existing_url = git_remote_get_url(repo_path, name)
    if existing_url:
        raise OSError(f"Remote '{name}' already exists: {existing_url}")

    _git(["remote", "add", name, url], repo_path)


def git_remote_remove(repo_path: Path, name: str) -> None:
    """Remove a git remote.

    Args:
        repo_path: Path to git repository
        name: Remote name (e.g., "origin")

    Raises:
        ValueError: If remote doesn't exist
        OSError: If removal fails
    """
    # Check if remote exists
    existing_url = git_remote_get_url(repo_path, name)
    if not existing_url:
        raise ValueError(f"Remote '{name}' not found")

    _git(["remote", "remove", name], repo_path)


def git_remote_set_url(repo_path: Path, name: str, url: str, push: bool = False) -> None:
    """Set URL for a git remote.

    Args:
        repo_path: Path to git repository
        name: Remote name
        url: New URL
        push: If True, update push URL; otherwise update fetch URL

    Raises:
        ValueError: If remote doesn't exist
        OSError: If update fails
    """
    # Check if remote exists
    existing_url = git_remote_get_url(repo_path, name)
    if not existing_url:
        raise ValueError(f"Remote '{name}' not found")

    cmd = ["remote", "set-url"]
    if push:
        cmd.append("--push")
    cmd.extend([name, url])

    _git(cmd, repo_path)


def git_rev_list_count(repo_path: Path, left_ref: str, right_ref: str) -> tuple[int, int]:
    """Count commits ahead and behind between two refs.

    Uses symmetric difference (left...right) to count commits unique to each ref.

    Args:
        repo_path: Path to git repository
        left_ref: Left reference (e.g., "origin/main")
        right_ref: Right reference (e.g., "HEAD")

    Returns:
        Tuple of (left_only, right_only) counts - commits unique to each side
    """
    result = _git(
        ["rev-list", "--left-right", "--count", f"{left_ref}...{right_ref}"],
        repo_path,
        check=False
    )
    if result.returncode != 0:
        return (0, 0)

    parts = result.stdout.strip().split('\t')
    if len(parts) == 2:
        return (int(parts[0]), int(parts[1]))
    return (0, 0)


def git_rev_list_count_single(repo_path: Path, ref: str = "HEAD") -> int:
    """Count total commits reachable from a ref.

    Args:
        repo_path: Path to git repository
        ref: Reference to count from (default: HEAD)

    Returns:
        Number of commits, or 0 if ref doesn't exist
    """
    result = _git(["rev-list", "--count", ref], repo_path, check=False)
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def git_remote_list(repo_path: Path) -> list[tuple[str, str, str]]:
    """List all git remotes.

    Args:
        repo_path: Path to git repository

    Returns:
        List of tuples: [(name, url, type), ...]
        Example: [("origin", "https://...", "fetch"), ("origin", "https://...", "push")]
    """
    result = _git(["remote", "-v"], repo_path, check=False)

    if result.returncode != 0:
        return []

    remotes = []
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 3:
            name = parts[0]
            url = parts[1]
            remote_type = parts[2].strip('()')
            remotes.append((name, url, remote_type))

    return remotes


# =============================================================================
# Branch Management Operations
# =============================================================================

def git_branch_list(repo_path: Path) -> list[tuple[str, bool]]:
    """List all branches with current branch marked.

    Args:
        repo_path: Path to git repository

    Returns:
        List of (branch_name, is_current) tuples
        Example: [("main", True), ("feature", False)]

    Raises:
        OSError: If git command fails
    """
    result = _git(["branch", "--list"], repo_path)

    branches = []
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue

        # Current branch starts with "* ", non-current starts with "  "
        is_current = line.startswith('* ')
        # Strip leading "* " or "  " and any trailing whitespace
        branch_name = line.lstrip('* ').strip()

        branches.append((branch_name, is_current))

    return branches


def git_branch_create(repo_path: Path, name: str, start_point: str = "HEAD") -> None:
    """Create new branch at start_point.

    Args:
        repo_path: Path to git repository
        name: Branch name to create
        start_point: Commit/branch/tag to start from (default: HEAD)

    Raises:
        OSError: If branch already exists or creation fails
        ValueError: If start_point doesn't exist
    """
    _git(
        ["branch", name, start_point],
        repo_path,
        not_found_msg=f"Git ref '{start_point}' does not exist"
    )


def git_branch_delete(repo_path: Path, name: str, force: bool = False) -> None:
    """Delete branch.

    Args:
        repo_path: Path to git repository
        name: Branch name to delete
        force: If True, force delete even if unmerged

    Raises:
        OSError: If branch doesn't exist or deletion fails
        ValueError: If trying to delete current branch
    """
    flag = "-D" if force else "-d"
    _git(
        ["branch", flag, name],
        repo_path,
        not_found_msg=f"Branch '{name}' does not exist"
    )


def git_switch_branch(repo_path: Path, branch: str, create: bool = False) -> None:
    """Switch to branch (optionally creating it).

    Args:
        repo_path: Path to git repository
        branch: Branch name to switch to
        create: If True, create branch if it doesn't exist

    Raises:
        OSError: If branch doesn't exist (and create=False) or switch fails
    """
    cmd = ["switch"]
    if create:
        cmd.append("-c")
    cmd.append(branch)

    _git(
        cmd,
        repo_path,
        not_found_msg=f"Branch '{branch}' does not exist (use create=True to create it)"
    )


def git_get_current_branch(repo_path: Path) -> str | None:
    """Get current branch name (None if detached HEAD).

    Args:
        repo_path: Path to git repository

    Returns:
        Branch name (e.g., "main") or None if in detached HEAD state

    Raises:
        OSError: If git command fails
    """
    result = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    branch = result.stdout.strip()

    # "HEAD" means detached HEAD state
    if branch == "HEAD":
        return None

    return branch


def git_merge_branch(
    repo_path: Path,
    branch: str,
    message: str | None = None,
    strategy_option: str | None = None,
) -> None:
    """Merge branch into current branch (wrapper around git_merge with message support).

    Args:
        repo_path: Path to git repository
        branch: Branch name to merge
        message: Optional merge commit message
        strategy_option: Optional strategy option (e.g., "ours" or "theirs" for -X flag)

    Raises:
        OSError: If branch doesn't exist or merge fails (conflicts, etc.)
        ValueError: If branch doesn't exist
    """
    cmd = ["merge", branch]
    if message:
        cmd.extend(["-m", message])
    if strategy_option:
        cmd.extend(["-X", strategy_option])

    _git(
        cmd,
        repo_path,
        not_found_msg=f"Branch '{branch}' does not exist"
    )


def git_reset(repo_path: Path, ref: str = "HEAD", mode: str = "hard") -> None:
    """Reset current branch to ref.

    Args:
        repo_path: Path to git repository
        ref: Commit/branch/tag to reset to (default: HEAD)
        mode: Reset mode - "soft", "mixed", or "hard" (default)

    Raises:
        OSError: If reset fails
        ValueError: If ref doesn't exist or mode is invalid
    """
    # Validate mode
    valid_modes = {"soft", "mixed", "hard"}
    if mode not in valid_modes:
        raise ValueError(f"Invalid reset mode '{mode}'. Must be one of: {valid_modes}")

    _git(
        ["reset", f"--{mode}", ref],
        repo_path,
        not_found_msg=f"Git ref '{ref}' does not exist"
    )

    # If hard reset, also clean untracked files
    if mode == "hard":
        _git(["clean", "-fd"], repo_path)


def git_revert(repo_path: Path, commit: str, no_commit: bool = False) -> None:
    """Create new commit that undoes changes from commit.

    Args:
        repo_path: Path to git repository
        commit: Commit hash/ref to revert
        no_commit: If True, apply changes but don't commit

    Raises:
        OSError: If revert fails (conflicts, etc.)
        ValueError: If commit doesn't exist
    """
    cmd = ["revert"]
    if no_commit:
        cmd.append("--no-commit")
    else:
        # Avoid opening editor for commit message
        cmd.append("--no-edit")

    cmd.append(commit)

    _git(
        cmd,
        repo_path,
        not_found_msg=f"Commit '{commit}' does not exist"
    )


# =============================================================================
# Git Authentication (for cloud deployments)
# =============================================================================

def _create_askpass_script(token: str) -> Path:
    """Create a temporary GIT_ASKPASS script that echoes the token.

    The script is created with restrictive permissions (0700) to protect the token.
    Caller is responsible for cleanup after git command completes.

    Args:
        token: GitHub PAT or other credential to inject

    Returns:
        Path to temporary script file
    """
    import stat
    import sys
    import tempfile

    # Create temp file with appropriate extension for platform
    suffix = ".bat" if sys.platform == "win32" else ".sh"
    fd, script_path = tempfile.mkstemp(suffix=suffix, prefix="git_askpass_")

    try:
        if sys.platform == "win32":
            # Windows batch file
            script_content = f"@echo {token}\n"
        else:
            # Unix shell script
            script_content = f"#!/bin/sh\necho '{token}'\n"

        os.write(fd, script_content.encode('utf-8'))
        os.close(fd)

        # Set executable permission (Unix only)
        if sys.platform != "win32":
            os.chmod(script_path, stat.S_IRWXU)  # 0700 - owner read/write/execute only

        return Path(script_path)
    except Exception:
        os.close(fd)
        Path(script_path).unlink(missing_ok=True)
        raise


def _git_with_auth(
    cmd: list[str],
    repo_path: Path,
    token: str,
    check: bool = True
) -> subprocess.CompletedProcess:
    """Run git command with token authentication via GIT_ASKPASS.

    This injects the token at runtime using the GIT_ASKPASS environment variable,
    which git uses to obtain credentials for HTTPS remotes. The token is never
    stored on disk permanently - only in a temporary script that is deleted
    immediately after the command completes.

    Args:
        cmd: Git command arguments (without 'git' prefix)
        repo_path: Path to git repository
        token: GitHub PAT or other credential
        check: Whether to raise exception on non-zero exit

    Returns:
        CompletedProcess result

    Raises:
        OSError: If git command fails
    """
    script_path = _create_askpass_script(token)
    try:
        # Build environment with authentication settings
        env = os.environ.copy()
        env["GIT_ASKPASS"] = str(script_path)
        env["GIT_TERMINAL_PROMPT"] = "0"  # Disable interactive prompts

        result = subprocess.run(
            ["git"] + cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            env=env,
            check=check
        )
        return result
    finally:
        # Always clean up temp script
        script_path.unlink(missing_ok=True)


def git_ls_remote_with_auth(repo_path: Path, remote_url: str, token: str) -> bool:
    """Test git authentication by running ls-remote against a URL.

    This is a lightweight way to verify credentials work without fetching
    any actual content.

    Args:
        repo_path: Path to git repository (for working directory)
        remote_url: Remote URL to test (must be HTTPS)
        token: GitHub PAT to test

    Returns:
        True if authentication succeeded, False otherwise
    """
    try:
        result = _git_with_auth(
            ["ls-remote", "--exit-code", remote_url, "HEAD"],
            repo_path,
            token,
            check=False
        )
        return result.returncode == 0
    except Exception:
        return False


def git_fetch_with_auth(
    repo_path: Path,
    remote: str,
    token: str,
    timeout: int = 30,
) -> str:
    """Fetch from remote with token authentication.

    Args:
        repo_path: Path to git repository
        remote: Remote name (default: origin)
        token: GitHub PAT for authentication
        timeout: Command timeout in seconds

    Returns:
        Fetch output

    Raises:
        ValueError: If remote doesn't exist
        OSError: If fetch fails (network, auth, etc.)
    """
    # Validate remote exists first
    remote_url = git_remote_get_url(repo_path, remote)
    if not remote_url:
        raise ValueError(
            f"Remote '{remote}' not configured. "
            f"Add with: cg remote add {remote} <url>"
        )

    result = _git_with_auth(["fetch", remote], repo_path, token)
    return result.stdout


def git_push_with_auth(
    repo_path: Path,
    remote: str,
    token: str,
    branch: str | None = None,
    force: bool = False,
    force_unsafe: bool = False,
    timeout: int = 30,
) -> str:
    """Push commits to remote with token authentication.

    Args:
        repo_path: Path to git repository
        remote: Remote name (default: origin)
        token: GitHub PAT for authentication
        branch: Branch to push (default: current branch)
        force: Use --force-with-lease first, then retry with --force if needed
        force_unsafe: Use --force directly (skip --force-with-lease)
        timeout: Command timeout in seconds

    Returns:
        Push output

    Raises:
        ValueError: If remote doesn't exist
        OSError: If push fails (auth, conflicts, network)
    """
    # Validate remote exists
    remote_url = git_remote_get_url(repo_path, remote)
    if not remote_url:
        raise ValueError(
            f"Remote '{remote}' not configured. "
            f"Add with: cg remote add {remote} <url>"
        )

    # If force pushing, fetch first to update remote refs for --force-with-lease
    if force and not force_unsafe:
        try:
            git_fetch_with_auth(repo_path, remote, token, timeout)
        except Exception:
            # If fetch fails, continue anyway - user wants to force push
            pass

    cmd = ["push", remote]
    if branch:
        cmd.append(branch)

    if force_unsafe:
        cmd.append("--force")
    elif force:
        cmd.append("--force-with-lease")

    try:
        result = _git_with_auth(cmd, repo_path, token)
        return result.stdout
    except subprocess.CalledProcessError as e:
        error_msg = (e.stderr or "").lower()
        if "permission denied" in error_msg or "authentication" in error_msg:
            raise OSError(
                "Authentication failed. Check your token has repo access."
            ) from e

        # If --force-with-lease failed due to stale refs, and force=True, retry with --force
        if force and not force_unsafe and ("stale info" in error_msg or "rejected" in error_msg):
            logger.warning("--force-with-lease failed, retrying with --force")
            return git_push_with_auth(repo_path, remote, token, branch, force=True, force_unsafe=True, timeout=timeout)

        if "rejected" in error_msg:
            raise OSError(
                "Push rejected - remote has changes. Run: cg pull first"
            ) from e
        raise OSError(f"Push failed: {e.stderr or str(e)}") from e


def git_pull_with_auth(
    repo_path: Path,
    remote: str,
    token: str,
    branch: str | None = None,
    ff_only: bool = False,
    timeout: int = 30,
    strategy_option: str | None = None,
    force: bool = False,
) -> dict:
    """Fetch and merge from remote with token authentication.

    Args:
        repo_path: Path to git repository
        remote: Remote name (default: origin)
        token: GitHub PAT for authentication
        branch: Branch name (default: auto-detect current branch)
        ff_only: Only allow fast-forward merges (default: False)
        timeout: Command timeout in seconds
        strategy_option: Optional strategy option (e.g., "ours" or "theirs" for -X flag)
        force: If True, allow unrelated histories merge (default: False)

    Returns:
        Dict with keys: 'fetch_output', 'merge_output', 'branch'

    Raises:
        ValueError: If remote doesn't exist, detached HEAD, or merge conflicts
        OSError: If fetch/merge fails
    """
    # Auto-detect current branch if not specified
    if not branch:
        branch = git_current_branch(repo_path)

    # Fetch with auth
    fetch_output = git_fetch_with_auth(repo_path, remote, token, timeout)

    # Then merge (no auth needed - local operation)
    merge_ref = f"{remote}/{branch}"
    merge_output = git_merge(
        repo_path,
        merge_ref,
        ff_only,
        timeout,
        strategy_option,
        allow_unrelated_histories=force,
    )

    return {
        'fetch_output': fetch_output,
        'merge_output': merge_output,
        'branch': branch,
    }
