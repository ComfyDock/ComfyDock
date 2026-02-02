"""Integration tests for dev node improvements.

Three key improvements:
1. Remove .disabled behavior for dev nodes - just untrack, don't touch filesystem
2. Capture git info on --dev add - repository/branch/commit captured immediately
3. Auto-refresh dev node requirements on sync - pick up requirement changes

See: .claude/context/shared/plans/2025-12-27-implementation-plan-dev-node-improvement.md
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestDevNodeRemoveNoDisabled:
    """Dev node removal should just untrack, not create .disabled directory."""

    def test_remove_dev_node_does_not_create_disabled_directory(self, test_env):
        """Removing a dev node should NOT create a .disabled directory."""
        # ARRANGE - Create and track a dev node
        dev_node_path = test_env.comfyui_path / "custom_nodes" / "my-dev-node"
        dev_node_path.mkdir(parents=True)
        (dev_node_path / "nodes.py").write_text("# dev node code")

        test_env.node_manager.add_node("my-dev-node", is_development=True)

        # Verify it's tracked
        nodes = test_env.pyproject.nodes.get_existing()
        assert "my-dev-node" in nodes

        # ACT - Remove the dev node (no untrack_only flag)
        result = test_env.node_manager.remove_node("my-dev-node")

        # ASSERT
        # Node should be untracked from pyproject
        nodes = test_env.pyproject.nodes.get_existing()
        assert "my-dev-node" not in nodes, "Dev node should be untracked"

        # Filesystem should be completely untouched - directory still exists
        assert dev_node_path.exists(), "Dev node directory should still exist"
        assert (dev_node_path / "nodes.py").read_text() == "# dev node code", (
            "Dev node files should be preserved"
        )

        # NO .disabled directory should be created
        disabled_path = test_env.comfyui_path / "custom_nodes" / "my-dev-node.disabled"
        assert not disabled_path.exists(), (
            "Dev node should NOT be renamed to .disabled - filesystem unchanged"
        )

        # Result should indicate no filesystem action
        assert result.filesystem_action == "none", (
            "Filesystem action should be 'none' for dev node removal"
        )

    def test_remove_dev_node_symlink_preserved(self, test_env, tmp_path):
        """Removing a symlinked dev node should preserve the symlink."""
        # ARRANGE - Create a dev node as a symlink to external repo
        external_repo = tmp_path / "external-repo"
        external_repo.mkdir()
        (external_repo / "nodes.py").write_text("# external code")

        # Create symlink in custom_nodes
        dev_node_link = test_env.comfyui_path / "custom_nodes" / "symlinked-dev"
        dev_node_link.symlink_to(external_repo)

        test_env.node_manager.add_node("symlinked-dev", is_development=True)

        # ACT - Remove the dev node
        test_env.node_manager.remove_node("symlinked-dev")

        # ASSERT - Symlink should still exist
        assert dev_node_link.exists(), "Symlink should still exist"
        assert dev_node_link.is_symlink(), "Should still be a symlink"
        assert dev_node_link.resolve() == external_repo, "Symlink target should be preserved"


class TestDevNodeGitInfoOnAdd:
    """Dev node add --dev should capture git info immediately."""

    def test_add_dev_node_captures_repository_url(self, test_env):
        """Adding a dev node with git remote should capture repository URL."""
        # ARRANGE - Create a dev node with git repo
        dev_node_path = test_env.comfyui_path / "custom_nodes" / "git-dev-node"
        dev_node_path.mkdir(parents=True)
        (dev_node_path / "nodes.py").write_text("# dev node code")

        # Initialize git repo with remote
        subprocess.run(["git", "init"], cwd=dev_node_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/user/git-dev-node.git"],
            cwd=dev_node_path, capture_output=True, check=True
        )
        subprocess.run(["git", "add", "."], cwd=dev_node_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=dev_node_path, capture_output=True, check=True,
            env={**subprocess.os.environ,
                 "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"}
        )

        # ACT - Add as dev node
        node_info = test_env.node_manager.add_node("git-dev-node", is_development=True)

        # ASSERT - Git info should be captured immediately
        assert node_info.repository == "https://github.com/user/git-dev-node.git", (
            "Repository URL should be captured on add"
        )

        # Verify it's persisted to pyproject.toml
        config = test_env.pyproject.load(force_reload=True)
        node_data = config['tool']['comfygit']['nodes']['git-dev-node']
        assert node_data.get('repository') == "https://github.com/user/git-dev-node.git", (
            "Repository URL should be persisted to pyproject.toml"
        )

    def test_add_dev_node_captures_branch(self, test_env):
        """Adding a dev node should capture current branch."""
        # ARRANGE - Create dev node on a feature branch
        dev_node_path = test_env.comfyui_path / "custom_nodes" / "branch-dev-node"
        dev_node_path.mkdir(parents=True)
        (dev_node_path / "nodes.py").write_text("# dev node code")

        subprocess.run(["git", "init"], cwd=dev_node_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/user/branch-dev-node.git"],
            cwd=dev_node_path, capture_output=True, check=True
        )
        subprocess.run(["git", "add", "."], cwd=dev_node_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=dev_node_path, capture_output=True, check=True,
            env={**subprocess.os.environ,
                 "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"}
        )
        # Create and checkout feature branch
        subprocess.run(
            ["git", "checkout", "-b", "feature/new-stuff"],
            cwd=dev_node_path, capture_output=True, check=True
        )

        # ACT
        node_info = test_env.node_manager.add_node("branch-dev-node", is_development=True)

        # ASSERT
        assert node_info.branch == "feature/new-stuff", (
            "Branch should be captured on add"
        )

        # Verify in pyproject
        config = test_env.pyproject.load(force_reload=True)
        node_data = config['tool']['comfygit']['nodes']['branch-dev-node']
        assert node_data.get('branch') == "feature/new-stuff"

    def test_add_dev_node_captures_pinned_commit(self, test_env):
        """Adding a dev node should capture current commit hash."""
        # ARRANGE
        dev_node_path = test_env.comfyui_path / "custom_nodes" / "commit-dev-node"
        dev_node_path.mkdir(parents=True)
        (dev_node_path / "nodes.py").write_text("# dev node code")

        subprocess.run(["git", "init"], cwd=dev_node_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/user/commit-dev-node.git"],
            cwd=dev_node_path, capture_output=True, check=True
        )
        subprocess.run(["git", "add", "."], cwd=dev_node_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=dev_node_path, capture_output=True, check=True,
            env={**subprocess.os.environ,
                 "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"}
        )

        # Get the actual commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=dev_node_path, capture_output=True, text=True
        )
        actual_commit = result.stdout.strip()

        # ACT
        node_info = test_env.node_manager.add_node("commit-dev-node", is_development=True)

        # ASSERT
        assert node_info.pinned_commit == actual_commit, (
            "Commit hash should be captured on add"
        )

        # Verify in pyproject
        config = test_env.pyproject.load(force_reload=True)
        node_data = config['tool']['comfygit']['nodes']['commit-dev-node']
        assert node_data.get('pinned_commit') == actual_commit

    def test_add_dev_node_without_git_skips_git_info(self, test_env):
        """Adding a dev node without git repo should not fail, just skip git info."""
        # ARRANGE - Dev node without git
        dev_node_path = test_env.comfyui_path / "custom_nodes" / "no-git-dev-node"
        dev_node_path.mkdir(parents=True)
        (dev_node_path / "nodes.py").write_text("# dev node code")

        # ACT
        node_info = test_env.node_manager.add_node("no-git-dev-node", is_development=True)

        # ASSERT - Should succeed without git info
        assert node_info.name == "no-git-dev-node"
        assert node_info.source == "development"
        assert node_info.repository is None, "No repository without git"
        assert node_info.branch is None, "No branch without git"
        assert node_info.pinned_commit is None, "No commit without git"
