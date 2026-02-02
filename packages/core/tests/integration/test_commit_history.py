"""Test commit history retrieval with short git hashes.

This replaces the version numbering system (v1, v2, v3) with native git commit hashes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCommitHistory:
    """Test commit history retrieval with short hashes."""

    def test_commit_history_format(self, test_env):
        """Commit history should return hash, message, date, date_relative."""
        # ARRANGE: Create a commit
        pyproject_path = test_env.cec_path / "pyproject.toml"
        with open(pyproject_path, 'a') as f:
            f.write("\n# Test commit")
        test_env.git_manager.commit_with_identity("Test commit")

        # ACT
        history = test_env.git_manager.get_version_history(limit=10)

        # ASSERT
        assert len(history) > 0
        commit = history[0]  # Newest first

        # Check required keys
        assert 'hash' in commit
        assert 'message' in commit
        assert 'date' in commit
        assert 'date_relative' in commit

        # Verify hash format (7 chars, hex)
        assert len(commit['hash']) == 7
        assert all(c in '0123456789abcdef' for c in commit['hash'].lower())

        # Verify newest commit is our test commit
        assert commit['message'] == "Test commit"

    def test_commit_history_ordering(self, test_env):
        """Commit history should be newest first."""
        # ARRANGE: Create 3 commits with distinctive messages
        pyproject_path = test_env.cec_path / "pyproject.toml"
        messages = ["First", "Second", "Third"]

        for msg in messages:
            with open(pyproject_path, 'a') as f:
                f.write(f"\n# {msg}")
            test_env.git_manager.commit_with_identity(msg)

        # ACT
        history = test_env.git_manager.get_version_history(limit=10)

        # ASSERT: Find our commits
        our_commits = [c for c in history if c['message'] in messages]
        assert len(our_commits) == 3

        # Should be newest first
        assert our_commits[0]['message'] == "Third"
        assert our_commits[1]['message'] == "Second"
        assert our_commits[2]['message'] == "First"

    def test_commit_hash_uniqueness(self, test_env):
        """Each commit should have a unique hash."""
        # ARRANGE: Create 10 commits
        pyproject_path = test_env.cec_path / "pyproject.toml"

        for i in range(10):
            with open(pyproject_path, 'a') as f:
                f.write(f"\n# Commit {i}")
            test_env.git_manager.commit_with_identity(f"Commit {i}")

        # ACT
        history = test_env.git_manager.get_version_history(limit=20)

        # ASSERT
        hashes = [c['hash'] for c in history]
        assert len(hashes) == len(set(hashes)), "Duplicate hashes found!"

    def test_limit_parameter(self, test_env):
        """Limit parameter should restrict number of commits returned."""
        # ARRANGE: Create 15 commits
        pyproject_path = test_env.cec_path / "pyproject.toml"

        for i in range(15):
            with open(pyproject_path, 'a') as f:
                f.write(f"\n# Commit {i}")
            test_env.git_manager.commit_with_identity(f"Commit {i}")

        # ACT
        history_5 = test_env.git_manager.get_version_history(limit=5)
        history_10 = test_env.git_manager.get_version_history(limit=10)

        # ASSERT
        assert len(history_5) <= 5
        assert len(history_10) <= 10

        # Both should have same newest commit
        assert history_5[0]['hash'] == history_10[0]['hash']


class TestRollbackWithHashes:
    """Test rollback operations using commit hashes."""

    def test_rollback_with_short_hash(self, test_env):
        """Rollback should work with 7-character hash."""
        # ARRANGE: Create 3 commits
        pyproject_path = test_env.cec_path / "pyproject.toml"

        for i in range(3):
            with open(pyproject_path, 'a') as f:
                f.write(f"\n# Commit {i}")
            test_env.git_manager.commit_with_identity(f"Commit {i}")

        # Get hash of second commit (Commit 1)
        history = test_env.git_manager.get_version_history(limit=10)
        second_commit = [c for c in history if c['message'] == "Commit 1"][0]
        target_hash = second_commit['hash']

        # ACT
        test_env.reset(target_hash, mode="hard", force=True)

        # ASSERT: Should be at second commit
        pyproject_content = (test_env.cec_path / "pyproject.toml").read_text()
        assert "# Commit 1" in pyproject_content
        assert "# Commit 2" not in pyproject_content

    def test_rollback_with_partial_hash(self, test_env):
        """Rollback should work with 4+ character hash prefix."""
        # ARRANGE
        pyproject_path = test_env.cec_path / "pyproject.toml"
        with open(pyproject_path, 'a') as f:
            f.write("\n# Test")
        test_env.git_manager.commit_with_identity("Test commit")

        history = test_env.git_manager.get_version_history(limit=1)
        full_hash = history[0]['hash']  # 7 chars
        partial_hash = full_hash[:4]    # 4 chars

        # Make another commit
        with open(pyproject_path, 'a') as f:
            f.write("\n# Another")
        test_env.git_manager.commit_with_identity("Another commit")

        # ACT: Reset using 4-char hash
        test_env.reset(partial_hash, mode="hard", force=True)

        # ASSERT
        pyproject_content = (test_env.cec_path / "pyproject.toml").read_text()
        assert "# Test" in pyproject_content
        assert "# Another" not in pyproject_content


class TestCommitSummary:
    """Test commit summary with hash-based info."""

    def test_commit_summary_uses_hashes(self, test_env):
        """Commit summary should use 'current_commit' not 'current_version'."""
        # ARRANGE: Create a commit
        pyproject_path = test_env.cec_path / "pyproject.toml"
        with open(pyproject_path, 'a') as f:
            f.write("\n# Summary test")
        test_env.git_manager.commit_with_identity("Summary test")

        # ACT
        summary = test_env.git_manager.get_commit_summary()

        # ASSERT
        assert 'current_commit' in summary
        assert 'total_commits' in summary
        assert 'latest_message' in summary
        assert 'has_uncommitted_changes' in summary

        # current_commit should be a 7-char hash
        assert len(summary['current_commit']) == 7
        assert all(c in '0123456789abcdef' for c in summary['current_commit'].lower())

        # latest_message should match our commit
        assert summary['latest_message'] == "Summary test"
