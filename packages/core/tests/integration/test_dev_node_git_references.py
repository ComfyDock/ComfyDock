"""Integration tests for dev node git references feature.

Tests the new behavior where dev nodes use git references instead of bundling source code.
This enables team collaboration on custom nodes while keeping ComfyGit as a lightweight
environment orchestrator rather than a node version manager.

Key behaviors tested:
1. NodeInfo now has branch and pinned_commit fields
2. Export captures git info instead of bundling source code
3. Import clones from git reference instead of extracting bundled code
4. Rollback/checkout operations skip dev nodes entirely
5. Status reports dev nodes separately (informational, not errors)
"""
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from comfygit_core.managers.pyproject_manager import PyprojectManager
from comfygit_core.models.shared import NodeInfo


class TestPhase1NodeInfoGitFields:
    """Phase 1: Core Model Changes - branch and pinned_commit fields on NodeInfo."""

    def test_node_info_has_branch_field(self):
        """NodeInfo should have an optional branch field."""
        # ARRANGE/ACT
        node_info = NodeInfo(
            name="my-team-node",
            source="development",
            version="dev",
            branch="dev"
        )

        # ASSERT
        assert hasattr(node_info, 'branch'), "NodeInfo should have branch field"
        assert node_info.branch == "dev"

    def test_node_info_has_pinned_commit_field(self):
        """NodeInfo should have an optional pinned_commit field."""
        # ARRANGE/ACT
        node_info = NodeInfo(
            name="my-team-node",
            source="development",
            version="dev",
            pinned_commit="abc123def"
        )

        # ASSERT
        assert hasattr(node_info, 'pinned_commit'), "NodeInfo should have pinned_commit field"
        assert node_info.pinned_commit == "abc123def"

    def test_node_info_from_pyproject_reads_branch(self, tmp_path):
        """from_pyproject_config should read branch and default criticality."""
        # ARRANGE - Create pyproject with branch field
        pyproject_path = tmp_path / "pyproject.toml"
        pyproject_path.write_text("""
[project]
name = "test"

[tool.comfygit.nodes.my-team-node]
name = "my-team-node"
source = "development"
repository = "https://github.com/user/my-team-node.git"
branch = "dev"
pinned_commit = "abc123def"
        """)

        manager = PyprojectManager(pyproject_path)
        config = manager.load()
        nodes_config = config.get('tool', {}).get('comfygit', {}).get('nodes', {})

        # ACT
        node_info = NodeInfo.from_pyproject_config(nodes_config, "my-team-node")

        # ASSERT
        assert node_info is not None
        assert node_info.criticality == "required", "Missing criticality should default to required"
        assert node_info.branch == "dev", "Should read branch from pyproject"
        assert node_info.pinned_commit == "abc123def", "Should read pinned_commit from pyproject"

    def test_node_handler_writes_branch_and_pinned_commit(self, tmp_path):
        """NodeHandler.add should write branch and pinned_commit to pyproject.toml."""
        # ARRANGE
        pyproject_path = tmp_path / "pyproject.toml"
        pyproject_path.write_text("""
[project]
name = "test"
        """)

        manager = PyprojectManager(pyproject_path)
        node_info = NodeInfo(
            name="my-team-node",
            source="development",
            version="dev",
            repository="https://github.com/user/my-team-node.git",
            branch="dev",
            pinned_commit="abc123def"
        )

        # ACT
        manager.nodes.add(node_info, "my-team-node")

        # ASSERT - Reload and verify
        config = manager.load(force_reload=True)
        node_data = config['tool']['comfygit']['nodes']['my-team-node']
        assert node_data.get('branch') == "dev", "Should write branch to pyproject"
        assert node_data.get('pinned_commit') == "abc123def", "Should write pinned_commit to pyproject"


class TestPhase2ExportChanges:
    """Phase 2: Export should capture git info instead of bundling source code."""

    def test_export_does_not_bundle_dev_node_source(self, test_env, tmp_path):
        """Export should NOT bundle dev node source code in dev_nodes/ directory."""
        # ARRANGE - Add a dev node to custom_nodes
        dev_node_path = test_env.comfyui_path / "custom_nodes" / "my-dev-node"
        dev_node_path.mkdir(parents=True)
        (dev_node_path / "nodes.py").write_text("# dev node code")
        (dev_node_path / "requirements.txt").write_text("torch>=2.0.0")

        # Track as dev node
        test_env.pyproject.nodes.add_development("my-dev-node")

        # Commit to make environment exportable
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add dev node")

        # ACT - Export
        export_path = tmp_path / "export.tar.gz"
        test_env.export_environment(export_path)

        # ASSERT - dev_nodes/ should NOT be in tarball
        with tarfile.open(export_path, "r:gz") as tar:
            members = [m.name for m in tar.getmembers()]
            dev_node_members = [m for m in members if m.startswith("dev_nodes/")]
            assert len(dev_node_members) == 0, (
                f"Export should NOT bundle dev node source code. Found: {dev_node_members}"
            )

    def test_export_captures_git_info_for_dev_node(self, test_env, tmp_path):
        """Export should capture repository/branch/pinned_commit for dev nodes with git."""
        # ARRANGE - Create a dev node with git repo
        dev_node_path = test_env.comfyui_path / "custom_nodes" / "my-git-node"
        dev_node_path.mkdir(parents=True)
        (dev_node_path / "nodes.py").write_text("# dev node code")

        # Initialize git repo with remote
        subprocess.run(["git", "init"], cwd=dev_node_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/user/my-git-node.git"],
            cwd=dev_node_path, capture_output=True
        )
        subprocess.run(["git", "add", "."], cwd=dev_node_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=dev_node_path, capture_output=True,
            env={**subprocess.os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"}
        )

        # Track as dev node (should auto-detect git info during export)
        test_env.pyproject.nodes.add_development("my-git-node")

        # Commit environment
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add dev node")

        # ACT - Export should capture git info
        export_path = tmp_path / "export.tar.gz"
        test_env.export_environment(export_path)

        # ASSERT - pyproject.toml in export should have git info
        with tarfile.open(export_path, "r:gz") as tar:
            pyproject_member = tar.extractfile("pyproject.toml")
            assert pyproject_member is not None
            content = pyproject_member.read().decode()

            # Verify git fields are captured
            assert "repository" in content, "Export should capture repository URL"
            assert "github.com/user/my-git-node" in content, "Repository URL should be captured"
            # branch and pinned_commit should be captured
            assert "branch" in content or "pinned_commit" in content, (
                "Export should capture branch or pinned_commit for git dev nodes"
            )


class TestPhase3ImportChanges:
    """Phase 3: Import should clone dev nodes from git reference."""

    def test_sync_clones_missing_dev_node_with_repository(self, test_env):
        """sync_nodes_to_filesystem should clone dev node from repository if missing."""
        from unittest.mock import patch

        # ARRANGE - Track a dev node with repository but NO local directory
        node_info = NodeInfo(
            name="team-dev-node",
            source="development",
            version="dev",
            repository="https://github.com/user/team-dev-node.git",
            branch="dev"
        )
        test_env.pyproject.nodes.add(node_info, "team-dev-node")

        # Verify node does NOT exist on filesystem
        node_path = test_env.comfyui_path / "custom_nodes" / "team-dev-node"
        assert not node_path.exists(), "Node should NOT exist before sync"

        # ACT - Mock git_clone to verify it gets called
        with patch('comfygit_core.managers.node_manager.git_clone') as mock_clone:
            # Make mock create the directory (simulating successful clone)
            def clone_side_effect(url, target_path, depth=1, ref=None, timeout=30, token=None):
                target_path.mkdir(parents=True, exist_ok=True)
                (target_path / "nodes.py").write_text("# cloned code")

            mock_clone.side_effect = clone_side_effect

            test_env.node_manager.sync_nodes_to_filesystem()

            # ASSERT - git_clone should have been called for the dev node
            mock_clone.assert_called_once()
            call_args = mock_clone.call_args
            # Check kwargs since we're calling with keyword args
            assert call_args.kwargs.get('url') == "https://github.com/user/team-dev-node.git"
            assert "team-dev-node" in str(call_args.kwargs.get('target_path'))
            # Should use branch, not depth=1 (full clone for dev nodes)
            assert call_args.kwargs.get('ref') == "dev"
            assert call_args.kwargs.get('depth') == 0  # Full clone, not shallow

    def test_sync_clones_dev_node_with_pinned_commit_before_branch(self, test_env):
        """sync_nodes_to_filesystem should prefer pinned_commit over branch for exact reconstruction."""
        from unittest.mock import patch

        node_info = NodeInfo(
            name="exact-dev-node",
            source="development",
            version="dev",
            repository="https://github.com/user/exact-dev-node.git",
            branch="dev",
            pinned_commit="abc123def456",
        )
        test_env.pyproject.nodes.add(node_info, "exact-dev-node")

        with patch('comfygit_core.managers.node_manager.git_clone') as mock_clone:
            def clone_side_effect(url, target_path, depth=1, ref=None, timeout=30, token=None):
                target_path.mkdir(parents=True, exist_ok=True)

            mock_clone.side_effect = clone_side_effect
            test_env.node_manager.sync_nodes_to_filesystem()

            mock_clone.assert_called_once()
            call_args = mock_clone.call_args
            assert call_args.kwargs.get('ref') == "abc123def456"
            assert call_args.kwargs.get('depth') == 0

    def test_sync_clones_dev_node_with_pinned_commit_when_no_branch(self, test_env):
        """sync_nodes_to_filesystem should use pinned_commit if branch not set."""
        from unittest.mock import patch

        # ARRANGE - Dev node with pinned_commit but no branch
        node_info = NodeInfo(
            name="pinned-dev-node",
            source="development",
            version="dev",
            repository="https://github.com/user/pinned-dev-node.git",
            pinned_commit="abc123def456"
        )
        test_env.pyproject.nodes.add(node_info, "pinned-dev-node")

        # ACT
        with patch('comfygit_core.managers.node_manager.git_clone') as mock_clone:
            def clone_side_effect(url, target_path, depth=1, ref=None, timeout=30, token=None):
                target_path.mkdir(parents=True, exist_ok=True)

            mock_clone.side_effect = clone_side_effect
            test_env.node_manager.sync_nodes_to_filesystem()

            # ASSERT - Should use pinned_commit as ref
            mock_clone.assert_called_once()
            call_args = mock_clone.call_args
            assert call_args.kwargs.get('ref') == "abc123def456"

    def test_sync_skips_existing_dev_node(self, test_env):
        """sync_nodes_to_filesystem should NOT clone dev node if already exists."""
        from unittest.mock import patch

        # ARRANGE - Dev node with repository AND local directory exists
        node_info = NodeInfo(
            name="existing-dev-node",
            source="development",
            version="dev",
            repository="https://github.com/user/existing-dev-node.git",
            branch="main"
        )
        test_env.pyproject.nodes.add(node_info, "existing-dev-node")

        # Create the directory (simulating existing local copy)
        node_path = test_env.comfyui_path / "custom_nodes" / "existing-dev-node"
        node_path.mkdir(parents=True)
        (node_path / "nodes.py").write_text("# local code")

        # ACT
        with patch('comfygit_core.managers.node_manager.git_clone') as mock_clone:
            test_env.node_manager.sync_nodes_to_filesystem()

            # ASSERT - git_clone should NOT have been called
            mock_clone.assert_not_called()

        # Local code should be preserved
        assert (node_path / "nodes.py").read_text() == "# local code"

    def test_sync_warns_for_dev_node_without_repository(self, test_env):
        """sync_nodes_to_filesystem should warn via callback when dev node has no repository."""
        from unittest.mock import MagicMock

        # ARRANGE - Dev node WITHOUT repository
        node_info = NodeInfo(
            name="local-only-node",
            source="development",
            version="dev"
            # No repository field
        )
        test_env.pyproject.nodes.add(node_info, "local-only-node")

        # Create mock callbacks
        callbacks = MagicMock()

        # ACT
        test_env.node_manager.sync_nodes_to_filesystem(callbacks=callbacks)

        # ASSERT - Callback should have been called for missing repo
        callbacks.on_dev_node_missing_repository.assert_called_once_with("local-only-node")

    def test_sync_calls_dev_node_cloned_callback(self, test_env):
        """sync_nodes_to_filesystem should call on_dev_node_cloned callback on success."""
        from unittest.mock import MagicMock, patch

        # ARRANGE
        node_info = NodeInfo(
            name="callback-test-node",
            source="development",
            version="dev",
            repository="https://github.com/user/callback-test-node.git",
            branch="main"
        )
        test_env.pyproject.nodes.add(node_info, "callback-test-node")

        callbacks = MagicMock()

        # ACT
        with patch('comfygit_core.managers.node_manager.git_clone') as mock_clone:
            def clone_side_effect(url, target_path, depth=1, ref=None, timeout=30, token=None):
                target_path.mkdir(parents=True, exist_ok=True)

            mock_clone.side_effect = clone_side_effect
            test_env.node_manager.sync_nodes_to_filesystem(callbacks=callbacks)

            # ASSERT
            callbacks.on_dev_node_cloned.assert_called_once_with(
                "callback-test-node",
                "https://github.com/user/callback-test-node.git"
            )


class TestPhase4RollbackChanges:
    """Phase 4: Rollback/checkout operations should skip dev nodes entirely."""

    def test_rollback_does_not_touch_dev_node(self, test_env):
        """Rollback should never modify dev node filesystem state."""
        # ARRANGE - Add a dev node
        dev_node_path = test_env.comfyui_path / "custom_nodes" / "my-dev-node"
        dev_node_path.mkdir(parents=True)
        (dev_node_path / "nodes.py").write_text("# original code")

        # Track as dev node and commit
        test_env.pyproject.nodes.add_development("my-dev-node")
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add dev node")

        # Make local changes to dev node (uncommitted)
        (dev_node_path / "nodes.py").write_text("# modified code")
        (dev_node_path / "new_file.py").write_text("# new file")

        # Get the commit to rollback to
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=test_env.cec_path, capture_output=True, text=True
        )
        commit_hash = result.stdout.strip()

        # ACT - Create another commit and rollback
        # (First we need to create a commit to rollback from)
        config = test_env.pyproject.load()
        config['tool']['comfygit']['test_key'] = "test_value"
        test_env.pyproject.save(config)
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Test commit")

        # Now rollback to previous commit
        test_env.checkout(commit_hash)

        # ASSERT - Dev node should be untouched
        assert (dev_node_path / "nodes.py").read_text() == "# modified code", (
            "Dev node file content should be preserved during rollback"
        )
        assert (dev_node_path / "new_file.py").exists(), (
            "Dev node new file should be preserved during rollback"
        )

    def test_reconcile_nodes_skips_dev_nodes(self, test_env):
        """reconcile_nodes_for_rollback should skip dev nodes entirely."""
        # ARRANGE
        dev_node_path = test_env.comfyui_path / "custom_nodes" / "my-dev-node"
        dev_node_path.mkdir(parents=True)
        (dev_node_path / "nodes.py").write_text("# dev code")

        # Create node info objects for reconciliation
        old_nodes = {
            "my-dev-node": NodeInfo(
                name="my-dev-node",
                source="development",
                version="dev"
            )
        }
        new_nodes = {}  # Dev node was removed in target commit

        # ACT
        test_env.node_manager.reconcile_nodes_for_rollback(old_nodes, new_nodes)

        # ASSERT - Dev node should NOT be disabled or deleted
        assert dev_node_path.exists(), "Dev node directory should still exist"
        assert not (test_env.comfyui_path / "custom_nodes" / "my-dev-node.disabled").exists(), (
            "Dev node should NOT be renamed to .disabled"
        )

    def test_remove_node_dev_untracks_without_filesystem_changes(self, test_env):
        """Removing a dev node should only untrack it, not delete or disable."""
        # ARRANGE
        dev_node_path = test_env.comfyui_path / "custom_nodes" / "my-dev-node"
        dev_node_path.mkdir(parents=True)
        (dev_node_path / "nodes.py").write_text("# dev code")

        # Track as dev node
        test_env.pyproject.nodes.add_development("my-dev-node")

        # Verify it's tracked
        nodes = test_env.pyproject.nodes.get_existing()
        assert "my-dev-node" in nodes

        # ACT - Remove the dev node (should only untrack)
        test_env.node_manager.remove_node("my-dev-node", untrack_only=True)

        # ASSERT
        # Node should be untracked from pyproject
        nodes = test_env.pyproject.nodes.get_existing()
        assert "my-dev-node" not in nodes, "Dev node should be untracked"

        # But filesystem should be untouched
        assert dev_node_path.exists(), "Dev node directory should still exist"
        assert (dev_node_path / "nodes.py").read_text() == "# dev code", (
            "Dev node files should be preserved"
        )
        assert not (test_env.comfyui_path / "custom_nodes" / "my-dev-node.disabled").exists(), (
            "Dev node should NOT be renamed to .disabled"
        )


class TestPhase5StatusChanges:
    """Phase 5: Status should report dev nodes separately (informational, not errors)."""

    def test_untracked_git_node_not_in_extra_nodes(self, test_env):
        """Untracked git repos in custom_nodes should be reported as dev_nodes_untracked."""
        # ARRANGE - Create an untracked git repo in custom_nodes
        node_path = test_env.comfyui_path / "custom_nodes" / "untracked-node"
        node_path.mkdir(parents=True)
        (node_path / "nodes.py").write_text("# code")
        subprocess.run(["git", "init"], cwd=node_path, capture_output=True)

        # ACT
        status = test_env.status()

        # ASSERT - Should be in dev_nodes_untracked, not extra_nodes
        assert hasattr(status.comparison, 'dev_nodes_untracked'), (
            "EnvironmentComparison should have dev_nodes_untracked field"
        )
        assert "untracked-node" in status.comparison.dev_nodes_untracked, (
            "Untracked git repo should be in dev_nodes_untracked"
        )
        assert "untracked-node" not in status.comparison.extra_nodes, (
            "Untracked git repo should NOT be in extra_nodes"
        )

    def test_missing_dev_node_not_in_missing_nodes(self, test_env):
        """Missing dev nodes should be in dev_nodes_missing, not missing_nodes."""
        # ARRANGE - Track a dev node that doesn't exist on filesystem
        node_info = NodeInfo(
            name="missing-dev-node",
            source="development",
            version="dev",
            repository="https://github.com/user/missing-dev-node.git"
        )
        test_env.pyproject.nodes.add(node_info, "missing-dev-node")

        # Verify node is NOT on filesystem
        node_path = test_env.comfyui_path / "custom_nodes" / "missing-dev-node"
        assert not node_path.exists()

        # ACT
        status = test_env.status()

        # ASSERT - Should be in dev_nodes_missing, not missing_nodes
        assert hasattr(status.comparison, 'dev_nodes_missing'), (
            "EnvironmentComparison should have dev_nodes_missing field"
        )
        assert "missing-dev-node" in status.comparison.dev_nodes_missing, (
            "Missing dev node should be in dev_nodes_missing"
        )
        assert "missing-dev-node" not in status.comparison.missing_nodes, (
            "Missing dev node should NOT be in missing_nodes"
        )

    def test_status_is_synced_ignores_dev_node_issues(self, test_env):
        """Environment should be considered 'synced' even with dev node discrepancies."""
        # ARRANGE - Create scenarios that would normally cause "out of sync":
        # 1. Untracked git repo
        untracked_path = test_env.comfyui_path / "custom_nodes" / "untracked-node"
        untracked_path.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=untracked_path, capture_output=True)

        # 2. Missing dev node
        node_info = NodeInfo(
            name="missing-dev-node",
            source="development",
            version="dev",
            repository="https://github.com/user/missing.git"
        )
        test_env.pyproject.nodes.add(node_info, "missing-dev-node")

        # ACT
        status = test_env.status()

        # ASSERT - Should still be considered "synced" (dev nodes are informational only)
        assert status.comparison.is_synced, (
            "Environment should be 'synced' despite dev node discrepancies"
        )
