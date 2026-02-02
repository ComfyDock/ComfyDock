"""Tests for git remote operations."""
import platform
import subprocess
from pathlib import Path

import pytest


def path_to_git_url(path: Path) -> str:
    """Convert local path to git-compatible URL format.

    On Windows, git push/fetch to local paths works better with file:// URLs.
    On Unix, plain paths work fine.
    """
    if platform.system() == "Windows":
        # Convert to file:// URL (e.g., file:///C:/Users/...)
        return path.as_uri()
    return str(path)


class TestGitRemote:
    """Test git remote management operations."""

    def test_add_remote(self, test_env, tmp_path):
        """Add remote should configure origin."""
        # Create bare remote repo
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote_repo, check=True, capture_output=True)

        # Use test environment
        env = test_env

        # Add remote
        env.git_manager.add_remote("origin", str(remote_repo))

        # Verify remote exists with correct URL
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=env.cec_path,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert str(remote_repo) in result.stdout

    def test_list_remotes(self, test_env, tmp_path):
        """List remotes should return all configured remotes."""
        # Create two bare remotes
        origin_repo = tmp_path / "origin-repo"
        origin_repo.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=origin_repo, check=True, capture_output=True)

        upstream_repo = tmp_path / "upstream-repo"
        upstream_repo.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=upstream_repo, check=True, capture_output=True)

        # Use test environment
        env = test_env

        # Add remotes
        env.git_manager.add_remote("origin", str(origin_repo))
        env.git_manager.add_remote("upstream", str(upstream_repo))

        # List remotes
        remotes = env.git_manager.list_remotes()

        # Should return list of tuples: [(name, url, type), ...]
        assert len(remotes) >= 2

        remote_dict = {name: url for name, url, _ in remotes}
        assert "origin" in remote_dict
        assert "upstream" in remote_dict
        assert str(origin_repo) in remote_dict["origin"]
        assert str(upstream_repo) in remote_dict["upstream"]

    def test_remove_remote(self, test_env, tmp_path):
        """Remove remote should delete configuration."""
        # Create bare remote
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote_repo, check=True, capture_output=True)

        # Use test environment
        env = test_env

        # Add remote
        env.git_manager.add_remote("origin", str(remote_repo))

        # Verify it exists
        assert env.git_manager.has_remote("origin")

        # Remove remote
        env.git_manager.remove_remote("origin")

        # Verify it's gone
        assert not env.git_manager.has_remote("origin")

    def test_add_remote_rejects_duplicate(self, test_env, tmp_path):
        """Add remote should fail if remote already exists."""
        # Create bare remote
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote_repo, check=True, capture_output=True)

        # Use test environment
        env = test_env

        # Add remote
        env.git_manager.add_remote("origin", str(remote_repo))

        # Try to add again - should fail
        with pytest.raises(OSError, match="already exists"):
            env.git_manager.add_remote("origin", str(remote_repo))

    def test_remove_nonexistent_remote_fails(self, test_env):
        """Remove remote should fail with helpful error if remote doesn't exist."""
        # Use test environment (has no remotes by default)
        env = test_env

        # Try to remove non-existent remote
        with pytest.raises(ValueError, match="not found"):
            env.git_manager.remove_remote("origin")

    def test_has_remote(self, test_env, tmp_path):
        """has_remote should correctly detect remote existence."""
        # Create bare remote
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote_repo, check=True, capture_output=True)

        # Use test environment
        env = test_env

        # Initially no remote
        assert not env.git_manager.has_remote("origin")

        # Add remote
        env.git_manager.add_remote("origin", str(remote_repo))

        # Now has remote
        assert env.git_manager.has_remote("origin")

        # Still no upstream
        assert not env.git_manager.has_remote("upstream")


class TestGitRemoteSetUrl:
    """Test git remote URL update operations."""

    def test_set_remote_url_fetch(self, test_env, tmp_path):
        """set_remote_url should update fetch URL."""
        # Create two bare remotes
        old_remote = tmp_path / "old-remote"
        old_remote.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=old_remote, check=True, capture_output=True)

        new_remote = tmp_path / "new-remote"
        new_remote.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=new_remote, check=True, capture_output=True)

        env = test_env

        # Add remote with old URL
        env.git_manager.add_remote("origin", str(old_remote))

        # Update to new URL
        env.git_manager.set_remote_url("origin", str(new_remote))

        # Verify URL changed
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=env.cec_path,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert str(new_remote) in result.stdout

    def test_set_remote_url_push(self, test_env, tmp_path):
        """set_remote_url should update push URL when is_push=True."""
        # Create remotes
        fetch_remote = tmp_path / "fetch-remote"
        fetch_remote.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=fetch_remote, check=True, capture_output=True)

        push_remote = tmp_path / "push-remote"
        push_remote.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=push_remote, check=True, capture_output=True)

        env = test_env

        # Add remote
        env.git_manager.add_remote("origin", str(fetch_remote))

        # Set different push URL
        env.git_manager.set_remote_url("origin", str(push_remote), is_push=True)

        # Verify push URL is different
        result = subprocess.run(
            ["git", "remote", "get-url", "--push", "origin"],
            cwd=env.cec_path,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert str(push_remote) in result.stdout

        # Verify fetch URL unchanged
        fetch_result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=env.cec_path,
            capture_output=True,
            text=True
        )
        assert str(fetch_remote) in fetch_result.stdout

    def test_set_remote_url_nonexistent_fails(self, test_env):
        """set_remote_url should fail for non-existent remote."""
        env = test_env

        with pytest.raises((ValueError, OSError)):
            env.git_manager.set_remote_url("nonexistent", "https://example.com/repo.git")


class TestGitFetch:
    """Test git fetch operations via GitManager."""

    def test_fetch_from_remote(self, test_env, tmp_path):
        """fetch should retrieve updates from remote."""
        # Create bare remote with a commit
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote_repo, check=True, capture_output=True)

        env = test_env

        # Add remote
        env.git_manager.add_remote("origin", str(remote_repo))

        # Push our initial commit to remote
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=env.cec_path,
            capture_output=True
        )

        # Fetch should succeed (even with nothing new)
        env.git_manager.fetch("origin")

    def test_fetch_nonexistent_remote_fails(self, test_env):
        """fetch should fail for non-existent remote."""
        env = test_env

        with pytest.raises(ValueError, match="not configured"):
            env.git_manager.fetch("nonexistent")


class TestGitSyncStatus:
    """Test git sync status (ahead/behind counts)."""

    def test_get_sync_status_no_remote_tracking(self, test_env):
        """get_sync_status should return zeros when no remote tracking."""
        env = test_env

        # No remote configured, should handle gracefully
        status = env.git_manager.get_sync_status()
        assert status["ahead"] == 0
        assert status["behind"] == 0

    def test_get_sync_status_with_commits_ahead(self, test_env, tmp_path):
        """get_sync_status should count local commits ahead of remote."""
        # Create bare remote
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote_repo, check=True, capture_output=True)

        env = test_env

        # Add remote and push
        env.git_manager.add_remote("origin", str(remote_repo))
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=env.cec_path,
            capture_output=True
        )

        # Make a local commit
        (env.cec_path / "test-file.txt").write_text("test content")
        env.git_manager.commit_with_identity("Add test file")

        # Fetch to update remote refs
        env.git_manager.fetch("origin")

        # Should be 1 ahead
        status = env.git_manager.get_sync_status("origin")
        assert status["ahead"] == 1
        assert status["behind"] == 0

    def test_get_sync_status_with_commits_behind(self, test_env, tmp_path):
        """get_sync_status should count remote commits we're behind."""
        # Create non-bare remote (so we can add commits to it)
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)

        # Create initial commit in remote
        (remote_repo / "initial.txt").write_text("initial")
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)

        # Convert to bare (by cloning)
        bare_remote = tmp_path / "bare-remote"
        subprocess.run(["git", "clone", "--bare", str(remote_repo), str(bare_remote)], check=True, capture_output=True)

        env = test_env

        # Add remote and fetch
        env.git_manager.add_remote("origin", str(bare_remote))
        env.git_manager.fetch("origin")

        # Set up tracking
        subprocess.run(
            ["git", "branch", "-u", "origin/main", "main"],
            cwd=env.cec_path,
            capture_output=True
        )

        # Add commit to remote (via the non-bare repo, then push)
        (remote_repo / "new-file.txt").write_text("new content")
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "New commit"], cwd=remote_repo, check=True, capture_output=True)
        # Push to bare remote - need to specify branch explicitly
        subprocess.run(["git", "push", path_to_git_url(bare_remote), "main"], cwd=remote_repo, check=True, capture_output=True)

        # Fetch to get the new commit
        env.git_manager.fetch("origin")

        # Should be behind
        status = env.git_manager.get_sync_status("origin")
        assert status["behind"] >= 1
