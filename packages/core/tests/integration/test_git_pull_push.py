"""Tests for git pull/push operations."""
import subprocess
from unittest.mock import patch

import pytest
from comfygit_core.models.exceptions import CDEnvironmentError


class TestGitPull:
    """Test pull operations (fetch + merge)."""

    def test_pull_fetches_and_merges(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Pull should fetch and merge from current branch."""
        # Create a remote repo with .cec structure
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()

        # Initialize remote as git repo
        subprocess.run(["git", "init"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        # Create initial content in remote
        pyproject_content = """
[project]
name = "test-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (remote_repo / "pyproject.toml").write_text(pyproject_content)
        (remote_repo / ".python-version").write_text("3.12\n")
        workflows_dir = remote_repo / "workflows"
        workflows_dir.mkdir()
        (workflows_dir / "test.json").write_text('{"nodes": []}')

        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)

        # Import from remote (fixture mocks UV and ComfyUI operations)
        env = test_workspace.import_from_git(
            git_url=str(remote_repo),
            name="test-pull",
            model_strategy="skip"
        )

        # Make change in remote
        (remote_repo / "workflows" / "new_workflow.json").write_text('{"new": true}')
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add new workflow"], cwd=remote_repo, check=True, capture_output=True)

        # Pull should fetch and merge the new workflow
        # This will fail until pull_and_repair is implemented
        result = env.pull_and_repair(remote="origin")

        # Verify fetch and merge happened
        assert result is not None
        assert "fetch_output" in result
        assert "merge_output" in result
        assert "branch" in result

        # Verify new workflow was pulled
        assert (env.cec_path / "workflows" / "new_workflow.json").exists()

    def test_pull_rejects_with_uncommitted_changes(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Pull should reject if uncommitted changes exist."""
        # Create remote repo
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        pyproject_content = """
[project]
name = "test-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (remote_repo / "pyproject.toml").write_text(pyproject_content)
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)

        # Import environment (fixture mocks UV and ComfyUI operations)
        env = test_workspace.import_from_git(
            git_url=str(remote_repo),
            name="test-pull-dirty",
            model_strategy="skip"
        )

        # Make local uncommitted change
        (env.cec_path / "workflows" / "local_change.json").write_text('{"local": true}')

        # Pull should fail with CDEnvironmentError
        with pytest.raises(CDEnvironmentError, match="uncommitted changes"):
            env.pull_and_repair(remote="origin")

    def test_pull_detects_current_branch(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Pull should auto-detect and use current branch."""
        # Create remote repo with feature branch
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        pyproject_content = """
[project]
name = "test-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (remote_repo / "pyproject.toml").write_text(pyproject_content)
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)

        # Create feature branch with different content
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=remote_repo, check=True, capture_output=True)
        (remote_repo / "workflows").mkdir(exist_ok=True)
        (remote_repo / "workflows" / "feature.json").write_text('{"feature": true}')
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Feature branch"], cwd=remote_repo, check=True, capture_output=True)

        # Import from feature branch (fixture mocks UV and ComfyUI operations)
        env = test_workspace.import_from_git(
            git_url=str(remote_repo),
            name="test-pull-branch",
            branch="feature",
            model_strategy="skip"
        )

        # Verify we're on feature branch
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=env.cec_path,
            capture_output=True,
            text=True
        )
        assert "feature" in result.stdout

        # Make change in remote feature branch
        (remote_repo / "workflows" / "feature2.json").write_text('{"feature2": true}')
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "More feature work"], cwd=remote_repo, check=True, capture_output=True)

        # Pull should auto-detect feature branch (not main)
        result = env.pull_and_repair(remote="origin")

        # Verify it pulled from feature branch
        assert result["branch"] == "feature"
        assert (env.cec_path / "workflows" / "feature2.json").exists()

    def test_pull_rollback_on_sync_failure(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Pull should rollback git changes if sync fails (atomic operation)."""
        # Create remote repo
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        pyproject_content = """
[project]
name = "test-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (remote_repo / "pyproject.toml").write_text(pyproject_content)
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)

        # Import environment (fixture mocks UV and ComfyUI operations)
        env = test_workspace.import_from_git(
            git_url=str(remote_repo),
            name="test-pull-rollback",
            model_strategy="skip"
        )

        # Get initial commit hash
        initial_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=env.cec_path,
            capture_output=True,
            text=True
        ).stdout.strip()

        # Make change in remote
        (remote_repo / "workflows").mkdir(exist_ok=True)
        (remote_repo / "workflows" / "bad.json").write_text('{"bad": true}')
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Bad change"], cwd=remote_repo, check=True, capture_output=True)

        # Mock sync to fail
        with patch.object(env, 'sync') as mock_sync:
            from comfygit_core.models.sync import SyncResult
            mock_sync.return_value = SyncResult(
                success=False,
                errors=["Sync failed"]
            )

            # Pull should fail and rollback
            with pytest.raises(CDEnvironmentError, match="Sync failed"):
                env.pull_and_repair(remote="origin")

        # Verify rollback happened - should be back to initial commit
        current_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=env.cec_path,
            capture_output=True,
            text=True
        ).stdout.strip()

        assert current_commit == initial_commit
        assert not (env.cec_path / "workflows" / "bad.json").exists()


class TestGitPush:
    """Test push operations."""

    def test_push_pushes_commits(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Push should push committed changes to current branch."""
        # Create bare remote repo
        bare_repo = tmp_path / "bare-repo"
        bare_repo.mkdir()
        subprocess.run(["git", "init", "--bare", "-b", "main"], cwd=bare_repo, check=True, capture_output=True)

        # Create regular remote repo to populate bare repo
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        pyproject_content = """
[project]
name = "test-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (remote_repo / "pyproject.toml").write_text(pyproject_content)
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(bare_repo)], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=remote_repo, check=True, capture_output=True)

        # Import from bare repo (fixture mocks UV and ComfyUI operations)
        env = test_workspace.import_from_git(
            git_url=str(bare_repo),
            name="test-push",
            model_strategy="skip"
        )

        # Make and commit local change
        workflows_dir = env.cec_path / "workflows"
        workflows_dir.mkdir(exist_ok=True)
        (workflows_dir / "new.json").write_text('{"new": true}')
        env.git_manager.commit_with_identity("Add new workflow")

        # Push should succeed
        result = env.push_commits(remote="origin")

        assert result is not None

        # Verify push succeeded by cloning bare repo and checking content
        verify_repo = tmp_path / "verify-repo"
        subprocess.run(["git", "clone", str(bare_repo), str(verify_repo)], check=True, capture_output=True)
        assert (verify_repo / "workflows" / "new.json").exists()

    def test_push_fails_with_uncommitted_changes(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Push should fail if uncommitted changes exist."""
        # Create bare remote
        bare_repo = tmp_path / "bare-repo"
        bare_repo.mkdir()
        subprocess.run(["git", "init", "--bare", "-b", "main"], cwd=bare_repo, check=True, capture_output=True)

        # Create and push initial content
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        pyproject_content = """
[project]
name = "test-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (remote_repo / "pyproject.toml").write_text(pyproject_content)
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(bare_repo)], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=remote_repo, check=True, capture_output=True)

        # Import environment (fixture mocks UV and ComfyUI operations)
        env = test_workspace.import_from_git(
            git_url=str(bare_repo),
            name="test-push-dirty",
            model_strategy="skip"
        )

        # Make uncommitted change
        workflows_dir = env.cec_path / "workflows"
        workflows_dir.mkdir(exist_ok=True)
        (workflows_dir / "uncommitted.json").write_text('{"uncommitted": true}')

        # Push should fail
        with pytest.raises(CDEnvironmentError, match="uncommitted changes"):
            env.push_commits(remote="origin")

    def test_push_auto_detects_branch(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Push should auto-detect current branch instead of assuming main."""
        # Create bare remote
        bare_repo = tmp_path / "bare-repo"
        bare_repo.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=bare_repo, check=True, capture_output=True)

        # Create repo with feature branch
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        pyproject_content = """
[project]
name = "test-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (remote_repo / "pyproject.toml").write_text(pyproject_content)
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)

        # Create and push feature branch
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(bare_repo)], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "push", "-u", "origin", "feature"], cwd=remote_repo, check=True, capture_output=True)

        # Import from feature branch (fixture mocks UV and ComfyUI operations)
        env = test_workspace.import_from_git(
            git_url=str(bare_repo),
            name="test-push-branch",
            branch="feature",
            model_strategy="skip"
        )

        # Make and commit change
        workflows_dir = env.cec_path / "workflows"
        workflows_dir.mkdir(exist_ok=True)
        (workflows_dir / "feature_work.json").write_text('{"feature": true}')
        env.git_manager.commit_with_identity("Feature work")

        # Push should auto-detect feature branch
        env.push_commits(remote="origin")

        # Verify it pushed to feature branch (not main)
        verify_repo = tmp_path / "verify-repo"
        subprocess.run(["git", "clone", "-b", "feature", str(bare_repo), str(verify_repo)], check=True, capture_output=True)
        assert (verify_repo / "workflows" / "feature_work.json").exists()


class TestGitPullForce:
    """Test force pull operations."""

    def test_pull_force_allows_uncommitted_changes(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Pull with --force should allow pulling even with uncommitted changes."""
        # Create remote repo
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        pyproject_content = """
[project]
name = "test-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (remote_repo / "pyproject.toml").write_text(pyproject_content)
        (remote_repo / ".python-version").write_text("3.12\n")
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)

        # Import environment
        env = test_workspace.import_from_git(
            git_url=str(remote_repo),
            name="test-pull-force",
            model_strategy="skip"
        )

        # Make local uncommitted change
        workflows_dir = env.cec_path / "workflows"
        workflows_dir.mkdir(exist_ok=True)
        (workflows_dir / "local_change.json").write_text('{"local": true}')

        # Make change in remote
        (remote_repo / "workflows").mkdir(exist_ok=True)
        (remote_repo / "workflows" / "remote.json").write_text('{"remote": true}')
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Remote change"], cwd=remote_repo, check=True, capture_output=True)

        # Pull with force=True should succeed (discarding local changes)
        result = env.pull_and_repair(remote="origin", force=True)

        # Verify remote changes were pulled
        assert result is not None
        assert (env.cec_path / "workflows" / "remote.json").exists()
        # Local uncommitted changes should be discarded
        assert not (env.cec_path / "workflows" / "local_change.json").exists()

    def test_pull_force_handles_unrelated_histories(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Pull with --force should handle 'unrelated histories' error."""
        # Create first repo (will be the remote) with a different initial commit
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        remote_pyproject = """
[project]
name = "remote-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (remote_repo / "pyproject.toml").write_text(remote_pyproject)
        (remote_repo / ".python-version").write_text("3.12\n")
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Remote initial"], cwd=remote_repo, check=True, capture_output=True)

        # Import from a DIFFERENT repo first to get an env with unrelated history
        # Create another repo for initial import
        first_repo = tmp_path / "first-repo"
        first_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=first_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=first_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=first_repo, check=True, capture_output=True)

        first_pyproject = """
[project]
name = "first-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (first_repo / "pyproject.toml").write_text(first_pyproject)
        (first_repo / ".python-version").write_text("3.12\n")
        subprocess.run(["git", "add", "."], cwd=first_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "First initial"], cwd=first_repo, check=True, capture_output=True)

        # Import from first repo
        env = test_workspace.import_from_git(
            git_url=str(first_repo),
            name="test-unrelated",
            model_strategy="skip"
        )

        # Now replace origin with the remote_repo (which has unrelated history)
        from comfygit_core.utils.git import git_remote_add, git_remote_remove
        git_remote_remove(env.cec_path, "origin")
        git_remote_add(env.cec_path, "origin", str(remote_repo))

        # Without --force, pull should fail with "unrelated histories" error
        with pytest.raises(OSError, match="(?i)unrelated"):
            env.pull_and_repair(remote="origin")

        # With force=True AND strategy_option="theirs", pull should succeed
        # by using --allow-unrelated-histories and resolving conflicts with remote's version
        result = env.pull_and_repair(remote="origin", force=True, strategy_option="theirs")

        assert result is not None
        # The remote's pyproject.toml should now have remote's content
        assert "remote-env" in (env.cec_path / "pyproject.toml").read_text()
        assert result['branch'] == "main"


class TestGitPushForce:
    """Test force push operations."""

    def test_push_force_uses_force_with_lease_first(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Force push should try --force-with-lease first (safe)."""
        # Create bare remote
        bare_repo = tmp_path / "bare-repo"
        bare_repo.mkdir()
        subprocess.run(["git", "init", "--bare", "-b", "main"], cwd=bare_repo, check=True, capture_output=True)

        # Create and push initial content
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        pyproject_content = """
[project]
name = "test-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (remote_repo / "pyproject.toml").write_text(pyproject_content)
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(bare_repo)], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=remote_repo, check=True, capture_output=True)

        # Import environment
        env = test_workspace.import_from_git(
            git_url=str(bare_repo),
            name="test-push-force",
            model_strategy="skip"
        )

        # Make and commit a change
        workflows_dir = env.cec_path / "workflows"
        workflows_dir.mkdir(exist_ok=True)
        (workflows_dir / "new.json").write_text('{"new": true}')
        env.git_manager.commit_with_identity("Add new workflow")

        # Rewind the bare repo to simulate divergence
        # Clone bare repo, reset to parent, force push
        diverge_repo = tmp_path / "diverge-repo"
        subprocess.run(["git", "clone", str(bare_repo), str(diverge_repo)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=diverge_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=diverge_repo, check=True, capture_output=True)
        (diverge_repo / "diverge.txt").write_text("diverged")
        subprocess.run(["git", "add", "."], cwd=diverge_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Diverge"], cwd=diverge_repo, check=True, capture_output=True)
        subprocess.run(["git", "push", "--force", "origin", "main"], cwd=diverge_repo, check=True, capture_output=True)

        # Normal push should fail (remote diverged)
        with pytest.raises(OSError, match="rejected"):
            env.push_commits(remote="origin", force=False)

        # Force push should succeed by retrying with true --force after --force-with-lease fails
        result = env.push_commits(remote="origin", force=True)
        assert result is not None

        # Verify our content is now in remote
        verify_repo = tmp_path / "verify-repo"
        subprocess.run(["git", "clone", str(bare_repo), str(verify_repo)], check=True, capture_output=True)
        assert (verify_repo / "workflows" / "new.json").exists()
        # The diverged content should be gone
        assert not (verify_repo / "diverge.txt").exists()
