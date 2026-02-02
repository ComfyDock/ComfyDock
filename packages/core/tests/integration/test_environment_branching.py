"""Integration tests for Environment-level git branching operations (Week 2).

Tests the high-level Environment API for git-native branching:
- checkout() - Move HEAD without auto-committing
- reset() - Reset HEAD with mode support (hard/mixed/soft)
- Branch management (create, delete, switch, list)
- Environment synchronization after git operations
- Merge operations with environment reconciliation
"""

import pytest
from comfygit_core.models.exceptions import CDEnvironmentError


class TestEnvironmentCheckout:
    """Test Environment.checkout() - non-destructive navigation."""

    def test_checkout_commit_does_not_auto_commit(self, test_env):
        """checkout() should move HEAD without creating new commit."""
        # ARRANGE: Create v1 and v2
        test_env.git_manager.commit_all("v1: initial")

        # Make a change and commit v2
        (test_env.cec_path / "test.txt").write_text("change")
        test_env.git_manager.commit_all("v2: change")

        # Get commits (get_commit_history returns newest-first)
        history = test_env.get_commit_history(limit=2)
        history[0]["hash"]  # Newest = v2 with test.txt
        v1_hash = history[1]["hash"]  # Older = fixture's initial commit

        # ACT: Checkout v1 (should NOT create v3)
        test_env.checkout(v1_hash, force=True)

        # ASSERT: Still at v1, no new commit created
        # Check HEAD is at v1 (not a new commit)
        from comfygit_core.utils.git import git_rev_parse
        current_hash = git_rev_parse(test_env.cec_path, "HEAD")
        assert current_hash.startswith(v1_hash), "HEAD should be at v1"

        # test.txt should be gone (it was added in v2)
        assert not (test_env.cec_path / "test.txt").exists(), "v2 file should be gone"

    def test_checkout_detached_head_state(self, test_env):
        """checkout() to commit should create detached HEAD."""
        # ARRANGE: Create commit
        test_env.git_manager.commit_all("v1")
        v1_hash = test_env.get_commit_history(limit=1)[0]["hash"]

        # ACT: Checkout specific commit
        test_env.checkout(v1_hash, force=True)

        # ASSERT: Detached HEAD (no branch name)
        current_branch = test_env.get_current_branch()
        assert current_branch is None, "Should be in detached HEAD state"

    def test_checkout_requires_confirmation_for_uncommitted_changes(self, test_env):
        """checkout() should require strategy or force flag if uncommitted changes."""
        # ARRANGE: Create commit and make uncommitted change
        test_env.git_manager.commit_all("v1")
        (test_env.cec_path / "uncommitted.txt").write_text("new")

        v1_hash = test_env.get_commit_history(limit=1)[0]["hash"]

        # ACT & ASSERT: Should raise without force or strategy
        with pytest.raises(CDEnvironmentError, match="uncommitted changes"):
            test_env.checkout(v1_hash)

    def test_checkout_with_force_discards_uncommitted_changes(self, test_env):
        """checkout() with force=True should discard uncommitted changes."""
        # ARRANGE: Create v1 and uncommitted change
        test_env.git_manager.commit_all("v1")
        uncommitted_file = test_env.cec_path / "uncommitted.txt"
        uncommitted_file.write_text("new")
        assert uncommitted_file.exists()

        v1_hash = test_env.get_commit_history(limit=1)[0]["hash"]

        # ACT: Checkout with force
        test_env.checkout(v1_hash, force=True)

        # ASSERT: Uncommitted changes discarded
        assert not uncommitted_file.exists(), "Should discard uncommitted file"


class TestEnvironmentReset:
    """Test Environment.reset() - git reset with modes."""

    def test_reset_hard_discards_all_changes(self, test_env):
        """reset(mode='hard') should discard all uncommitted changes."""
        # ARRANGE: Create commit and uncommitted changes
        test_env.git_manager.commit_all("v1")
        uncommitted = test_env.cec_path / "new.txt"
        uncommitted.write_text("uncommitted")

        # ACT: Hard reset to HEAD
        test_env.reset(ref="HEAD", mode="hard", force=True)

        # ASSERT: Uncommitted changes gone
        assert not uncommitted.exists(), "Hard reset should discard uncommitted files"

    def test_reset_hard_moves_to_previous_commit(self, test_env):
        """reset(mode='hard') to previous commit should move HEAD and discard changes."""
        # ARRANGE: Create v1 and v2
        test_env.git_manager.commit_all("v1")
        v1_hash = test_env.get_commit_history(limit=1)[0]["hash"]

        (test_env.cec_path / "v2.txt").write_text("v2")
        test_env.git_manager.commit_all("v2")

        # ACT: Hard reset to v1
        test_env.reset(ref=v1_hash, mode="hard", force=True)

        # ASSERT: Back at v1, v2.txt gone
        assert not (test_env.cec_path / "v2.txt").exists()
        assert test_env.get_commit_history(limit=1)[0]["hash"] == v1_hash

    def test_reset_mixed_keeps_changes_unstaged(self, test_env):
        """reset(mode='mixed') should keep changes but unstage them."""
        # ARRANGE: Create commit, stage a change
        test_env.git_manager.commit_all("v1")
        new_file = test_env.cec_path / "new.txt"
        new_file.write_text("content")

        # Stage it manually
        from comfygit_core.utils.git import _git
        _git(["add", "new.txt"], test_env.cec_path)

        # ACT: Mixed reset
        test_env.reset(ref="HEAD", mode="mixed", force=True)

        # ASSERT: File still exists but unstaged
        assert new_file.exists(), "File should still exist"
        # Check it's unstaged (appears in status as untracked)
        from comfygit_core.utils.git import git_status_porcelain
        status = git_status_porcelain(test_env.cec_path)
        assert any(entry[2] == "new.txt" for entry in status), "File should be unstaged"

    def test_reset_soft_keeps_changes_staged(self, test_env):
        """reset(mode='soft') should keep changes staged."""
        # ARRANGE: Create v1, then v2 with a file
        test_env.git_manager.commit_all("v1")
        v1_hash = test_env.get_commit_history(limit=1)[0]["hash"]

        new_file = test_env.cec_path / "v2.txt"
        new_file.write_text("v2")
        test_env.git_manager.commit_all("v2")

        # ACT: Soft reset to v1
        test_env.reset(ref=v1_hash, mode="soft", force=True)

        # ASSERT: Back at v1, but v2.txt still staged
        assert new_file.exists(), "File should still exist"
        from comfygit_core.utils.git import get_staged_changes
        staged = get_staged_changes(test_env.cec_path)
        assert "v2.txt" in staged, "File should be staged"


class TestEnvironmentBranchManagement:
    """Test Environment branch management methods."""

    def test_create_branch(self, test_env):
        """Environment.create_branch() should create new branch."""
        # ARRANGE: Initial commit
        test_env.git_manager.commit_all("initial")

        # ACT: Create branch
        test_env.create_branch("feature")

        # ASSERT: Branch exists
        branches = test_env.list_branches()
        branch_names = [name for name, _ in branches]
        assert "feature" in branch_names

    def test_delete_branch(self, test_env):
        """Environment.delete_branch() should delete branch."""
        # ARRANGE: Create and delete branch
        test_env.git_manager.commit_all("initial")
        test_env.create_branch("temp")

        # ACT: Delete it
        test_env.delete_branch("temp")

        # ASSERT: Branch gone
        branches = test_env.list_branches()
        branch_names = [name for name, _ in branches]
        assert "temp" not in branch_names

    def test_switch_branch(self, test_env):
        """Environment.switch_branch() should switch to branch."""
        # ARRANGE: Create branch
        test_env.git_manager.commit_all("initial")
        test_env.create_branch("feature")

        # ACT: Switch to it
        test_env.switch_branch("feature")

        # ASSERT: Now on feature branch
        current = test_env.get_current_branch()
        assert current == "feature"

    def test_switch_branch_with_create(self, test_env):
        """Environment.switch_branch(create=True) should create and switch."""
        # ARRANGE: Initial commit
        test_env.git_manager.commit_all("initial")

        # ACT: Switch with create
        test_env.switch_branch("new-feature", create=True)

        # ASSERT: Branch exists and we're on it
        current = test_env.get_current_branch()
        assert current == "new-feature"

    def test_list_branches(self, test_env):
        """Environment.list_branches() should return all branches."""
        # ARRANGE: Create multiple branches
        test_env.git_manager.commit_all("initial")
        test_env.create_branch("feature1")
        test_env.create_branch("feature2")

        # ACT: List branches
        branches = test_env.list_branches()

        # ASSERT: All branches present
        branch_names = [name for name, _ in branches]
        assert "main" in branch_names
        assert "feature1" in branch_names
        assert "feature2" in branch_names

    def test_get_current_branch(self, test_env):
        """Environment.get_current_branch() should return current branch."""
        # ARRANGE: Initial commit on main
        test_env.git_manager.commit_all("initial")

        # ACT: Get current
        current = test_env.get_current_branch()

        # ASSERT: On main
        assert current == "main"


class TestEnvironmentSyncAfterGitOperations:
    """Test environment synchronization after git operations change HEAD.

    When switching branches or checking out commits, the environment must:
    1. Reload pyproject.toml
    2. Reconcile nodes (add new, remove deleted)
    3. Sync Python environment
    4. Restore workflows
    """

    def test_switch_branch_reloads_pyproject(self, test_env):
        """Switching branches should reload pyproject.toml from new branch."""
        # ARRANGE: Ensure tool.comfygit exists
        config = test_env.pyproject.load()
        if "tool" not in config:
            config["tool"] = {}
        if "comfygit" not in config["tool"]:
            config["tool"]["comfygit"] = {}

        # Create v1 on main with one value
        config["tool"]["comfygit"]["test_value"] = "main_value"
        test_env.pyproject.save(config)
        test_env.git_manager.commit_all("v1: main value")

        # Create feature branch with different value
        test_env.create_branch("feature")
        test_env.switch_branch("feature")
        config = test_env.pyproject.load(force_reload=True)
        config["tool"]["comfygit"]["test_value"] = "feature_value"
        test_env.pyproject.save(config)
        test_env.git_manager.commit_all("v2: feature value")

        # Switch back to main
        test_env.switch_branch("main")

        # ACT: Read value (should trigger reload)
        test_env.pyproject.reset_lazy_handlers()
        config = test_env.pyproject.load(force_reload=True)
        value = config["tool"]["comfygit"]["test_value"]

        # ASSERT: Should have main's value
        assert value == "main_value", "Should reload pyproject from main branch"

    def test_checkout_reloads_pyproject(self, test_env):
        """Checking out commit should reload pyproject.toml."""
        # ARRANGE: Ensure tool.comfygit exists
        config = test_env.pyproject.load()
        if "tool" not in config:
            config["tool"] = {}
        if "comfygit" not in config["tool"]:
            config["tool"]["comfygit"] = {}

        # Create v1 and v2 with different values
        config["tool"]["comfygit"]["test_value"] = "v1"
        test_env.pyproject.save(config)
        test_env.git_manager.commit_all("v1")
        v1_hash = test_env.get_commit_history(limit=10)[0]["hash"]  # Newest commit

        config = test_env.pyproject.load(force_reload=True)
        config["tool"]["comfygit"]["test_value"] = "v2"
        test_env.pyproject.save(config)
        test_env.git_manager.commit_all("v2")

        # ACT: Checkout v1
        test_env.checkout(v1_hash, force=True)

        # Read value
        test_env.pyproject.reset_lazy_handlers()
        config = test_env.pyproject.load(force_reload=True)
        value = config["tool"]["comfygit"]["test_value"]

        # ASSERT: Should have v1's value
        assert value == "v1", "Should reload pyproject from v1 commit"


class TestEnvironmentMerge:
    """Test Environment.merge_branch() with environment reconciliation."""

    def test_merge_branch_fast_forward(self, test_env):
        """Merging branch should fast-forward when possible."""
        # ARRANGE: Create feature branch with commit
        test_env.git_manager.commit_all("v1: initial")

        test_env.create_branch("feature")
        test_env.switch_branch("feature")
        (test_env.cec_path / "feature.txt").write_text("feature")
        test_env.git_manager.commit_all("v2: feature")

        # Switch back to main (commits any uv.lock changes from sync)
        test_env.switch_branch("main")
        if test_env.git_manager.has_uncommitted_changes():
            test_env.git_manager.commit_all("sync after switch")

        # ACT: Merge feature
        test_env.merge_branch("feature")

        # ASSERT: feature.txt now on main
        assert (test_env.cec_path / "feature.txt").exists()

    def test_merge_branch_with_message(self, test_env):
        """Merging with message should create merge commit."""
        # ARRANGE: Create divergent branches
        test_env.git_manager.commit_all("v1: initial")

        # Feature branch
        test_env.create_branch("feature")
        test_env.switch_branch("feature")
        (test_env.cec_path / "feature.txt").write_text("feature")
        test_env.git_manager.commit_all("v2: feature")

        # Back to main, make different commit
        test_env.switch_branch("main")
        if test_env.git_manager.has_uncommitted_changes():
            test_env.git_manager.commit_all("sync after switch to main")

        (test_env.cec_path / "main.txt").write_text("main")
        test_env.git_manager.commit_all("v3: main")

        # ACT: Merge with message
        test_env.merge_branch("feature", message="Merge feature branch")

        # ASSERT: Both files exist
        assert (test_env.cec_path / "feature.txt").exists()
        assert (test_env.cec_path / "main.txt").exists()

        # Latest commit should be merge commit
        history = test_env.get_commit_history(limit=1)
        assert "Merge" in history[0]["message"]  # [0] gets newest (newest-first order)


class TestMergeWithDirtyUvLock:
    """Test that merge succeeds when only uv.lock is dirty.

    BUG: After branch switch, uv.sync_project() regenerates uv.lock, creating
    phantom "uncommitted changes" that block subsequent merges. The merge should
    handle this gracefully since uv.lock gets regenerated anyway after merge.
    """

    def test_merge_succeeds_when_only_uvlock_dirty(self, test_env):
        """Merge should succeed even if uv.lock was modified by branch switch."""
        # ARRANGE: Create feature branch with commit
        test_env.git_manager.commit_all("v1: initial")

        test_env.create_branch("feature")
        test_env.switch_branch("feature")
        (test_env.cec_path / "feature.txt").write_text("feature")
        test_env.git_manager.commit_all("v2: feature")

        # Switch back to main - this may regenerate uv.lock
        test_env.switch_branch("main")

        # Intentionally do NOT commit uv.lock changes - this is the bug scenario
        # The test should pass because merge should handle this gracefully

        # ACT: Merge feature - should NOT fail due to dirty uv.lock
        test_env.merge_branch("feature")

        # ASSERT: feature.txt now on main (merge succeeded)
        assert (test_env.cec_path / "feature.txt").exists()


class TestEnvironmentRevert:
    """Test Environment.revert_commit() - undo commits."""

    def test_revert_commit_creates_new_commit(self, test_env):
        """revert_commit() should create new commit that undoes previous commit."""
        # ARRANGE: Create a file in v1, then another in v2, revert v2
        test_file1 = test_env.cec_path / "file1.txt"
        test_file1.write_text("v1")
        test_env.git_manager.commit_all("v1: add file1")

        test_file2 = test_env.cec_path / "file2.txt"
        test_file2.write_text("v2")
        test_env.git_manager.commit_all("v2: add file2")
        v2_hash = test_env.get_commit_history(limit=10)[0]["hash"]  # Get latest (v2)

        # ACT: Revert v2 (should undo file2 addition)
        test_env.revert_commit(v2_hash)

        # ASSERT: file2 is gone (reverted), file1 still exists
        assert test_file1.exists(), "File1 should still exist"
        assert not test_file2.exists(), "File2 should be reverted"

        # Should have created new commit (Initial, v1, v2, Revert = 4 total)
        history = test_env.get_commit_history(limit=10)
        assert len(history) == 4
        assert "Revert" in history[0]["message"]  # Newest commit is the revert
