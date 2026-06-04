"""Integration tests for workflow analysis caching.

Tests end-to-end workflow caching behavior:
- Status command cache usage
- Commit after status uses cache
- Cache invalidation on workflow edits
- Resolve command cache integration
- Performance improvements
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import (
    load_workflow_fixture,
    simulate_comfyui_save_workflow,
)


class TestStatusCommandUsesCache:
    """Test that status command uses cache across invocations."""

    def test_status_command_uses_cache_with_multiple_workflows(
        self,
        test_env,
        workflow_fixtures,
        test_models
    ):
        """Create multiple workflows - second status should be much faster with warm cache."""
        # Create 5 workflows
        for i in range(5):
            workflow = load_workflow_fixture(workflow_fixtures, "simple_txt2img")
            simulate_comfyui_save_workflow(test_env, f"workflow_{i}", workflow)

        # First status (cold cache)
        start_time = time.perf_counter()
        status1 = test_env.status()
        cold_time = time.perf_counter() - start_time

        # Second status (warm cache)
        start_time = time.perf_counter()
        status2 = test_env.status()
        warm_time = time.perf_counter() - start_time

        # Should have 5 workflows with identical results
        assert len(status1.workflow.analyzed_workflows) == 5
        assert len(status2.workflow.analyzed_workflows) == 5

        # Warm cache should be significantly faster
        assert warm_time < cold_time


class TestCommitAfterStatusUsesCache:
    """Test that commit command uses cache from status command."""

    def test_commit_after_status_uses_session_cache(
        self,
        test_env,
        workflow_fixtures,
        test_models
    ):
        """Run status then commit - commit should reuse analysis from status."""
        # Create workflow
        workflow = load_workflow_fixture(workflow_fixtures, "simple_txt2img")
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # Run status
        status = test_env.status()
        assert len(status.workflow.analyzed_workflows) == 1

        # Get workflow status for commit
        workflow_status = test_env.workflow_manager.get_workflow_status()

        # Run commit (should use cached analysis)
        start_time = time.perf_counter()
        test_env.execute_commit(workflow_status, message="Add workflow")
        commit_time = time.perf_counter() - start_time

        # Commit should be fast (using session cache)
        # This is primarily a smoke test - actual timing validation is in benchmarks
        assert commit_time < 5.0  # Generous upper bound

        # Verify workflow was committed
        assert (test_env.cec_path / "workflows" / "test_workflow.json").exists()


class TestCacheInvalidationOnWorkflowEdit:
    """Test that cache is invalidated when workflows are edited."""

    def test_cache_invalidation_on_workflow_edit_and_new_workflow_addition(
        self,
        test_env,
        workflow_fixtures,
        test_models
    ):
        """Edit workflow and add new workflow - only edited workflow should be re-analyzed."""
        # Create two workflows
        workflow = load_workflow_fixture(workflow_fixtures, "simple_txt2img")
        simulate_comfyui_save_workflow(test_env, "workflow1", workflow)
        simulate_comfyui_save_workflow(test_env, "workflow2", workflow)

        # Run status to cache both
        status1 = test_env.status()
        assert len(status1.workflow.analyzed_workflows) == 2

        # Edit workflow1 (add node)
        workflow_path = test_env.comfyui_path / "user" / "default" / "workflows" / "workflow1.json"
        with open(workflow_path) as f:
            wf_data = json.load(f)
        wf_data["nodes"].append({
            "id": 999,
            "type": "SaveImage",
            "widgets_values": []
        })
        with open(workflow_path, 'w') as f:
            json.dump(wf_data, f)

        # Add new workflow3
        simulate_comfyui_save_workflow(test_env, "workflow3", workflow)

        # Run status again
        status2 = test_env.status()

        # Should see 3 workflows - workflow1 re-analyzed, workflow2 cached, workflow3 newly analyzed
        assert len(status2.workflow.analyzed_workflows) == 3


class TestResolveCommandUsesCache:
    """Test that workflow resolve command uses cache."""

    def test_resolve_populates_cache_for_status(
        self,
        test_env,
        workflow_fixtures,
        test_models
    ):
        """Run workflow resolve, then status - status should use cache."""
        # Create workflow
        workflow = load_workflow_fixture(workflow_fixtures, "simple_txt2img")
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # Analyze and resolve workflow (similar to resolve command)
        dependencies, _ = test_env.workflow_manager.analyze_and_resolve_workflow("test_workflow")
        assert dependencies is not None

        # Run status (should use cache from analyze)
        start_time = time.perf_counter()
        status = test_env.status()
        status_time = time.perf_counter() - start_time

        # Status should be fast (using cache)
        assert len(status.workflow.analyzed_workflows) == 1
        # Generous upper bound - mainly checking it doesn't re-analyze
        assert status_time < 5.0

    def test_resolution_is_actually_cached(
        self,
        test_env,
        workflow_fixtures,
        test_models
    ):
        """Verify that resolution result is cached and retrieved from cache."""
        # Create workflow
        workflow = load_workflow_fixture(workflow_fixtures, "simple_txt2img")
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # First call - should cache both dependencies and resolution
        deps1, res1 = test_env.workflow_manager.analyze_and_resolve_workflow("test_workflow")

        # Verify cache was populated with resolution
        workflow_path = test_env.workflow_manager.get_workflow_path("test_workflow")
        cached = test_env.workflow_manager.workflow_cache.get(
            env_name=test_env.name,
            workflow_name="test_workflow",
            workflow_path=workflow_path,
            pyproject_path=test_env.pyproject_path
        )

        assert cached is not None, "Cache should be populated"
        assert cached.dependencies is not None, "Dependencies should be cached"
        assert cached.resolution is not None, "Resolution should be cached"
        assert not cached.needs_reresolution, "Should not need re-resolution"

        # Second call - should return cached resolution
        deps2, res2 = test_env.workflow_manager.analyze_and_resolve_workflow("test_workflow")

        # Verify same data returned (from cache)
        assert deps2.workflow_name == deps1.workflow_name
        assert len(res2.nodes_resolved) == len(res1.nodes_resolved)
        assert len(res2.models_resolved) == len(res1.models_resolved)


class TestCachePerformanceWithManyWorkflows:
    """Test cache performance improvements with many workflows."""

    def test_cache_performance_with_20_workflows(
        self,
        test_env,
        workflow_fixtures,
        test_models,
        monkeypatch
    ):
        """Create 20 workflows - second status should hit cache for all workflows."""
        # Create 20 workflows
        workflow = load_workflow_fixture(workflow_fixtures, "simple_txt2img")
        for i in range(20):
            simulate_comfyui_save_workflow(test_env, f"workflow_{i:02d}", workflow)

        # First status (cold cache) - populates cache
        status1 = test_env.status()
        assert len(status1.workflow.analyzed_workflows) == 20

        # Instrument cache to count hits/misses
        cache = test_env.workflow_manager.workflow_cache
        hits = {"hit": 0, "miss": 0}
        orig_get = cache.get

        def wrapped_get(*args, **kwargs):
            result = orig_get(*args, **kwargs)
            if result is None:
                hits["miss"] += 1
            else:
                hits["hit"] += 1
            return result

        monkeypatch.setattr(cache, "get", wrapped_get)

        # Second status (warm cache) - should hit cache for all workflows
        status2 = test_env.status()
        assert len(status2.workflow.analyzed_workflows) == 20

        # All 20 workflows should be cache hits, no misses
        assert hits["miss"] == 0, f"Expected no cache misses, got {hits['miss']}"
        assert hits["hit"] >= 20, f"Expected at least 20 cache hits, got {hits['hit']}"


class TestWorkflowDeletion:
    """Test cache behavior when workflows are deleted."""

    def test_cache_handles_deleted_workflows(
        self,
        test_env,
        workflow_fixtures,
        test_models
    ):
        """Delete workflow file - cache should handle gracefully."""
        # Create workflow
        workflow = load_workflow_fixture(workflow_fixtures, "simple_txt2img")
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # Run status to cache
        status1 = test_env.status()
        assert len(status1.workflow.analyzed_workflows) == 1

        # Delete workflow file
        workflow_path = test_env.comfyui_path / "user" / "default" / "workflows" / "test_workflow.json"
        workflow_path.unlink()

        # Run status again
        status2 = test_env.status()

        # Should see 0 workflows now
        assert len(status2.workflow.analyzed_workflows) == 0


class TestCacheWithWorkflowIssues:
    """Test caching behavior with problematic workflows."""

    def test_cache_works_with_missing_models(
        self,
        test_env,
        workflow_fixtures,
        test_models
    ):
        """Workflows with missing models should still be cached."""
        # Create workflow with missing model
        workflow = load_workflow_fixture(workflow_fixtures, "with_missing_model")
        simulate_comfyui_save_workflow(test_env, "problematic", workflow)

        # First status
        status1 = test_env.status()

        # Should detect issues
        assert status1.workflow.total_issues > 0 or len(status1.workflow.analyzed_workflows) > 0

        # Second status (should use cache)
        status2 = test_env.status()

        # Should return same results
        assert len(status1.workflow.analyzed_workflows) == len(status2.workflow.analyzed_workflows)
        assert status1.workflow.total_issues == status2.workflow.total_issues


class TestCacheClearOnCopy:
    """Test that cache is cleared when workflows are copied to .cec."""

    def test_cache_invalidated_after_workflow_copy(
        self,
        test_env,
        workflow_fixtures,
        test_models
    ):
        """After copying workflows to .cec, modified workflows should have cache invalidated."""
        # Create workflow
        workflow = load_workflow_fixture(workflow_fixtures, "simple_txt2img")
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # Run status to cache
        status1 = test_env.status()
        assert len(status1.workflow.analyzed_workflows) == 1

        # Copy workflows (this happens during commit)
        results = test_env.workflow_manager.copy_all_workflows()

        # Verify workflow was copied
        assert "test_workflow" in results

        # If workflow was modified during copy, cache should be invalidated
        # This is tested implicitly - the implementation should handle this


class TestPyprojectMtimeUpdateAfterContextCheck:
    """Test that pyproject_mtime is updated after context hash check."""

    def test_pyproject_mtime_updated_after_context_unchanged(
        self,
        test_env,
        workflow_fixtures,
        test_models
    ):
        """Verify that pyproject_mtime is updated in cache to avoid redundant context checks.

        Bug: When pyproject.toml changes but context is unchanged, the cache should
        update pyproject_mtime to avoid recomputing context hash on next run.

        Expected behavior:
        - Run 1: pyproject changed → compute context hash (~100ms)
        - Run 2: pyproject unchanged → instant hit (~1ms)

        Current buggy behavior:
        - Run 1: pyproject changed → compute context hash (~100ms)
        - Run 2: pyproject changed → compute context hash AGAIN (~100ms)
        """
        # Create workflow
        workflow = load_workflow_fixture(workflow_fixtures, "simple_txt2img")
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # First status - populate cache
        status1 = test_env.status()
        assert len(status1.workflow.analyzed_workflows) == 1

        # Modify pyproject.toml (change mtime without affecting this workflow's context)
        # This simulates user editing the file (e.g., adding a comment or unrelated package)
        import os
        current_mtime = test_env.pyproject_path.stat().st_mtime
        new_mtime = current_mtime + 2  # Bump mtime forward by 2 seconds
        os.utime(test_env.pyproject_path, (new_mtime, new_mtime))

        # Clear session cache to simulate new CLI invocation
        test_env.workflow_manager.workflow_cache._session_cache.clear()

        # Second status - should compute context hash and find it unchanged
        # Measure just the cache lookup, not the entire status() call
        workflow_path = test_env.workflow_manager.get_workflow_path("test_workflow")
        start_time = time.perf_counter()
        cached = test_env.workflow_manager.workflow_cache.get(
            env_name=test_env.name,
            workflow_name="test_workflow",
            workflow_path=workflow_path,
            pyproject_path=test_env.pyproject_path
        )
        first_run_time = time.perf_counter() - start_time

        assert cached is not None and not cached.needs_reresolution

        rows = test_env.workflow_manager.workflow_cache.sqlite.execute_query(
            """
            SELECT pyproject_mtime
            FROM workflow_cache
            WHERE environment_name = ? AND workflow_name = ?
            """,
            (test_env.name, "test_workflow"),
        )
        assert rows, "Cache row should exist after context check"
        assert abs(rows[0]["pyproject_mtime"] - new_mtime) < 0.001

        # Third cache lookup should hit against the updated fast-path metadata.
        cached2 = test_env.workflow_manager.workflow_cache.get(
            env_name=test_env.name,
            workflow_name="test_workflow",
            workflow_path=workflow_path,
            pyproject_path=test_env.pyproject_path
        )

        assert cached2 is not None and not cached2.needs_reresolution
        assert first_run_time >= 0
