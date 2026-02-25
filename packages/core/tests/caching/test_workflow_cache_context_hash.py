"""Tests for workflow cache context hash computation.

Tests that context hash correctly captures workflow-specific changes:
- Node package version changes invalidate cache
- Unrelated package changes don't invalidate cache
- Custom node mappings are captured
- Model metadata changes are captured
- Model index changes are captured
"""
from unittest.mock import Mock

import pytest
from comfygit_core.caching.workflow_cache import WorkflowCacheRepository
from comfygit_core.models.shared import NodeInfo
from comfygit_core.models.workflow import (
    WorkflowDependencies,
    WorkflowNode,
    WorkflowNodeWidgetRef,
)


@pytest.fixture
def mock_pyproject_manager():
    """Create mock pyproject manager with workflow and node data."""
    manager = Mock()

    # Mock workflows config
    manager.workflows.get_all_with_resolutions.return_value = {
        "workflow_a": {
            "nodes": ["pkg-1", "pkg-2"],
            "custom_node_map": {"NodeTypeA": "pkg-1"}
        },
        "workflow_b": {
            "nodes": ["pkg-3"],
            "custom_node_map": {}
        }
    }

    # Mock workflow models
    manager.workflows.get_workflow_models.return_value = []

    # Mock custom node map
    manager.workflows.get_custom_node_map.return_value = {"NodeTypeA": "pkg-1"}

    # Mock node packages
    manager.nodes.get_existing.return_value = {
        "pkg-1": NodeInfo(
            name="Package 1",
            repository="https://github.com/user/pkg-1",
            version="1.0.0",
            source="registry"
        ),
        "pkg-2": NodeInfo(
            name="Package 2",
            repository="https://github.com/user/pkg-2",
            version="2.0.0",
            source="registry"
        ),
        "pkg-3": NodeInfo(
            name="Package 3",
            repository="https://github.com/user/pkg-3",
            version="3.0.0",
            source="git"
        )
    }

    return manager


@pytest.fixture
def mock_model_repository():
    """Create mock model repository."""
    repo = Mock()
    repo.find_by_filename.return_value = []
    return repo


@pytest.fixture
def cache_with_mocks(tmp_path, mock_pyproject_manager, mock_model_repository):
    """Create cache with mocked dependencies."""
    db_path = tmp_path / "test_cache.db"
    cache = WorkflowCacheRepository(
        db_path=db_path,
        pyproject_manager=mock_pyproject_manager,
        model_repository=mock_model_repository
    )
    return cache


@pytest.fixture
def sample_dependencies():
    """Create sample dependencies for workflow_a."""
    return WorkflowDependencies(
        workflow_name="workflow_a",
        builtin_nodes=[],
        non_builtin_nodes=[
            WorkflowNode(id="1", type="NodeTypeA"),
            WorkflowNode(id="2", type="NodeTypeB")
        ],
        found_models=[]
    )


class TestContextHashIncludesWorkflowNodePackages:
    """Test that context hash includes packages from workflow.nodes list."""

    def test_context_hash_includes_packages_from_nodes_list(
        self,
        cache_with_mocks,
        sample_dependencies
    ):
        """Context hash should include version/repo/source from workflow.nodes list."""
        # Compute context hash
        hash1 = cache_with_mocks._compute_resolution_context_hash(
            sample_dependencies,
            "workflow_a"
        )

        # Verify hash was computed
        assert hash1 is not None
        assert len(hash1) == 16

        # Change version of pkg-1 (used by workflow_a)
        cache_with_mocks.pyproject_manager.nodes.get_existing.return_value["pkg-1"].version = "1.1.0"

        # Recompute hash
        hash2 = cache_with_mocks._compute_resolution_context_hash(
            sample_dependencies,
            "workflow_a"
        )

        # Hash should change because pkg-1 version changed
        assert hash2 != hash1


class TestContextHashIgnoresUnrelatedPackages:
    """Test that context hash ignores packages not in workflow.nodes."""

    def test_context_hash_unchanged_when_unrelated_package_changes(
        self,
        cache_with_mocks,
        sample_dependencies
    ):
        """Changing pkg-3 (used by workflow_b) shouldn't affect workflow_a's hash."""
        # Compute initial hash
        hash1 = cache_with_mocks._compute_resolution_context_hash(
            sample_dependencies,
            "workflow_a"
        )

        # Change version of pkg-3 (NOT used by workflow_a)
        cache_with_mocks.pyproject_manager.nodes.get_existing.return_value["pkg-3"].version = "3.1.0"

        # Recompute hash
        hash2 = cache_with_mocks._compute_resolution_context_hash(
            sample_dependencies,
            "workflow_a"
        )

        # Hash should be unchanged (pkg-3 not in workflow_a.nodes)
        assert hash2 == hash1


class TestContextHashIncludesAllPackageFields:
    """Test that context hash includes version, repository, and source."""

    def test_context_hash_changes_on_repository_change(
        self,
        cache_with_mocks,
        sample_dependencies
    ):
        """Changing repository URL should invalidate cache."""
        hash1 = cache_with_mocks._compute_resolution_context_hash(
            sample_dependencies,
            "workflow_a"
        )

        # Change repository of pkg-1
        cache_with_mocks.pyproject_manager.nodes.get_existing.return_value["pkg-1"].repository = "https://github.com/fork/pkg-1"

        hash2 = cache_with_mocks._compute_resolution_context_hash(
            sample_dependencies,
            "workflow_a"
        )

        assert hash2 != hash1

    def test_context_hash_changes_on_source_change(
        self,
        cache_with_mocks,
        sample_dependencies
    ):
        """Changing source type should invalidate cache."""
        hash1 = cache_with_mocks._compute_resolution_context_hash(
            sample_dependencies,
            "workflow_a"
        )

        # Change source of pkg-2 from registry to git
        cache_with_mocks.pyproject_manager.nodes.get_existing.return_value["pkg-2"].source = "git"

        hash2 = cache_with_mocks._compute_resolution_context_hash(
            sample_dependencies,
            "workflow_a"
        )

        assert hash2 != hash1


class TestContextHashWithNewWorkflow:
    """Test context hash behavior for workflows without nodes list yet."""

    def test_context_hash_with_empty_nodes_list(
        self,
        cache_with_mocks,
        sample_dependencies
    ):
        """New workflow with no nodes list should compute valid hash."""
        # Mock empty workflow config (new workflow not yet resolved)
        cache_with_mocks.pyproject_manager.workflows.get_all_with_resolutions.return_value = {
            "new_workflow": {"nodes": []}
        }

        # Compute hash for new workflow
        hash_result = cache_with_mocks._compute_resolution_context_hash(
            sample_dependencies,
            "new_workflow"
        )

        # Should return valid hash (empty declared_packages is fine)
        assert hash_result is not None
        assert len(hash_result) == 16


class TestContextHashWithMissingPackages:
    """Test context hash when workflow.nodes references packages not in global list."""

    def test_context_hash_ignores_missing_packages(
        self,
        cache_with_mocks,
        sample_dependencies
    ):
        """If workflow.nodes has pkg not in declared_packages, skip it gracefully."""
        # Add non-existent package to workflow config
        cache_with_mocks.pyproject_manager.workflows.get_all_with_resolutions.return_value["workflow_a"]["nodes"].append("missing-pkg")

        # Should compute hash without error (missing-pkg is skipped)
        hash_result = cache_with_mocks._compute_resolution_context_hash(
            sample_dependencies,
            "workflow_a"
        )

        assert hash_result is not None
        assert len(hash_result) == 16


class TestContextHashMultipleWorkflows:
    """Test that different workflows get different context hashes."""

    def test_different_workflows_have_different_hashes(
        self,
        cache_with_mocks
    ):
        """workflow_a and workflow_b should have different context hashes."""
        deps_a = WorkflowDependencies(
            workflow_name="workflow_a",
            builtin_nodes=[],
            non_builtin_nodes=[WorkflowNode(id="1", type="NodeA")],
            found_models=[]
        )

        deps_b = WorkflowDependencies(
            workflow_name="workflow_b",
            builtin_nodes=[],
            non_builtin_nodes=[WorkflowNode(id="1", type="NodeB")],
            found_models=[]
        )

        hash_a = cache_with_mocks._compute_resolution_context_hash(deps_a, "workflow_a")
        hash_b = cache_with_mocks._compute_resolution_context_hash(deps_b, "workflow_b")

        # Different workflows with different packages should have different hashes
        assert hash_a != hash_b


class TestContextHashCustomMappings:
    """Test that custom node mappings are captured in context hash."""

    def test_context_hash_includes_custom_mappings(
        self,
        cache_with_mocks,
        sample_dependencies
    ):
        """Adding/changing custom_node_map should change context hash."""
        hash1 = cache_with_mocks._compute_resolution_context_hash(
            sample_dependencies,
            "workflow_a"
        )

        # Add new custom mapping
        cache_with_mocks.pyproject_manager.workflows.get_custom_node_map.return_value = {
            "NodeTypeA": "pkg-1",
            "NodeTypeB": "pkg-2"  # New mapping
        }

        hash2 = cache_with_mocks._compute_resolution_context_hash(
            sample_dependencies,
            "workflow_a"
        )

        # Hash should change
        assert hash2 != hash1


class TestContextHashModelFilenameNormalization:
    """Test that model filename extraction handles Windows-style separators."""

    def test_context_hash_uses_basename_for_windows_style_model_refs(
        self,
        cache_with_mocks,
        sample_dependencies
    ):
        sample_dependencies.found_models = [
            WorkflowNodeWidgetRef(
                node_id="1",
                node_type="CheckpointLoaderSimple",
                widget_index=0,
                widget_value=r"Z-Image\qwen_3_4b.safetensors",
            )
        ]

        hash_result = cache_with_mocks._compute_resolution_context_hash(
            sample_dependencies,
            "workflow_a",
        )

        assert hash_result is not None
        cache_with_mocks.model_repository.find_by_filename.assert_called_once_with(
            "qwen_3_4b.safetensors"
        )
