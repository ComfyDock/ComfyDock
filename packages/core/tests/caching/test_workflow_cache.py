"""Unit tests for WorkflowCacheRepository.

Tests workflow analysis caching including:
- Cache hit/miss behavior
- Content-based invalidation
- mtime + size fast path
- Hash fallback path
- Session cache isolation
- Multi-environment isolation
- Cache persistence
"""
import json
import os
import time

import pytest
from comfygit_core.caching.workflow_cache import WorkflowCacheRepository
from comfygit_core.models.workflow import WorkflowDependencies, WorkflowNode


@pytest.fixture
def cache_db(tmp_path):
    """Create temporary cache database."""
    db_path = tmp_path / "test_workflows.db"
    return WorkflowCacheRepository(db_path)


@pytest.fixture
def sample_workflow_file(tmp_path):
    """Create a sample workflow JSON file."""
    workflow_path = tmp_path / "test_workflow.json"
    workflow_data = {
        "nodes": [
            {
                "id": 1,
                "type": "CheckpointLoaderSimple",
                "widgets_values": ["model.safetensors"]
            },
            {
                "id": 2,
                "type": "KSampler",
                "widgets_values": [123, "fixed", 20, 8.0]
            }
        ],
        "extra": {
            "ds": {"scale": 1.0, "offset": [0, 0]}  # UI state - should be normalized
        }
    }
    with open(workflow_path, 'w') as f:
        json.dump(workflow_data, f)
    return workflow_path


@pytest.fixture
def sample_dependencies():
    """Create sample WorkflowDependencies object."""
    return WorkflowDependencies(
        workflow_name="test_workflow",
        builtin_nodes=[
            WorkflowNode(
                id="1",
                type="CheckpointLoaderSimple"
            ),
            WorkflowNode(
                id="2",
                type="KSampler"
            )
        ],
        non_builtin_nodes=[],
        found_models=[]
    )


class TestCacheMissReturnsNone:
    """Test that cache queries for non-existent workflows return None."""

    def test_cache_miss_returns_none(self, cache_db, sample_workflow_file):
        """Query cache for non-existent workflow should return None."""
        result = cache_db.get(
            env_name="test-env",
            workflow_name="nonexistent",
            workflow_path=sample_workflow_file
        )

        assert result is None


class TestCacheHitAfterSet:
    """Test that cached data is returned after being set."""

    def test_cache_hit_after_set_and_session_cache_populated(self, cache_db, sample_workflow_file, sample_dependencies):
        """Set workflow analysis in cache - should return cached data and populate session cache."""
        # Set cache
        cache_db.set(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file,
            dependencies=sample_dependencies
        )

        # Query cache - should return cached analysis
        result = cache_db.get(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file
        )

        assert result is not None
        assert result.dependencies is not None
        assert len(result.dependencies.builtin_nodes) == 2
        assert result.dependencies.builtin_nodes[0].type == "CheckpointLoaderSimple"
        assert result.dependencies.builtin_nodes[1].type == "KSampler"

        # Session cache should have exactly one entry (with mtime in key)
        assert len(cache_db._session_cache) == 1, "Session cache should have one entry"
        # Verify the typed key includes env, workflow, and file metadata.
        session_keys = list(cache_db._session_cache.keys())
        assert session_keys[0].environment_name == "test-env"
        assert session_keys[0].workflow_name == "test_workflow"
        assert session_keys[0].workflow_mtime == sample_workflow_file.stat().st_mtime


class TestCacheInvalidationOnContentChange:
    """Test that cache is invalidated when workflow content changes."""

    def test_cache_invalidation_on_content_change(
        self,
        cache_db,
        sample_workflow_file,
        sample_dependencies
    ):
        """Modify workflow content - cache should miss."""
        # Cache workflow
        cache_db.set(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file,
            dependencies=sample_dependencies
        )

        # Verify cache hit
        result = cache_db.get(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file
        )
        assert result is not None

        # Modify workflow content (add a node)
        with open(sample_workflow_file) as f:
            workflow = json.load(f)

        workflow["nodes"].append({
            "id": 3,
            "type": "SaveImage",
            "widgets_values": []
        })

        with open(sample_workflow_file, 'w') as f:
            json.dump(workflow, f)

        # Clear session cache to force SQLite lookup
        cache_db._session_cache.clear()

        # Query again - should miss (content changed)
        result = cache_db.get(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file
        )

        assert result is None


class TestCacheHitOnMtimeMatch:
    """Test fast path using mtime + size matching."""

    def test_cache_hit_on_mtime_match(
        self,
        cache_db,
        sample_workflow_file,
        sample_dependencies
    ):
        """Query without file changes should use fast mtime path."""
        # Cache workflow
        cache_db.set(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file,
            dependencies=sample_dependencies
        )

        # Clear session cache to force SQLite lookup
        cache_db._session_cache.clear()

        # Query again - should hit via mtime fast path
        start_time = time.perf_counter()
        result = cache_db.get(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file
        )
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assert result is not None
        assert result.dependencies is not None
        # Fast path should be very quick (< 10ms for test overhead)
        assert elapsed_ms < 10


class TestCacheMissAfterMtimeChange:
    """Test that cache misses when mtime changes (even if content is same).

    Note: We intentionally removed the content hash fallback for simplicity.
    When mtime changes, the cache returns MISS and recomputes. This is a
    trade-off: we lose cache hits on `touch` (rare) but gain simpler code.
    """

    def test_cache_miss_after_touch(
        self,
        cache_db,
        sample_workflow_file,
        sample_dependencies
    ):
        """Touch file (change mtime, same content) - cache should MISS.

        This is expected behavior after removing the content hash fallback.
        The trade-off is: simpler code at the cost of extra recomputation
        in the rare case of `touch` without content change.
        """
        # Cache workflow
        cache_db.set(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file,
            dependencies=sample_dependencies
        )

        # Bump mtime deterministically
        new_mtime = sample_workflow_file.stat().st_mtime + 2
        os.utime(sample_workflow_file, (new_mtime, new_mtime))

        # Clear session cache to force SQLite lookup
        cache_db._session_cache.clear()

        # Query again - should MISS because mtime changed
        result = cache_db.get(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file
        )

        # With simplified caching (no content hash fallback), mtime change = MISS
        assert result is None


class TestSessionCacheIsolation:
    """Test that session caches are isolated between instances."""

    def test_session_cache_isolation(
        self,
        tmp_path,
        sample_workflow_file,
        sample_dependencies
    ):
        """Session cache should be instance-specific, SQLite shared."""
        db_path = tmp_path / "shared.db"

        # Create two cache instances
        cache_a = WorkflowCacheRepository(db_path)
        cache_b = WorkflowCacheRepository(db_path)

        # Set in cache A
        cache_a.set(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file,
            dependencies=sample_dependencies
        )

        # Query in cache B - should hit SQLite, not session cache
        result_b = cache_b.get(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file
        )

        # Should get data from SQLite
        assert result_b is not None

        # Verify B's session cache was populated with typed workflow state.
        assert len(cache_b._session_cache) == 1, "Cache B should have one session cache entry"
        session_keys_b = list(cache_b._session_cache.keys())
        assert session_keys_b[0].environment_name == "test-env"
        assert session_keys_b[0].workflow_name == "test_workflow"
        assert session_keys_b[0].workflow_mtime == sample_workflow_file.stat().st_mtime

        # Verify A and B have independent session caches
        assert cache_a._session_cache is not cache_b._session_cache


class TestMultiEnvironmentIsolation:
    """Test that different environments have isolated cache entries."""

    def test_multi_environment_isolation(
        self,
        cache_db,
        tmp_path,
        sample_dependencies
    ):
        """Same workflow name in different environments should have independent cache."""
        # Create two workflow files with different content
        workflow1 = tmp_path / "workflow1.json"
        workflow2 = tmp_path / "workflow2.json"

        workflow1.write_text(json.dumps({
            "nodes": [{"id": 1, "type": "NodeA"}]
        }))
        workflow2.write_text(json.dumps({
            "nodes": [{"id": 1, "type": "NodeB"}]
        }))

        deps1 = WorkflowDependencies(
            workflow_name="my_workflow",
            non_builtin_nodes=[WorkflowNode(id="1", type="NodeA")],
            builtin_nodes=[],
            found_models=[]
        )
        deps2 = WorkflowDependencies(
            workflow_name="my_workflow",
            non_builtin_nodes=[WorkflowNode(id="1", type="NodeB")],
            builtin_nodes=[],
            found_models=[]
        )

        # Cache same workflow name in different environments
        cache_db.set("env1", "my_workflow", workflow1, deps1)
        cache_db.set("env2", "my_workflow", workflow2, deps2)

        # Clear session cache
        cache_db._session_cache.clear()

        # Query each environment
        result1 = cache_db.get("env1", "my_workflow", workflow1)
        result2 = cache_db.get("env2", "my_workflow", workflow2)

        # Should get correct data for each environment
        assert result1 is not None
        assert result2 is not None
        assert result1.dependencies.non_builtin_nodes[0].type == "NodeA"
        assert result2.dependencies.non_builtin_nodes[0].type == "NodeB"


class TestCacheSurvivesRestart:
    """Test that cache persists across repository instances."""

    def test_cache_survives_restart(
        self,
        tmp_path,
        sample_workflow_file,
        sample_dependencies
    ):
        """Cache should persist when creating new repository instance."""
        db_path = tmp_path / "persistent.db"

        # Create cache instance A and set data
        cache_a = WorkflowCacheRepository(db_path)
        cache_a.set(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file,
            dependencies=sample_dependencies
        )

        # Destroy instance A
        del cache_a

        # Create new instance B with same db_path
        cache_b = WorkflowCacheRepository(db_path)

        # Query in instance B
        result = cache_b.get(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file
        )

        # Should get persisted data
        assert result is not None
        assert result.dependencies is not None
        assert len(result.dependencies.builtin_nodes) == 2


class TestInvalidation:
    """Test cache invalidation - selective and environment-wide."""

    def test_invalidate_specific_workflow_and_entire_environment(
        self,
        cache_db,
        tmp_path,
        sample_dependencies
    ):
        """Test both selective and environment-wide cache invalidation."""
        # Create workflows in two environments
        workflow1 = tmp_path / "workflow1.json"
        workflow2 = tmp_path / "workflow2.json"
        workflow3 = tmp_path / "workflow3.json"

        for wf in [workflow1, workflow2, workflow3]:
            wf.write_text(json.dumps({"nodes": []}))

        # Cache workflows in env1 and env2
        cache_db.set("env1", "workflow1", workflow1, sample_dependencies)
        cache_db.set("env1", "workflow2", workflow2, sample_dependencies)
        cache_db.set("env2", "workflow1", workflow1, sample_dependencies)

        # Test selective invalidation: invalidate workflow2 in env1
        cache_db.invalidate("env1", "workflow2")
        cache_db._session_cache.clear()

        result1 = cache_db.get("env1", "workflow1", workflow1)
        result2 = cache_db.get("env1", "workflow2", workflow2)

        assert result1 is not None  # workflow1 still cached
        assert result2 is None       # workflow2 invalidated

        # Test environment-wide invalidation: clear all of env1
        cache_db.invalidate("env1")
        cache_db._session_cache.clear()

        result_env1_wf1 = cache_db.get("env1", "workflow1", workflow1)
        result_env2_wf1 = cache_db.get("env2", "workflow1", workflow1)

        assert result_env1_wf1 is None          # env1 cleared
        assert result_env2_wf1 is not None      # env2 unaffected
        assert result_env2_wf1.dependencies is not None  # has data


class TestSessionCacheInvalidationOnFileChange:
    """Test that session cache automatically invalidates when workflow file changes.

    This is critical for long-running services (like ComfyUI server) where the
    Environment instance persists across requests. The session cache must detect
    file changes and not return stale data.
    """

    def test_session_cache_invalidates_when_workflow_content_changes(
        self,
        cache_db,
        tmp_path,
        sample_dependencies
    ):
        """Session cache should automatically invalidate when workflow file changes.

        BUG: Without mtime in session key, session cache returns stale data.
        Expected: Session cache key includes mtime, so file changes cause cache miss.
        """
        # Create initial workflow
        workflow_path = tmp_path / "test_workflow.json"
        workflow_v1 = {
            "nodes": [
                {"id": 1, "type": "CheckpointLoaderSimple", "widgets_values": ["model1.safetensors"]}
            ]
        }
        with open(workflow_path, 'w') as f:
            json.dump(workflow_v1, f)

        deps_v1 = WorkflowDependencies(
            workflow_name="test_workflow",
            builtin_nodes=[WorkflowNode(id="1", type="CheckpointLoaderSimple")],
            non_builtin_nodes=[],
            found_models=[]
        )

        # Cache v1
        cache_db.set("test-env", "test_workflow", workflow_path, deps_v1)

        # First get should return v1
        result1 = cache_db.get("test-env", "test_workflow", workflow_path)
        assert result1 is not None
        assert len(result1.dependencies.builtin_nodes) == 1
        assert result1.dependencies.builtin_nodes[0].type == "CheckpointLoaderSimple"

        # Modify workflow file (simulating user edit in ComfyUI)
        workflow_v2 = {
            "nodes": [
                {"id": 1, "type": "CheckpointLoaderSimple", "widgets_values": ["model1.safetensors"]},
                {"id": 2, "type": "KSampler", "widgets_values": [123, "fixed", 20, 8.0]}
            ]
        }
        with open(workflow_path, 'w') as f:
            json.dump(workflow_v2, f)
        # Bump mtime deterministically
        new_mtime = workflow_path.stat().st_mtime + 2
        os.utime(workflow_path, (new_mtime, new_mtime))

        # Second get WITHOUT clearing session cache (simulates long-running server)
        # This should detect file change and return None (cache miss)
        result2 = cache_db.get("test-env", "test_workflow", workflow_path)

        # CRITICAL: Should return None because file changed
        # If this returns cached v1, the session cache is not detecting file changes
        assert result2 is None, (
            "Session cache should invalidate when workflow file changes. "
            "Returning cached data means mtime is not included in session key."
        )

    def test_session_cache_persists_for_unchanged_files(
        self,
        cache_db,
        sample_workflow_file,
        sample_dependencies
    ):
        """Session cache should persist for multiple gets when file hasn't changed.

        This ensures we don't break the performance benefits of session caching.
        """
        # Cache workflow
        cache_db.set("test-env", "test_workflow", sample_workflow_file, sample_dependencies)

        # Multiple gets without file changes should all hit session cache
        for _i in range(3):
            result = cache_db.get("test-env", "test_workflow", sample_workflow_file)
            assert result is not None
            assert result.dependencies is not None
            assert len(result.dependencies.builtin_nodes) == 2

        # Verify session cache was used (should have exactly 1 entry)
        # If mtime is in key and file hasn't changed, all 3 gets use same session key
        session_keys = list(cache_db._session_cache.keys())
        assert len(session_keys) == 1, "Should have exactly 1 session cache entry for unchanged file"


class TestCacheHashVerification:
    """Test that cache verifies content hash to prevent stale data.

    Bug scenario: When another process (e.g., panel) computes a resolution
    and stores it in the cache with the current file's mtime+size, but the
    resolution was actually computed against DIFFERENT content, the cache
    should detect this via hash verification and return a MISS.

    This simulates the race condition where:
    1. File has content A with mtime T1
    2. Panel reads file (sees mtime T1)
    3. User modifies file to content B with mtime T2
    4. Panel computes resolution (against content A it read earlier)
    5. Panel calls cache.set() which captures current mtime T2
    6. CLI queries cache with mtime T2 - gets HIT but resolution is for content A!
    """

    def test_cache_miss_when_hash_differs_despite_mtime_match(
        self,
        tmp_path,
        sample_dependencies
    ):
        """Cache should MISS when mtime+size matches but content hash differs.

        This is the critical fix for the cache invalidation bug: even when
        mtime+size matches, we must verify the content hash before returning
        cached data.
        """
        db_path = tmp_path / "test.db"
        cache = WorkflowCacheRepository(db_path)

        # Create workflow with initial content
        workflow_path = tmp_path / "test_workflow.json"
        initial_content: dict[str, object] = {
            "nodes": [{"id": 1, "type": "NodeA", "widgets_values": ["value_a"]}]
        }
        with open(workflow_path, 'w') as f:
            json.dump(initial_content, f)

        # Simulate Process A (e.g., panel) caching a resolution
        cache.set("test-env", "test_workflow", workflow_path, sample_dependencies)

        # Get the mtime+size that was cached
        stat = workflow_path.stat()
        original_mtime = stat.st_mtime

        # Now modify the file content but preserve SAME mtime+size
        # This simulates the race where content changed between panel read and cache set
        modified_content: dict[str, object] = {
            "nodes": [{"id": 1, "type": "NodeB", "widgets_values": ["value_b"]}]
        }

        # Write different content with exact same size (pad if needed)
        modified_json = json.dumps(modified_content)
        original_json = json.dumps(initial_content)

        # If sizes differ, pad the shorter one to match
        if len(modified_json) < len(original_json):
            # Add whitespace to pad
            modified_content["_pad"] = " " * (len(original_json) - len(modified_json) - 10)
            modified_json = json.dumps(modified_content)
        elif len(modified_json) > len(original_json):
            # Just use a different approach - write same size content
            modified_content = {
                "nodes": [{"id": 1, "type": "NodeZ", "widgets_values": ["value_z"]}]
            }
            modified_json = json.dumps(modified_content)

        # Write the modified content
        with open(workflow_path, 'w') as f:
            f.write(modified_json)

        # Restore the original mtime (simulating the race condition)
        import os
        os.utime(workflow_path, (original_mtime, original_mtime))

        # Clear session cache to force SQLite lookup
        cache._session_cache.clear()

        # Query cache - mtime matches, but content hash differs
        # BUG: Current implementation returns HIT because mtime+size matches
        # FIX: Should return MISS because content hash differs
        result = cache.get("test-env", "test_workflow", workflow_path)

        # With the fix, this should be None (cache miss due to hash mismatch)
        assert result is None, (
            "Cache should MISS when content hash differs, even if mtime+size matches. "
            "The mtime+size fast path must verify content hash before returning cached data."
        )


class TestResolutionRoundTrip:
    """Test that all dataclass fields survive cache serialization/deserialization.

    This catches bugs where new fields are added to dataclasses but not included
    in the reconstruct_* functions.
    """

    def test_resolved_model_category_mismatch_fields_survive_cache(
        self,
        tmp_path,
        sample_workflow_file,
        sample_dependencies
    ):
        """Category mismatch fields on ResolvedModel must survive cache round-trip.

        Bug: reconstruct_resolved_model() explicitly maps each field, so new fields
        (has_category_mismatch, expected_categories, actual_category) get dropped.
        """
        from comfygit_core.models.workflow import (
            ResolutionResult,
            ResolvedModel,
            WorkflowNodeWidgetRef,
        )

        db_path = tmp_path / "test.db"
        cache = WorkflowCacheRepository(db_path)

        # Create pyproject.toml (needed for full cache hit with resolution)
        pyproject_path = tmp_path / "pyproject.toml"
        pyproject_path.write_text("[project]\nname = 'test'\n")

        # Create a ResolvedModel with category mismatch fields populated
        reference = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="LoraLoader",
            widget_index=0,
            widget_value="test_lora.safetensors"
        )

        resolved_model = ResolvedModel(
            workflow="test_workflow",
            reference=reference,
            resolved_model=None,
            model_source=None,
            is_optional=False,
            match_type="filename",
            match_confidence=0.7,
            target_path=None,
            needs_path_sync=True,
            # The new category mismatch fields
            has_category_mismatch=True,
            expected_categories=["loras"],
            actual_category="checkpoints"
        )

        resolution = ResolutionResult(
            workflow_name="test_workflow",
            models_resolved=[resolved_model]
        )

        # Cache the resolution with pyproject_path
        cache.set(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file,
            dependencies=sample_dependencies,
            resolution=resolution,
            pyproject_path=pyproject_path
        )

        # Clear session cache to force deserialization from SQLite
        cache._session_cache.clear()

        # Retrieve from cache (provide same pyproject_path for full hit)
        result = cache.get(
            "test-env", "test_workflow", sample_workflow_file,
            pyproject_path=pyproject_path
        )

        assert result is not None
        assert result.resolution is not None, \
            "Resolution should be returned on cache hit with pyproject_path"
        assert len(result.resolution.models_resolved) == 1

        cached_model = result.resolution.models_resolved[0]

        # These assertions fail with the bug (fields are dropped during deserialization)
        assert cached_model.has_category_mismatch, \
            "has_category_mismatch should survive cache round-trip"
        assert cached_model.expected_categories == ["loras"], \
            "expected_categories should survive cache round-trip"
        assert cached_model.actual_category == "checkpoints", \
            "actual_category should survive cache round-trip"

        # Verify other fields are still correct
        assert cached_model.needs_path_sync
        assert cached_model.match_type == "filename"
        assert cached_model.match_confidence == 0.7

    def test_old_cache_entries_without_new_fields_use_defaults(self, tmp_path):
        """Old cache entries (missing new fields) should use dataclass defaults gracefully.

        This ensures backward compatibility when loading cache created before
        new fields were added.
        """
        import json

        from comfygit_core.caching.workflow_cache import WorkflowCacheRepository

        db_path = tmp_path / "test.db"
        cache = WorkflowCacheRepository(db_path)

        # Simulate old cache entry without category mismatch fields
        old_model_dict = {
            'workflow': 'test',
            'reference': {
                'node_id': '1',
                'node_type': 'LoraLoader',
                'widget_index': 0,
                'widget_value': 'test.safetensors'
            },
            'resolved_model': None,
            'model_source': None,
            'is_optional': False,
            'match_type': 'filename',
            'match_confidence': 0.7,
            'target_path': None,
            'needs_path_sync': True
            # NOTE: No has_category_mismatch, expected_categories, actual_category
        }

        # Call the private deserialize method directly to test backward compat
        old_resolution_dict = {
            'workflow_name': 'test',
            'nodes_resolved': [],
            'nodes_unresolved': [],
            'nodes_ambiguous': [],
            'models_resolved': [old_model_dict],
            'models_unresolved': [],
            'models_ambiguous': [],
            'download_results': []
        }

        # Deserialize should not raise, should use defaults
        result = cache._deserialize_resolution(json.dumps(old_resolution_dict))

        assert len(result.models_resolved) == 1
        model = result.models_resolved[0]

        # New fields should use defaults
        assert not model.has_category_mismatch
        assert model.expected_categories == []
        assert model.actual_category is None

        # Existing fields should still work
        assert model.needs_path_sync
        assert model.match_type == "filename"

    def test_resolution_version_gated_and_uninstallable_fields_survive_cache(
        self,
        tmp_path,
        sample_workflow_file,
        sample_dependencies
    ):
        """New node-resolution buckets should survive cache round-trip."""
        from comfygit_core.models.workflow import (
            ResolutionResult,
            ResolvedNodePackage,
            WorkflowNode,
        )

        db_path = tmp_path / "test.db"
        cache = WorkflowCacheRepository(db_path)

        pyproject_path = tmp_path / "pyproject.toml"
        pyproject_path.write_text("[project]\nname = 'test'\n")

        version_gated_node = WorkflowNode(id="1", type="FutureBuiltin")
        uninstallable_pkg = ResolvedNodePackage(
            node_type="ManagerOnlyNode",
            package_id="manager-only-pkg",
            versions=[],
            match_type="type_only",
            source="manager",
        )

        resolution = ResolutionResult(
            workflow_name="test_workflow",
            nodes_version_gated=[version_gated_node],
            nodes_uninstallable=[uninstallable_pkg],
            node_guidance={
                "FutureBuiltin": "Node FutureBuiltin requires ComfyUI >= v0.3.10 (current v0.3.0).",
                "ManagerOnlyNode": (
                    "Node ManagerOnlyNode matched manager-only mapping "
                    "'manager-only-pkg' with no installable versions."
                ),
            },
        )

        cache.set(
            env_name="test-env",
            workflow_name="test_workflow",
            workflow_path=sample_workflow_file,
            dependencies=sample_dependencies,
            resolution=resolution,
            pyproject_path=pyproject_path,
        )

        cache._session_cache.clear()
        result = cache.get(
            "test-env",
            "test_workflow",
            sample_workflow_file,
            pyproject_path=pyproject_path,
        )

        assert result is not None
        assert result.resolution is not None
        assert len(result.resolution.nodes_version_gated) == 1
        assert result.resolution.nodes_version_gated[0].type == "FutureBuiltin"
        assert len(result.resolution.nodes_uninstallable) == 1
        assert result.resolution.nodes_uninstallable[0].package_id == "manager-only-pkg"
        assert result.resolution.node_guidance["FutureBuiltin"].startswith("Node FutureBuiltin")

    def test_dependencies_deserialize_tolerates_runtime_without_version_gated_field(self, tmp_path, monkeypatch):
        """Dependency deserialization should not crash if runtime class lacks new fields."""
        from dataclasses import dataclass, field

        from comfygit_core.caching import workflow_cache as cache_module

        @dataclass
        class LegacyWorkflowDependencies:
            workflow_name: str
            found_models: list = field(default_factory=list)
            builtin_nodes: list = field(default_factory=list)
            non_builtin_nodes: list = field(default_factory=list)

        db_path = tmp_path / "test.db"
        cache = WorkflowCacheRepository(db_path)

        # Simulate mixed-version cache payload containing a newer field.
        deps_dict = {
            "workflow_name": "test_workflow",
            "found_models": [],
            "builtin_nodes": [],
            "version_gated_nodes": [{"id": "1", "type": "FutureBuiltin"}],
            "non_builtin_nodes": [],
        }

        monkeypatch.setattr(cache_module, "WorkflowDependencies", LegacyWorkflowDependencies)
        deserialized = cache._deserialize_dependencies(json.dumps(deps_dict))

        assert isinstance(deserialized, LegacyWorkflowDependencies)
        assert deserialized.workflow_name == "test_workflow"
