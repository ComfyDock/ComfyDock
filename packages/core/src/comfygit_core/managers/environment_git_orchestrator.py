"""Environment-aware git orchestration manager.

Coordinates git operations with environment state synchronization.
Handles node reconciliation, package syncing, and workflow restoration
around git operations like checkout, rollback, merge, etc.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..logging.logging_config import get_logger

if TYPE_CHECKING:
    from ..models.protocols import RollbackStrategy
    from .git_manager import GitManager
    from .node_manager import NodeManager
    from .pyproject_manager import PyprojectManager
    from .pytorch_backend_manager import PyTorchBackendManager
    from .uv_project_manager import UVProjectManager
    from .workflow_manager import WorkflowManager

logger = get_logger(__name__)


class EnvironmentGitOrchestrator:
    """Orchestrates git operations with environment synchronization.

    Responsibilities:
    - Coordinate git operations with environment state
    - Handle node reconciliation (add/remove nodes based on git changes)
    - Sync Python packages after git operations
    - Restore workflows from .cec to ComfyUI
    - Manage uncommitted change validation
    """

    def __init__(
        self,
        git_manager: GitManager,
        node_manager: NodeManager,
        pyproject_manager: PyprojectManager,
        uv_manager: UVProjectManager,
        workflow_manager: WorkflowManager,
        pytorch_manager: PyTorchBackendManager | None = None,
    ):
        self.git = git_manager
        self.node_manager = node_manager
        self.pyproject = pyproject_manager
        self.uv = uv_manager
        self.workflow_manager = workflow_manager
        self.pytorch_manager = pytorch_manager

    def checkout(
        self,
        ref: str,
        strategy: RollbackStrategy | None = None,
        force: bool = False
    ) -> None:
        """Checkout commit/branch without auto-committing (git-native exploration).

        Args:
            ref: Git reference (commit hash, branch, tag)
            strategy: Optional strategy for confirming destructive checkout
            force: If True, discard uncommitted changes without confirmation

        Raises:
            ValueError: If ref doesn't exist
            OSError: If git commands fail
            CDEnvironmentError: If uncommitted changes exist and no strategy/force
        """
        from ..models.exceptions import CDEnvironmentError

        # Check for uncommitted changes
        if not force:
            has_git_changes = self.git.has_uncommitted_changes()
            has_workflow_changes = self.workflow_manager.get_workflow_sync_status().has_changes

            if has_git_changes or has_workflow_changes:
                if strategy is None:
                    raise CDEnvironmentError(
                        "Cannot checkout with uncommitted changes.\n"
                        "Uncommitted changes detected:\n"
                        + ("  • Git changes in .cec/\n" if has_git_changes else "")
                        + ("  • Workflow changes in ComfyUI\n" if has_workflow_changes else "")
                    )

                if not strategy.confirm_destructive_rollback(
                    git_changes=has_git_changes,
                    workflow_changes=has_workflow_changes
                ):
                    raise CDEnvironmentError("Checkout cancelled by user")

        # Snapshot old state
        old_nodes = self.pyproject.nodes.get_existing()

        # Git checkout (restore both HEAD and working tree)
        from ..utils.git import _git
        _git(["checkout", "--force", ref], self.git.repo_path)
        if force:
            _git(["clean", "-fd"], self.git.repo_path)

        # Reload pyproject and sync environment
        self._sync_environment_after_git(old_nodes)

        logger.info(f"Checkout complete: HEAD now at {ref}")

    def reset(
        self,
        ref: str | None = None,
        mode: str = "hard",
        strategy: RollbackStrategy | None = None,
        force: bool = False
    ) -> None:
        """Reset HEAD to ref with git reset semantics.

        Modes:
        - hard: Discard all changes, move HEAD (auto-commits for history)
        - mixed: Keep changes in working tree, unstage
        - soft: Keep changes staged

        Args:
            ref: Git reference to reset to (None = HEAD)
            mode: Reset mode (hard/mixed/soft)
            strategy: Optional strategy for confirming destructive reset
            force: If True, skip confirmation

        Raises:
            ValueError: If ref doesn't exist or invalid mode
            CDEnvironmentError: If uncommitted changes exist (hard mode only)
        """
        from ..models.exceptions import CDEnvironmentError

        if mode not in ("hard", "mixed", "soft"):
            raise ValueError(f"Invalid reset mode: {mode}. Must be hard, mixed, or soft")

        ref = ref or "HEAD"

        # Hard mode requires confirmation for uncommitted changes
        if mode == "hard" and not force:
            has_git_changes = self.git.has_uncommitted_changes()
            has_workflow_changes = self.workflow_manager.get_workflow_sync_status().has_changes

            if has_git_changes or has_workflow_changes:
                if strategy is None:
                    raise CDEnvironmentError(
                        "Cannot reset with uncommitted changes.\n"
                        "Uncommitted changes detected:\n"
                        + ("  • Git changes in .cec/\n" if has_git_changes else "")
                        + ("  • Workflow changes in ComfyUI\n" if has_workflow_changes else "")
                    )

                if not strategy.confirm_destructive_rollback(
                    git_changes=has_git_changes,
                    workflow_changes=has_workflow_changes
                ):
                    raise CDEnvironmentError("Reset cancelled by user")

        # Perform git reset
        if mode == "hard":
            old_nodes = self.pyproject.nodes.get_existing()
            self.git.reset_to(ref, mode="hard")
            self._sync_environment_after_git(old_nodes)
            logger.info(f"Hard reset complete: HEAD now at {ref}")
        else:
            self.git.reset_to(ref, mode=mode)
            logger.info(f"Reset ({mode}) complete: HEAD now at {ref}")

    def create_branch(self, name: str, start_point: str = "HEAD") -> None:
        """Create new branch at start_point.

        Args:
            name: Branch name
            start_point: Commit to branch from (default: HEAD)
        """
        self.git.create_branch(name, start_point)
        logger.info(f"Created branch '{name}' at {start_point}")

    def delete_branch(self, name: str, force: bool = False) -> None:
        """Delete branch.

        Args:
            name: Branch name
            force: Force delete even if unmerged
        """
        self.git.delete_branch(name, force)
        logger.info(f"Deleted branch '{name}'")

    def create_and_switch_branch(self, name: str, start_point: str = "HEAD") -> None:
        """Create new branch and switch to it (git checkout -b semantics).

        This is the atomic equivalent of 'git checkout -b'. It creates a branch
        from start_point and switches to it in one operation, preserving any
        uncommitted workflow changes. No conflict checking is performed since
        the new branch is guaranteed to have the same tree as the start_point.

        Args:
            name: Branch name to create
            start_point: Commit to branch from (default: HEAD)

        Raises:
            OSError: If branch already exists or git operations fail
        """
        # Create the branch
        self.git.create_branch(name, start_point)
        logger.info(f"Created branch '{name}' at {start_point}")

        # Snapshot old state
        old_nodes = self.pyproject.nodes.get_existing()

        # Switch to the new branch
        self.git.switch_branch(name, create=False)

        # Sync environment with uncommitted workflows preserved
        # No conflict checking needed - branch was just created from current state
        self._sync_environment_after_git(old_nodes, preserve_uncommitted=True)

        logger.info(f"Switched to new branch '{name}'")

    def switch_branch(self, branch: str, create: bool = False) -> None:
        """Switch to branch and sync environment.

        Args:
            branch: Branch name
            create: Create branch if it doesn't exist

        Raises:
            CDEnvironmentError: If uncommitted workflow changes would be overwritten
        """
        from ..models.exceptions import CDEnvironmentError

        # Check for uncommitted workflow changes
        preserve_uncommitted = False

        if not create:
            status = self.workflow_manager.get_workflow_sync_status()
            has_workflow_changes = status.has_changes

            if has_workflow_changes:
                would_overwrite = self._would_overwrite_workflows(branch, status)

                if would_overwrite:
                    raise CDEnvironmentError(
                        f"Cannot switch to branch '{branch}' with uncommitted workflow changes.\n"
                        "Your changes to the following workflows would be overwritten:\n" +
                        "\n".join(f"  • {wf}" for wf in status.new + status.modified) +
                        "\n\nPlease commit your changes or use --force to discard them:\n"
                        "  • Commit: cg commit -m '<message>'\n"
                        "  • Force: cg switch <branch> --force"
                    )
                else:
                    preserve_uncommitted = True
        else:
            preserve_uncommitted = True

        # Snapshot old state
        old_nodes = self.pyproject.nodes.get_existing()

        # Switch branch
        self.git.switch_branch(branch, create)

        # Sync environment
        self._sync_environment_after_git(old_nodes, preserve_uncommitted=preserve_uncommitted)

        logger.info(f"Switched to branch '{branch}'")

    def merge_branch(
        self,
        branch: str,
        message: str | None = None,
        strategy_option: str | None = None,
    ) -> None:
        """Merge branch into current branch and sync environment.

        Args:
            branch: Branch to merge
            message: Custom merge commit message
            strategy_option: Optional strategy option (e.g., "ours" or "theirs" for -X flag)
        """
        old_nodes = self.pyproject.nodes.get_existing()
        self.git.merge_branch(branch, message, strategy_option)
        self._sync_environment_after_git(old_nodes)
        logger.info(f"Merged branch '{branch}'")

    def revert_commit(self, commit: str) -> None:
        """Revert a commit by creating new commit that undoes it.

        Args:
            commit: Commit hash to revert
        """
        old_nodes = self.pyproject.nodes.get_existing()
        self.git.revert_commit(commit)
        self._sync_environment_after_git(old_nodes)
        logger.info(f"Reverted commit {commit}")

    def _sync_environment_after_git(
        self,
        old_nodes: dict,
        preserve_uncommitted: bool = False
    ) -> None:
        """Sync environment state after git operation.

        Args:
            old_nodes: Node state before git operation
            preserve_uncommitted: Whether to preserve uncommitted workflows
        """
        # Reload pyproject
        self.pyproject.reset_lazy_handlers()

        # NOTE: PyTorch config is now handled entirely by pytorch_injection_context()
        # which strips existing config before injecting, then restores original after sync.
        # This keeps pyproject.toml clean of machine-specific PyTorch configuration.

        new_nodes = self.pyproject.nodes.get_existing()

        # Reconcile nodes
        self.node_manager.reconcile_nodes_for_rollback(old_nodes, new_nodes)

        # Sync Python environment with PyTorch injection
        self.uv.sync_project(all_groups=True, pytorch_manager=self.pytorch_manager)

        # Restore workflows
        self.workflow_manager.restore_all_from_cec(preserve_uncommitted=preserve_uncommitted)

    def _would_overwrite_workflows(self, target_branch: str, status) -> bool:
        """Check if switching to target branch would overwrite uncommitted workflows.

        Args:
            target_branch: Branch name to check
            status: Current workflow sync status

        Returns:
            True if any uncommitted workflow exists in target branch's .cec
        """
        from ..utils.git import _git

        uncommitted = set(status.new + status.modified)
        if not uncommitted:
            return False

        try:
            result = _git(
                ["ls-tree", "-r", "--name-only", target_branch, "workflows/"],
                self.git.repo_path,
                capture_output=True
            )

            target_workflows = set()
            for line in result.stdout.strip().split('\n'):
                if line.startswith('workflows/') and line.endswith('.json'):
                    name = line[len('workflows/'):-len('.json')]
                    target_workflows.add(name)

            conflicts = uncommitted & target_workflows
            if conflicts:
                logger.debug(f"Conflicting workflows detected: {conflicts}")
                return True

            return False

        except Exception as e:
            logger.warning(f"Could not check target branch workflows: {e}")
            return True

