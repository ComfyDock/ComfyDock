"""Unit tests for AtomicMergeExecutor.

Tests the atomic merge execution with rollback on failure.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from comfygit_core.merging.atomic_executor import AtomicMergeExecutor
from comfygit_core.models.merge_plan import MergePlan


class TestAtomicMergeExecutor:
    """Test AtomicMergeExecutor functionality."""

    def test_is_merge_in_progress_detects_merge(self, tmp_path):
        """Detects when a merge is in progress."""
        # Create a mock git repo with MERGE_HEAD
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "MERGE_HEAD").write_text("abc123")

        assert AtomicMergeExecutor.is_merge_in_progress(tmp_path)

    def test_is_merge_in_progress_false_when_clean(self, tmp_path):
        """Returns false when no merge in progress."""
        # Create a mock git repo without MERGE_HEAD
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        assert not AtomicMergeExecutor.is_merge_in_progress(tmp_path)

    def test_rollback_on_failure(self, tmp_path):
        """Merge rolls back on failure."""
        # Create a mock pyproject manager
        mock_pyproject = MagicMock()

        executor = AtomicMergeExecutor(
            repo_path=tmp_path,
            pyproject_manager=mock_pyproject,
        )

        plan = MergePlan(
            target_branch="feature",
            base_ref="HEAD",
            workflow_resolutions={},
            final_workflow_set=[],
        )

        # Mock _start_merge to fail
        with patch.object(executor, "_start_merge", side_effect=Exception("Merge conflict")):
            with patch.object(executor, "_abort_merge") as mock_abort:
                result = executor.execute(plan)

        assert not result.success
        assert "Merge conflict" in result.error
        mock_abort.assert_called_once()

    def test_successful_merge_returns_commit(self, tmp_path):
        """Successful merge returns commit hash."""
        mock_pyproject = MagicMock()

        executor = AtomicMergeExecutor(
            repo_path=tmp_path,
            pyproject_manager=mock_pyproject,
        )

        plan = MergePlan(
            target_branch="feature",
            base_ref="HEAD",
            workflow_resolutions={"wf1": "take_base"},
            final_workflow_set=["wf1"],
        )

        # Mock all the git operations
        with patch.object(executor, "_start_merge"):
            with patch.object(executor, "_resolve_workflow_files"):
                with patch.object(executor, "_build_merged_pyproject"):
                    with patch.object(executor, "_commit_merge", return_value="abc123"):
                        result = executor.execute(plan)

        assert result.success
        assert result.merge_commit == "abc123"
        assert result.workflows_merged == ["wf1"]

    def test_execute_refuses_when_merge_in_progress(self, tmp_path):
        """execute() returns failure if MERGE_HEAD already exists."""
        # Create a mock git repo with MERGE_HEAD (stale merge state)
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "MERGE_HEAD").write_text("abc123")

        mock_pyproject = MagicMock()
        executor = AtomicMergeExecutor(
            repo_path=tmp_path,
            pyproject_manager=mock_pyproject,
        )

        plan = MergePlan(
            target_branch="feature",
            base_ref="HEAD",
            workflow_resolutions={},
            final_workflow_set=[],
        )

        # Should refuse to start without attempting the merge
        with patch.object(executor, "_start_merge") as mock_start:
            result = executor.execute(plan)

        assert not result.success
        assert "already in progress" in result.error
        mock_start.assert_not_called()

    def test_abort_merge_falls_back_to_reset(self, tmp_path):
        """_abort_merge falls back to git reset --hard when merge --abort fails."""
        mock_pyproject = MagicMock()
        executor = AtomicMergeExecutor(
            repo_path=tmp_path,
            pyproject_manager=mock_pyproject,
        )

        # Mock _git: first call (merge --abort) fails, second call (reset --hard) succeeds
        mock_results = [
            MagicMock(returncode=1),  # merge --abort fails
            MagicMock(returncode=0),  # reset --hard succeeds
        ]

        with patch("comfygit_core.merging.atomic_executor._git", side_effect=mock_results) as mock_git:
            executor._abort_merge(pre_merge_commit="abc123")

        assert mock_git.call_count == 2
        # First call: merge --abort
        assert mock_git.call_args_list[0][0][0] == ["merge", "--abort"]
        # Second call: reset --hard
        assert mock_git.call_args_list[1][0][0] == ["reset", "--hard", "abc123"]

    def test_abort_merge_no_fallback_without_commit(self, tmp_path):
        """_abort_merge does not fall back if no pre_merge_commit provided."""
        mock_pyproject = MagicMock()
        executor = AtomicMergeExecutor(
            repo_path=tmp_path,
            pyproject_manager=mock_pyproject,
        )

        mock_result = MagicMock(returncode=1)  # merge --abort fails

        with patch("comfygit_core.merging.atomic_executor._git", return_value=mock_result) as mock_git:
            executor._abort_merge()

        # Should only call merge --abort, no fallback
        mock_git.assert_called_once()

    def test_resolution_validation_aborts_on_failure(self, tmp_path):
        """Merge aborts if merged pyproject fails resolution validation."""
        mock_pyproject = MagicMock()
        mock_pyproject.path = tmp_path / "pyproject.toml"

        executor = AtomicMergeExecutor(
            repo_path=tmp_path,
            pyproject_manager=mock_pyproject,
        )

        plan = MergePlan(
            target_branch="feature",
            base_ref="HEAD",
            workflow_resolutions={},
            final_workflow_set=[],
        )

        # Mock a failed resolution result
        mock_resolution_result = MagicMock()
        mock_resolution_result.success = False
        mock_resolution_result.conflicts = ["pkg-a>=2.0 conflicts with pkg-b<1.5"]

        mock_tester = MagicMock()
        mock_tester.test_resolution.return_value = mock_resolution_result

        with patch.object(executor, "_start_merge"):
            with patch.object(executor, "_resolve_workflow_files"):
                with patch.object(executor, "_build_merged_pyproject"):
                    with patch.object(executor, "_abort_merge") as mock_abort:
                        with patch("comfygit_core.merging.atomic_executor.git_rev_parse", return_value="pre123"):
                            with patch("comfygit_core.merging.atomic_executor.ResolutionTester", return_value=mock_tester):
                                result = executor.execute(plan)

        assert not result.success
        assert "unsatisfiable" in result.error.lower() or "conflicts" in result.error.lower()
        mock_abort.assert_called_once()
