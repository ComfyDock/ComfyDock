"""Integration tests for repair command node removal functionality.

Tests the scenario where repair command should remove extra nodes from filesystem
to match the state in pyproject.toml (git collaboration scenario).
"""



class TestRepairNodeRemoval:
    """Test repair command removes extra nodes as promised in preview."""

    def test_repair_removes_extra_registry_nodes(self, test_env):
        """Repair should remove registry nodes that exist on filesystem but not in pyproject.toml.

        Scenario:
        1. Environment has node tracked in pyproject.toml
        2. Git reset removes node from pyproject.toml (simulated by direct removal)
        3. Node directory still exists on filesystem
        4. Repair should remove the node directory
        """
        # ARRANGE: Add a node through normal flow (will be in pyproject + filesystem)
        node_name = "comfyui-manager"

        # Manually create a registry node directory (simulate it was installed before)
        node_path = test_env.custom_nodes_path / node_name
        node_path.mkdir(parents=True, exist_ok=True)

        # Create a .git directory to mark it as a git clone (registry node)
        git_dir = node_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]\n")

        # Verify node exists on filesystem
        assert node_path.exists(), "Node directory should exist on filesystem"

        # Verify node is NOT in pyproject.toml (simulating git reset scenario)
        config = test_env.pyproject.load()
        nodes = config.get("tool", {}).get("comfygit", {}).get("nodes", {})
        assert node_name not in nodes, "Node should not be in pyproject.toml"

        # ACT: Run sync (repair calls this)
        sync_result = test_env.sync()

        # ASSERT: Node directory should be removed
        assert not node_path.exists(), (
            f"Expected {node_name} to be removed from filesystem after repair, "
            f"but directory still exists at {node_path}"
        )
        assert sync_result.success, "Sync should succeed"

    def test_repair_warns_only_in_conservative_mode(self, test_env):
        """When remove_extra_nodes=False, should only warn about extra nodes."""
        # ARRANGE: Create extra node
        node_name = "extra-node"
        node_path = test_env.custom_nodes_path / node_name
        node_path.mkdir(parents=True, exist_ok=True)
        git_dir = node_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]\n")

        # ACT: Run sync with conservative mode
        sync_result = test_env.sync(remove_extra_nodes=False)

        # ASSERT: Node should still exist (only warned)
        assert node_path.exists(), "Node should not be removed in conservative mode"
        assert sync_result.success

    def test_git_collaboration_scenario(self, test_env):
        """Full scenario: Dev B force-resets .cec/ and runs repair.

        This is the exact bug scenario from the bug document:
        1. Dev A adds nodes, commits, pushes
        2. Dev B force-resets .cec/ to remote (removes nodes from pyproject)
        3. Dev B's filesystem still has the nodes
        4. Dev B runs repair expecting aggressive reconciliation
        """
        # ARRANGE: Simulate Dev B's state after git reset
        # - Filesystem has nodes that Dev A added
        # - pyproject.toml doesn't have them (after git reset)

        extra_nodes = [
            "ComfyUI-AKatz-Nodes",
            "rgthree-comfy",
            "ComfyUI-VideoHelperSuite",
            "ComfyUI-Basic-Math",
            "ComfyUI-Depthflow-Nodes",
            "ComfyUI-DepthAnythingV2"
        ]

        # Create all extra nodes on filesystem
        for node_name in extra_nodes:
            node_path = test_env.custom_nodes_path / node_name
            node_path.mkdir(parents=True, exist_ok=True)
            git_dir = node_path / ".git"
            git_dir.mkdir()
            (git_dir / "config").write_text("[core]\n")

        # Verify all nodes exist
        for node_name in extra_nodes:
            assert (test_env.custom_nodes_path / node_name).exists()

        # Verify none are in pyproject.toml (post git-reset state)
        config = test_env.pyproject.load()
        nodes = config.get("tool", {}).get("comfygit", {}).get("nodes", {})
        for node_name in extra_nodes:
            assert node_name not in nodes

        # ACT: Run repair (which calls sync)
        sync_result = test_env.sync()

        # ASSERT: All extra nodes should be removed
        for node_name in extra_nodes:
            node_path = test_env.custom_nodes_path / node_name
            assert not node_path.exists(), (
                f"Expected {node_name} to be removed after repair, "
                f"but it still exists. This is the reported bug!"
            )

        assert sync_result.success

        # Status should show clean state
        status = test_env.status()
        assert status.is_synced, "Environment should be synced after repair"
        assert len(status.comparison.extra_nodes) == 0, "Should have no extra nodes"
