"""Atomic merge executor for ComfyGit environments.

Executes merges with atomic rollback on failure.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from ..models.merge_plan import MergePlan, MergeResult, Resolution
from ..utils.git import _git
from ..validation.resolution_tester import ResolutionTester

if TYPE_CHECKING:
    from ..managers.pyproject_manager import PyprojectManager

from .semantic_merger import SemanticMerger


class AtomicMergeExecutor:
    """Executes merge with atomic rollback on failure."""

    def __init__(
        self,
        repo_path: Path,
        pyproject_manager: "PyprojectManager",
        semantic_merger: SemanticMerger | None = None,
        workspace_path: Path | None = None,
    ):
        self.repo_path = repo_path
        self.pyproject = pyproject_manager
        self.merger = semantic_merger or SemanticMerger()
        self.workspace_path = workspace_path

    def execute(self, plan: MergePlan) -> MergeResult:
        """Execute merge according to plan.

        Atomic: either completes fully or rolls back to pre-merge state.
        """
        from ..utils.git import git_rev_parse

        # Guard: refuse to merge if already in merge state
        if self.is_merge_in_progress(self.repo_path):
            return MergeResult(
                success=False,
                error="A merge is already in progress. Run 'git merge --abort' to cancel it first.",
            )

        pre_merge_commit = git_rev_parse(self.repo_path, "HEAD")

        try:
            # Phase 1: Start merge without committing
            self._start_merge(plan.target_branch)

            # Phase 2: Resolve workflow files
            self._resolve_workflow_files(plan.workflow_resolutions, plan.target_branch)

            # Phase 3: Build and write merged pyproject
            self._build_merged_pyproject(plan)

            # Phase 3.5: Validate merged pyproject resolves
            self._validate_merged_resolution()

            # Phase 4: Stage all changes and commit
            merge_commit = self._commit_merge(plan.target_branch)

            return MergeResult(
                success=True,
                merge_commit=merge_commit,
                workflows_merged=plan.final_workflow_set,
            )

        except Exception as e:
            # Rollback everything
            self._abort_merge(pre_merge_commit=pre_merge_commit)
            return MergeResult(success=False, error=str(e))

    def _start_merge(self, branch: str) -> None:
        """Start merge without committing."""
        _git(["merge", "--no-commit", "--no-ff", branch], self.repo_path)

    def _resolve_workflow_files(
        self, resolutions: dict[str, Resolution], target_branch: str
    ) -> None:
        """Checkout correct version of each workflow based on resolution.

        For take_base: checkout from HEAD (current branch before merge)
        For take_target: checkout from target branch

        This works regardless of whether git detected a conflict.
        """
        for wf_name, resolution in resolutions.items():
            wf_path = f"workflows/{wf_name}.json"

            # Determine which ref to checkout from
            if resolution == "take_base":
                # HEAD is the original branch we're merging INTO
                ref = "HEAD"
            else:
                # target_branch is the branch we're merging FROM
                ref = target_branch

            # Checkout the file from the appropriate ref
            # Use git show to get content, then write it (avoids merge conflicts)
            result = _git(
                ["show", f"{ref}:{wf_path}"],
                self.repo_path,
                check=False,
            )

            if result.returncode == 0:
                # Write the content to the file
                file_path = self.repo_path / wf_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(result.stdout)
                _git(["add", wf_path], self.repo_path)

    def _build_merged_pyproject(self, plan: MergePlan) -> None:
        """Build and write the merged pyproject.toml."""
        from ..utils.git import git_show

        # Get base and target configs
        pyproject_path = Path("pyproject.toml")
        base_content = git_show(self.repo_path, "HEAD", pyproject_path)
        target_content = git_show(self.repo_path, plan.target_branch, pyproject_path)

        from ..utils.toml_compat import tomllib

        base_config = tomllib.loads(base_content) if base_content else {}
        target_config = tomllib.loads(target_content) if target_content else {}

        # Perform semantic merge
        merged_config = self.merger.merge(
            base_config=base_config,
            target_config=target_config,
            workflow_resolutions=plan.workflow_resolutions,
            merged_workflow_files=plan.final_workflow_set,
        )

        # Write merged config
        self.pyproject.save(merged_config)
        _git(["add", "pyproject.toml"], self.repo_path)

    def _commit_merge(self, branch: str) -> str:
        """Commit the merge and return the commit hash."""
        from ..utils.git import git_rev_parse

        _git(
            ["commit", "-m", f"Merge branch '{branch}'"],
            self.repo_path,
        )
        commit_hash: str = git_rev_parse(self.repo_path, "HEAD")
        return commit_hash

    def _validate_merged_resolution(self) -> None:
        """Dry-run resolve merged pyproject to catch unsatisfiable deps."""
        if not self.workspace_path:
            return  # Skip validation if no workspace path available

        from ..models.exceptions import CDDependencyConflictError

        tester = ResolutionTester(self.workspace_path)
        result = tester.test_resolution(self.pyproject.path)
        if not result.success:
            conflicts = "; ".join(result.conflicts[:3]) if result.conflicts else "unknown"
            raise CDDependencyConflictError(
                f"Merged pyproject.toml has unsatisfiable dependencies: {conflicts}"
            )

    def _abort_merge(self, pre_merge_commit: str | None = None) -> None:
        """Abort in-progress merge, falling back to hard reset if needed."""
        result = _git(["merge", "--abort"], self.repo_path, check=False)
        if result.returncode != 0 and pre_merge_commit:
            # Fallback: hard reset to pre-merge state
            _git(["reset", "--hard", pre_merge_commit], self.repo_path, check=False)

    @staticmethod
    def is_merge_in_progress(repo_path: Path) -> bool:
        """Check if a merge is currently in progress."""
        merge_head = repo_path / ".git" / "MERGE_HEAD"
        return merge_head.exists()
