"""High-level Git workflow manager for ComfyGit environments.

This module provides higher-level git workflows that combine multiple git operations
with business logic. It builds on top of the low-level git utilities in git.py.
"""
from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import TYPE_CHECKING

from ..logging.logging_config import get_logger
from ..models.environment import GitStatus

if TYPE_CHECKING:
    from .pyproject_manager import PyprojectManager

from ..utils.git import (
    get_uncommitted_changes,
    git_checkout,
    git_commit,
    git_config_get,
    git_config_set,
    git_diff,
    git_history,
    git_init,
    git_ls_files,
    git_ls_tree,
    git_show,
    git_status_porcelain,
)

logger = get_logger(__name__)


class GitManager:
    """Manages high-level git workflows for environment tracking."""

    def __init__(self, repo_path: Path):
        """Initialize GitManager for a specific repository.

        Args:
            repo_path: Path to the git repository (usually .cec directory)
        """
        self.repo_path = repo_path
        self.gitignore_content = """# Staging area
staging/

# Staging metadata
metadata/

# logs
logs/

# Local safety backups
backups/

# Python cache
__pycache__/
*.pyc

# Temporary files
*.tmp
*.bak
.comfygit-tmp/

# Runtime marker (created after successful environment initialization)
.complete

# PyTorch backend configuration (machine-specific)
.pytorch-backend

# Local overlays and activation (machine-specific)
overlays/.*
.overlay-config.toml

# Lock file (machine-specific due to PyTorch platform variants)
uv.lock

# Generated ComfyUI metadata (recreated from the selected ComfyUI version)
comfyui_builtins.json
comfyui_folder_paths.json
comfyui_model_loaders.json
"""

    def ensure_git_identity(self) -> None:
        """Ensure git has a user identity configured for commits.

        Sets up local git config (not global) with sensible defaults.
        """
        # Check if identity is already configured
        existing_name = git_config_get(self.repo_path, "user.name")
        existing_email = git_config_get(self.repo_path, "user.email")

        # If both are set, we're good
        if existing_name and existing_email:
            return

        # Determine git identity using fallback chain
        git_name = self._get_git_identity()
        git_email = self._get_git_email()

        # Set identity locally for this repository only
        git_config_set(self.repo_path, "user.name", git_name)
        git_config_set(self.repo_path, "user.email", git_email)

        logger.info(f"Set local git identity: {git_name} <{git_email}>")

    def _get_git_identity(self) -> str:
        """Get a suitable git user name with smart fallbacks."""
        # Try environment variables first
        git_name = os.environ.get("GIT_AUTHOR_NAME")
        if git_name:
            return git_name

        # Try to get system username as fallback for name
        try:
            import pwd
            git_name = (
                pwd.getpwuid(os.getuid()).pw_gecos or pwd.getpwuid(os.getuid()).pw_name
            )
            if git_name:
                return git_name
        except Exception:
            pass

        try:
            git_name = os.getlogin()
            if git_name:
                return git_name
        except Exception:
            pass

        return "ComfyGit User"

    def _get_git_email(self) -> str:
        """Get a suitable git email with smart fallbacks."""
        # Try environment variables first
        git_email = os.environ.get("GIT_AUTHOR_EMAIL")
        if git_email:
            return git_email

        # Try to construct from username and hostname
        try:
            hostname = socket.gethostname()
            username = os.getlogin()
            return f"{username}@{hostname}"
        except Exception:
            pass

        return "user@comfygit.local"

    def initialize_environment_repo(
        self, initial_message: str = "Initial environment setup"
    ) -> None:
        """Initialize a new environment repository with proper setup.

        This combines:
        - Git init
        - Identity setup
        - Gitignore creation
        - Initial commit

        Args:
            initial_message: Message for the initial commit
        """
        # Initialize git repository
        git_init(self.repo_path)

        # Ensure git identity is configured
        self.ensure_git_identity()

        # Create standard .gitignore
        self._create_gitignore()

        # Initial commit (if there are files to commit)
        if any(self.repo_path.iterdir()):
            git_commit(self.repo_path, initial_message)
            logger.info(f"Created initial commit: {initial_message}")

    def commit_with_identity(self, message: str, add_all: bool = True) -> None:
        """Commit changes ensuring identity is set up.

        Args:
            message: Commit message
            add_all: Whether to stage all changes first
        """
        # Ensure identity before committing
        self.ensure_git_identity()

        if add_all:
            self._strip_local_path_sources_before_commit()

        # Perform the commit
        git_commit(self.repo_path, message, add_all)

    def _get_files_in_commit(self, commit_hash: str) -> set[str]:
        """Get all tracked file paths in a specific commit.

        Args:
            commit_hash: Git commit hash

        Returns:
            Set of file paths that exist in the commit
        """
        result = git_ls_tree(self.repo_path, commit_hash, recursive=True)
        if not result.strip():
            return set()

        return {line for line in result.splitlines() if line}

    def _get_tracked_files(self) -> set[str]:
        """Get all currently tracked file paths in working tree.

        Returns:
            Set of file paths currently tracked by git
        """
        result = git_ls_files(self.repo_path)
        if not result.strip():
            return set()

        return {line for line in result.splitlines() if line}

    def apply_commit(self, commit_ref: str, leave_unstaged: bool = True) -> None:
        """Apply files from a specific commit to working directory.

        Args:
            commit_ref: Any valid git ref (hash, branch, tag, HEAD~N)
            leave_unstaged: If True, files are left as uncommitted changes

        Raises:
            OSError: If git commands fail (invalid ref, etc.)
        """
        # Git will validate the ref - no manual resolution needed
        logger.info(f"Applying files from commit {commit_ref}")

        # Phase 1: Get file lists
        target_files = self._get_files_in_commit(commit_ref)
        current_files = self._get_tracked_files()
        files_to_delete = current_files - target_files

        # Phase 2: Restore files from target commit
        git_checkout(self.repo_path, commit_ref, files=["."], unstage=leave_unstaged)

        # Phase 3: Delete files that don't exist in target commit
        if files_to_delete:
            from ..utils.common import run_command

            for file_path in files_to_delete:
                full_path = self.repo_path / file_path
                if full_path.exists():
                    full_path.unlink()
                    logger.info(f"Deleted {file_path} (not in target commit)")

            # Stage only the specific deletions (not all modifications)
            # git add <file> will stage the deletion when file doesn't exist
            for file_path in files_to_delete:
                run_command(["git", "add", file_path], cwd=self.repo_path, check=True)

            # If leave_unstaged, unstage the deletions again
            if leave_unstaged:
                run_command(["git", "reset", "HEAD"] + list(files_to_delete),
                          cwd=self.repo_path, check=True)

    def discard_uncommitted(self) -> None:
        """Discard all uncommitted changes in the repository."""
        logger.info("Discarding uncommitted changes")
        git_checkout(self.repo_path, "HEAD", files=["."])

    def get_version_history(self, limit: int = 10, rev_range: str | None = None) -> list[dict]:
        """Get commit history with short hashes and branch references.

        Args:
            limit: Maximum number of commits to return
            rev_range: Git revision range (e.g. "origin/main..HEAD")

        Returns:
            List of commit dicts with keys: hash, refs, message, date, date_relative
            (newest first)
        """
        # Use %h for short hash, %D for refs (branch names without parens), %cr for relative date
        result = git_history(
            self.repo_path,
            max_count=limit,
            pretty="format:%h|%D|%s|%ai|%cr",
            rev_range=rev_range,
        )

        commits = []
        for line in result.strip().split('\n'):
            if line:
                hash_short, refs, message, date, date_relative = line.split('|', 4)
                commits.append({
                    'hash': hash_short,           # 7-char short hash
                    'refs': refs.strip(),          # Branch/tag refs: "HEAD -> main, origin/main" or ""
                    'message': message,
                    'date': date,                 # Absolute: 2025-11-15 14:23:45
                    'date_relative': date_relative  # Relative: "2 days ago"
                })

        # git log returns newest first by default
        return commits


    def get_pyproject_diff(self) -> str:
        """Get the git diff specifically for pyproject.toml.

        Returns:
            Diff output or empty string
        """
        pyproject_path = Path("pyproject.toml")
        return git_diff(self.repo_path, pyproject_path) or ""

    def get_pyproject_from_commit(self, commit_ref: str) -> str:
        """Get pyproject.toml content from a specific commit.

        Args:
            commit_ref: Any valid git ref (hash, branch, tag, HEAD~N)

        Returns:
            File content as string

        Raises:
            OSError: If commit or file doesn't exist
        """
        return git_show(self.repo_path, commit_ref, Path("pyproject.toml"))

    def commit_all(self, message: str | None = None) -> None:
        """Commit all changes in the repository.

        Args:
            message: Commit message

        Raises:
            OSError: If git commands fail

        """
        if message is None:
            message = "Committing all changes"
        self._strip_local_path_sources_before_commit()
        return git_commit(self.repo_path, message, add_all=True)

    def _strip_local_path_sources_before_commit(self) -> None:
        """Remove local path sources from pyproject.toml before committing."""
        pyproject_path = self.repo_path / "pyproject.toml"
        if not pyproject_path.exists():
            return

        try:
            from .pyproject_manager import PyprojectManager

            pyproject = PyprojectManager(pyproject_path)
            removed = pyproject.strip_local_path_sources()
            if removed:
                logger.info(f"Stripped {len(removed)} local path source(s) before commit")
        except Exception as exc:
            logger.warning(f"Failed to strip local path sources before commit: {exc}")

    def get_workflow_git_changes(self) -> dict[str, str]:
        """Get git status for workflow files specifically.

        Returns:
            Dict mapping workflow names to their git status:
            - 'modified' for modified files
            - 'added' for new/untracked files
            - 'deleted' for deleted files
        """
        status_entries = git_status_porcelain(self.repo_path)
        workflow_changes = {}

        for index_status, working_status, filename in status_entries:
            logger.debug(f"index status: {index_status}, working status: {working_status}, filename: {filename}")

            # Only process workflow files
            if filename.startswith('workflows/') and filename.endswith('.json'):
                # Extract workflow name from path (keep spaces as-is)
                workflow_name = Path(filename).stem
                logger.debug(f"Workflow name: {workflow_name}")

                # Determine status (prioritize working tree status)
                if working_status == 'M' or index_status == 'M':
                    workflow_changes[workflow_name] = 'modified'
                elif working_status == 'D' or index_status == 'D':
                    workflow_changes[workflow_name] = 'deleted'
                elif working_status == '?' or index_status == 'A':
                    workflow_changes[workflow_name] = 'added'

        logger.debug(f"Workflow changes: {str(workflow_changes)}")
        return workflow_changes

    def has_uncommitted_changes(self) -> bool:
        """Check if there are any uncommitted changes.

        Returns:
            True if there are uncommitted changes
        """
        return bool(get_uncommitted_changes(self.repo_path))

    def _create_gitignore(self) -> None:
        """Create standard .gitignore for environment tracking."""
        gitignore_path = self.repo_path / ".gitignore"
        gitignore_path.write_text(self.gitignore_content)

    def ensure_gitignore_entry(self, entry: str) -> bool:
        """Ensure a specific entry exists in .gitignore.

        Used during migrations to add new gitignore entries to existing
        environments.

        Args:
            entry: The gitignore entry to add (e.g., '.pytorch-backend')

        Returns:
            True if entry was added, False if already present
        """
        gitignore_path = self.repo_path / ".gitignore"

        if not gitignore_path.exists():
            # Create with just this entry
            gitignore_path.write_text(f"{entry}\n")
            logger.debug(f"Created .gitignore with entry: {entry}")
            return True

        current_content = gitignore_path.read_text()
        lines = current_content.strip().split('\n') if current_content.strip() else []

        # Check if entry already exists (exact match or with trailing comment)
        for line in lines:
            stripped = line.split('#')[0].strip()
            if stripped == entry:
                logger.debug(f".gitignore already contains: {entry}")
                return False

        # Add entry at the end
        if not current_content.endswith('\n'):
            current_content += '\n'
        current_content += f"\n# Added during migration\n{entry}\n"
        gitignore_path.write_text(current_content)
        logger.info(f"Added to .gitignore: {entry}")
        return True


    def get_status(self, pyproject_manager: PyprojectManager | None = None) -> GitStatus:
        """Get complete git status with optional change parsing.

        Args:
            pyproject_manager: Optional PyprojectManager for parsing changes

        Returns:
            GitStatus with all git information encapsulated
        """
        # Get basic git information
        workflow_changes = self.get_workflow_git_changes()
        pyproject_has_changes = bool(self.get_pyproject_diff().strip())
        has_changes = pyproject_has_changes or bool(workflow_changes)
        current_branch = self.get_current_branch()

        # Check for other uncommitted changes beyond workflows/pyproject
        all_uncommitted = self.has_uncommitted_changes()
        has_other_changes = all_uncommitted and not has_changes

        # Create status object
        status = GitStatus(
            has_changes=has_changes or has_other_changes,
            current_branch=current_branch,
            has_other_changes=has_other_changes,
            # diff=diff,
            workflow_changes=workflow_changes
        )

        # Parse changes if we have them and a pyproject manager
        if has_changes and pyproject_manager:
            from ..analyzers.git_change_parser import GitChangeParser
            parser = GitChangeParser(self.repo_path)
            current_config = pyproject_manager.load()

            # The parser updates the status object directly
            parser.update_git_status(status, current_config)

        return status

    def create_checkpoint(self, description: str | None = None) -> str:
        """Create a checkpoint of the current state.

        Args:
            description: Optional description for the checkpoint

        Returns:
            Commit hash of the checkpoint
        """
        # Generate automatic message if not provided
        if not description:
            from datetime import datetime

            description = f"Checkpoint created at {datetime.now().isoformat()}"

        # Commit current state
        self.commit_with_identity(description)

        # Get the new commit hash
        history = self.get_version_history(limit=1)
        if history:
            return history[0]["hash"]  # Newest first
        return ""

    def get_commit_summary(self) -> dict:
        """Get a summary of the commit state.

        Returns:
            Dict with current_commit, has_uncommitted_changes, total_commits, latest_message
        """
        history = self.get_version_history(limit=100)
        has_changes = self.has_uncommitted_changes()

        current_commit = history[0]["hash"] if history else None  # Newest first

        return {
            "current_commit": current_commit,
            "has_uncommitted_changes": has_changes,
            "total_commits": len(history),
            "latest_message": history[0]["message"] if history else None,
        }

    # =============================================================================
    # Pull/Push/Remote Operations
    # =============================================================================

    def pull(
        self,
        remote: str = "origin",
        branch: str | None = None,
        ff_only: bool = False,
        strategy_option: str | None = None,
        force: bool = False,
    ) -> dict:
        """Pull from remote (fetch + merge).

        Args:
            remote: Remote name (default: origin)
            branch: Branch to pull (default: current branch)
            ff_only: Only allow fast-forward merges (default: False)
            strategy_option: Optional strategy option (e.g., "ours" or "theirs" for -X flag)
            force: If True, allow unrelated histories merge (default: False)

        Returns:
            Dict with keys: 'fetch_output', 'merge_output', 'branch'

        Raises:
            ValueError: If no remote, detached HEAD, or merge conflicts
            OSError: If fetch/merge fails
        """
        from ..utils.git import git_pull

        logger.info(f"Pulling {remote}/{branch or 'current branch'}" + (" (force)" if force else ""))

        result = git_pull(
            self.repo_path, remote, branch, ff_only=ff_only, strategy_option=strategy_option, force=force
        )

        return result

    def push(self, remote: str = "origin", branch: str | None = None, force: bool = False) -> str:
        """Push commits to remote.

        Args:
            remote: Remote name (default: origin)
            branch: Branch to push (default: current branch)
            force: Use --force-with-lease (default: False)

        Returns:
            Push output

        Raises:
            ValueError: If no remote or detached HEAD
            OSError: If push fails
        """
        from ..utils.git import git_current_branch, git_push

        # Get current branch if not specified
        if not branch:
            branch = git_current_branch(self.repo_path)

        logger.info(f"Pushing to {remote}/{branch}" + (" (force)" if force else ""))

        return git_push(self.repo_path, remote, branch, force=force)

    def add_remote(self, name: str, url: str) -> None:
        """Add a git remote.

        Args:
            name: Remote name (e.g., "origin")
            url: Remote URL

        Raises:
            OSError: If remote already exists
        """
        from ..utils.git import git_remote_add

        logger.info(f"Adding remote '{name}': {url}")
        git_remote_add(self.repo_path, name, url)

    def remove_remote(self, name: str) -> None:
        """Remove a git remote.

        Args:
            name: Remote name (e.g., "origin")

        Raises:
            ValueError: If remote doesn't exist
        """
        from ..utils.git import git_remote_remove

        logger.info(f"Removing remote '{name}'")
        git_remote_remove(self.repo_path, name)

    def list_remotes(self) -> list[tuple[str, str, str]]:
        """List all git remotes.

        Returns:
            List of tuples: [(name, url, type), ...]
        """
        from ..utils.git import git_remote_list

        return git_remote_list(self.repo_path)

    def has_remote(self, name: str = "origin") -> bool:
        """Check if a remote exists.

        Args:
            name: Remote name (default: origin)

        Returns:
            True if remote exists
        """
        from ..utils.git import git_remote_get_url

        url = git_remote_get_url(self.repo_path, name)
        return bool(url)

    def fetch(self, remote: str = "origin") -> None:
        """Fetch from remote.

        Args:
            remote: Remote name (default: origin)

        Raises:
            ValueError: If remote doesn't exist
            OSError: If fetch fails
        """
        from ..utils.git import git_fetch

        logger.info(f"Fetching from {remote}")
        git_fetch(self.repo_path, remote)

    def set_remote_url(self, name: str, url: str, is_push: bool = False) -> None:
        """Set URL for a git remote.

        Args:
            name: Remote name
            url: New URL
            is_push: If True, update push URL; otherwise update fetch URL

        Raises:
            ValueError: If remote doesn't exist
            OSError: If update fails
        """
        from ..utils.git import git_remote_set_url

        logger.info(f"Setting {'push' if is_push else 'fetch'} URL for '{name}': {url}")
        git_remote_set_url(self.repo_path, name, url, push=is_push)

    def get_sync_status(self, remote: str = "origin", branch: str | None = None) -> dict:
        """Get ahead/behind status for a remote branch.

        Args:
            remote: Remote name (default: origin)
            branch: Branch name (default: current branch)

        Returns:
            Dict with keys:
            - 'ahead': commits ahead of remote (int)
            - 'behind': commits behind remote (int)
            - 'remote_branch_exists': whether the remote branch exists (bool)
        """
        from ..utils.git import (
            git_get_current_branch,
            git_remote_get_url,
            git_rev_list_count,
            git_rev_list_count_single,
            git_rev_parse,
        )

        # Check if remote exists
        if not git_remote_get_url(self.repo_path, remote):
            return {"ahead": 0, "behind": 0, "remote_branch_exists": False}

        # Get current branch if not specified
        if not branch:
            branch = git_get_current_branch(self.repo_path)
            if not branch:
                return {"ahead": 0, "behind": 0, "remote_branch_exists": False}

        remote_ref = f"{remote}/{branch}"

        # Check if remote branch exists (first push scenario)
        if not git_rev_parse(self.repo_path, remote_ref):
            # Remote branch doesn't exist - all local commits are "ahead"
            local_count = git_rev_list_count_single(self.repo_path, branch)
            return {"ahead": local_count, "behind": 0, "remote_branch_exists": False}

        # Compare HEAD to remote/branch
        # git rev-list --left-right --count origin/main...HEAD
        # Returns: "behind\tahead" (commits on left, commits on right)
        behind, ahead = git_rev_list_count(self.repo_path, remote_ref, "HEAD")

        return {"ahead": ahead, "behind": behind, "remote_branch_exists": True}

    # =============================================================================
    # Branch Management
    # =============================================================================

    def list_branches(self) -> list[tuple[str, bool]]:
        """List all branches with current branch marked.

        Returns:
            List of (branch_name, is_current) tuples
        """
        from ..utils.git import git_branch_list

        return git_branch_list(self.repo_path)

    def create_branch(self, name: str, start_point: str = "HEAD") -> None:
        """Create new branch at start_point.

        Args:
            name: Branch name to create
            start_point: Commit/branch/tag to start from (default: HEAD)

        Raises:
            OSError: If branch already exists or creation fails
            ValueError: If start_point doesn't exist
        """
        from ..utils.git import git_branch_create

        logger.info(f"Creating branch '{name}' at {start_point}")
        git_branch_create(self.repo_path, name, start_point)

    def delete_branch(self, name: str, force: bool = False) -> None:
        """Delete branch.

        Args:
            name: Branch name to delete
            force: If True, force delete even if unmerged

        Raises:
            OSError: If branch doesn't exist or deletion fails
            ValueError: If trying to delete current branch
        """
        from ..utils.git import git_branch_delete

        logger.info(f"Deleting branch '{name}'" + (" (force)" if force else ""))
        git_branch_delete(self.repo_path, name, force)

    def switch_branch(self, branch: str, create: bool = False) -> None:
        """Switch to branch (optionally creating it).

        Args:
            branch: Branch name to switch to
            create: If True, create branch if it doesn't exist

        Raises:
            OSError: If branch doesn't exist (and create=False) or switch fails
        """
        from ..utils.git import git_switch_branch

        logger.info(f"Switching to branch '{branch}'" + (" (create)" if create else ""))
        git_switch_branch(self.repo_path, branch, create)

    def get_current_branch(self) -> str | None:
        """Get current branch name (None if detached HEAD).

        Returns:
            Branch name or None if in detached HEAD state
        """
        from ..utils.git import git_get_current_branch

        return git_get_current_branch(self.repo_path)

    def merge_branch(
        self,
        branch: str,
        message: str | None = None,
        strategy_option: str | None = None,
    ) -> None:
        """Merge branch into current branch.

        Args:
            branch: Branch name to merge
            message: Optional merge commit message
            strategy_option: Optional strategy option (e.g., "ours" or "theirs" for -X flag)

        Raises:
            OSError: If branch doesn't exist or merge fails (conflicts, etc.)
            ValueError: If branch doesn't exist
        """
        from ..utils.git import git_merge_branch

        logger.info(f"Merging branch '{branch}' into current branch")
        git_merge_branch(self.repo_path, branch, message, strategy_option)

    def reset_to(self, ref: str = "HEAD", mode: str = "hard") -> None:
        """Reset current branch to ref.

        Args:
            ref: Commit/branch/tag to reset to (default: HEAD)
            mode: Reset mode - "soft", "mixed", or "hard" (default)

        Raises:
            OSError: If reset fails
            ValueError: If ref doesn't exist or mode is invalid
        """
        from ..utils.git import git_reset

        logger.info(f"Resetting to {ref} (mode: {mode})")
        git_reset(self.repo_path, ref, mode)

    def revert_commit(self, commit: str) -> None:
        """Create new commit that undoes changes from commit.

        Args:
            commit: Commit hash/ref to revert

        Raises:
            OSError: If revert fails (conflicts, etc.)
            ValueError: If commit doesn't exist
        """
        from ..utils.git import git_revert

        logger.info(f"Reverting commit {commit}")
        git_revert(self.repo_path, commit)
