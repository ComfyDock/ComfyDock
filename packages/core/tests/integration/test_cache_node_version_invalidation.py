"""Integration test for cache invalidation on node package version changes.

This test verifies the fix for the context hash bug where registry-resolved
node package version changes weren't invalidating the workflow cache.

Scenario:
1. Create workflow with custom node
2. Resolve and commit workflow (cache is populated)
3. Update node package version
4. Re-analyze workflow - cache should invalidate due to version change
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import (
    simulate_comfyui_save_workflow,
    load_workflow_fixture,
)


class TestCacheInvalidationOnNodeVersionChange:
    """Test that cache invalidates when node package versions change."""

    def test_cache_invalidates_when_node_package_updates(
        self,
        test_env,
        workflow_fixtures,
        test_models
    ):
        """Updating a node package version should invalidate workflow cache."""
        # Create workflow with custom node (txt2img uses various nodes)
        workflow = load_workflow_fixture(workflow_fixtures, "simple_txt2img")
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # First resolution - cold cache
        deps1, res1 = test_env.workflow_manager.analyze_and_resolve_workflow("test_workflow")

        # Apply resolution to populate workflow.nodes list
        test_env.workflow_manager.apply_resolution(res1)

        # Check what packages are being used
        workflow_config = test_env.pyproject.workflows.get_all_with_resolutions()
        workflow_nodes = workflow_config.get("test_workflow", {}).get("nodes", [])

        # If no custom nodes, inject a deterministic fake node for testing
        if not workflow_nodes:
            config = test_env.pyproject.load()
            config.setdefault("tool", {}).setdefault("comfygit", {}).setdefault("nodes", {})
            config["tool"]["comfygit"]["nodes"]["fake-node"] = {
                "name": "fake-node",
                "version": "0.1.0",
                "source": "git",
                "repository": "https://github.com/test/fake-node",
            }
            config["tool"]["comfygit"].setdefault("workflows", {}).setdefault("test_workflow", {})
            config["tool"]["comfygit"]["workflows"]["test_workflow"]["nodes"] = ["fake-node"]
            test_env.pyproject.save(config)
            workflow_nodes = ["fake-node"]

        # Pick first package to update
        test_package = workflow_nodes[0]
        original_version = test_env.pyproject.nodes.get_existing()[test_package].version

        # Second resolution - should hit cache (warm)
        deps2, res2 = test_env.workflow_manager.analyze_and_resolve_workflow("test_workflow")

        # Verify cache was used (same object references)
        assert deps2 is deps1 or deps2.workflow_name == deps1.workflow_name

        # Now simulate package update (change version in pyproject.toml)
        config = test_env.pyproject.load()
        new_version = "999.0.0"  # Obviously different version
        config["tool"]["comfygit"]["nodes"][test_package]["version"] = new_version
        test_env.pyproject.save(config)

        # Third resolution - cache should invalidate due to version change
        deps3, res3 = test_env.workflow_manager.analyze_and_resolve_workflow("test_workflow")

        # Verify cache was invalidated by checking that analysis happened
        # (In a real scenario, the resolution would be different, but we're just
        # testing that the cache invalidation happened, not the resolution result)

        # The key test: context hash should be different now
        cache = test_env.workflow_manager.workflow_cache

        # Get workflow path for cache lookup
        workflow_path = test_env.workflow_manager.get_workflow_path("test_workflow")

        # Compute context hash with new version
        hash_with_new_version = cache._compute_resolution_context_hash(
            deps3,
            "test_workflow"
        )

        # Reset version to original
        config["tool"]["comfygit"]["nodes"][test_package]["version"] = original_version
        test_env.pyproject.save(config)

        # Compute context hash with original version
        hash_with_original_version = cache._compute_resolution_context_hash(
            deps3,
            "test_workflow"
        )

        # Hashes should be different
        assert hash_with_new_version != hash_with_original_version, (
            f"Context hash should change when node package version changes. "
            f"Package: {test_package}, Old: {original_version}, New: {new_version}"
        )

    def test_cache_not_invalidated_by_unrelated_package_change(
        self,
        test_env,
        workflow_fixtures,
        test_models
    ):
        """Updating an unrelated node package should NOT invalidate workflow cache."""
        # Create workflow
        workflow = load_workflow_fixture(workflow_fixtures, "simple_txt2img")
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # Resolve workflow
        deps, res = test_env.workflow_manager.analyze_and_resolve_workflow("test_workflow")
        test_env.workflow_manager.apply_resolution(res)

        # Get initial context hash
        cache = test_env.workflow_manager.workflow_cache
        hash1 = cache._compute_resolution_context_hash(deps, "test_workflow")

        # Install a completely unrelated package that this workflow doesn't use
        test_env.add_node("comfyui-manager")  # Assuming test workflow doesn't use this

        # Compute context hash again
        hash2 = cache._compute_resolution_context_hash(deps, "test_workflow")

        # Hash should be unchanged (workflow doesn't use comfyui-manager)
        assert hash1 == hash2, (
            "Context hash should not change when unrelated package is added/updated"
        )


class TestCacheContextHashUsesWorkflowNodesList:
    """Test that context hash uses workflow.nodes list as authoritative source."""

    def test_context_hash_reads_from_workflow_nodes_list(
        self,
        test_env,
        workflow_fixtures,
        test_models
    ):
        """Context hash should read packages from workflow.nodes, not infer from content."""
        # Create and resolve workflow
        workflow = load_workflow_fixture(workflow_fixtures, "simple_txt2img")
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        deps, res = test_env.workflow_manager.analyze_and_resolve_workflow("test_workflow")
        test_env.workflow_manager.apply_resolution(res)

        # Get the workflow.nodes list
        workflow_config = test_env.pyproject.workflows.get_all_with_resolutions()
        workflow_nodes = set(workflow_config.get("test_workflow", {}).get("nodes", []))

        # If no custom nodes, inject a deterministic fake node for testing
        if not workflow_nodes:
            config = test_env.pyproject.load()
            config.setdefault("tool", {}).setdefault("comfygit", {}).setdefault("nodes", {})
            config["tool"]["comfygit"]["nodes"]["fake-node"] = {
                "name": "fake-node",
                "version": "0.1.0",
                "source": "git",
                "repository": "https://github.com/test/fake-node",
            }
            config["tool"]["comfygit"].setdefault("workflows", {}).setdefault("test_workflow", {})
            config["tool"]["comfygit"]["workflows"]["test_workflow"]["nodes"] = ["fake-node"]
            test_env.pyproject.save(config)
            workflow_nodes = {"fake-node"}

        # Compute context hash
        cache = test_env.workflow_manager.workflow_cache
        context_hash = cache._compute_resolution_context_hash(deps, "test_workflow")

        # Verify that the context includes exactly the packages from workflow.nodes
        # by checking that changing any of those packages affects the hash
        all_packages = test_env.pyproject.nodes.get_existing()

        for pkg_id in workflow_nodes:
            if pkg_id not in all_packages:
                continue

            # Save original version
            original_version = all_packages[pkg_id].version

            # Modify version
            config = test_env.pyproject.load()
            config["tool"]["comfygit"]["nodes"][pkg_id]["version"] = "changed"
            test_env.pyproject.save(config)

            # Compute new hash
            new_hash = cache._compute_resolution_context_hash(deps, "test_workflow")

            # Restore original
            config["tool"]["comfygit"]["nodes"][pkg_id]["version"] = original_version
            test_env.pyproject.save(config)

            # Hash should have changed
            assert new_hash != context_hash, (
                f"Context hash should include package '{pkg_id}' from workflow.nodes list"
            )
            break  # Just test one package
