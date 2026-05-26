"""Tests for workflow model deduplication during resolution.

When the same model appears in multiple nodes, the user should only be prompted once,
and all node references should be grouped together in a single ManifestWorkflowModel entry.
"""
from pathlib import Path
from unittest.mock import Mock

import pytest
from comfygit_core.managers.workflow_manager import WorkflowManager
from comfygit_core.models.manifest import ManifestWorkflowModel
from comfygit_core.models.shared import ModelWithLocation
from comfygit_core.models.workflow import (
    ResolvedModel,
    WorkflowDependencies,
    WorkflowNodeWidgetRef,
)
from comfygit_core.services.workflow_manifest_reconciler import WorkflowManifestReconciler
from comfygit_core.services.workflow_resolution_service import ResolutionContext


class TestModelDeduplication:
    """Test that duplicate model references are resolved only once."""

    @pytest.fixture
    def workflow_manager(self, tmp_path):
        """Create a WorkflowManager with mocked dependencies."""
        manager = Mock(spec=WorkflowManager)
        manager.environment_name = "test_env"
        manager.pyproject = Mock()
        manager.pyproject.workflows = Mock()
        manager.model_repository = Mock()
        manager.workflow_cache = Mock()
        manager.builtin_versions_repository = None

        # Make the actual methods we're testing real
        manager._write_model_resolution_grouped = WorkflowManager._write_model_resolution_grouped.__get__(manager)
        manager._get_category_for_node_ref = Mock(return_value="vae")
        manager._get_default_criticality = Mock(return_value="flexible")
        manager.manifest_reconciler = WorkflowManifestReconciler(
            pyproject=manager.pyproject,
            model_repository=manager.model_repository,
            normalize_package_id=lambda value: value,
            category_for_node_ref=manager._get_category_for_node_ref,
            default_criticality=manager._get_default_criticality,
            is_manual_workflow_model=WorkflowManager._is_manual_workflow_model,
            manual_workflow_model_key=WorkflowManager._manual_workflow_model_key,
            cleanup_orphaned_workflow_state=Mock(return_value=0),
        )

        return manager

    def test_same_model_in_multiple_nodes_groups_refs(self, workflow_manager):
        """When same model appears in multiple nodes, all refs should be grouped together."""
        # Arrange: Two nodes reference the same model
        ref1 = WorkflowNodeWidgetRef(
            node_id="39",
            node_type="VAELoader",
            widget_index=0,
            widget_value="qwen_image_vae.safetensors"
        )
        ref2 = WorkflowNodeWidgetRef(
            node_id="337",
            node_type="VAELoader",
            widget_index=0,
            widget_value="qwen_image_vae.safetensors"
        )

        resolved_model = ModelWithLocation(
            hash="abc123",
            file_size=1000,
            blake3_hash="blake3_abc123",
            sha256_hash=None,
            relative_path="vae/qwen_image_vae.safetensors",
            filename="qwen_image_vae.safetensors",
            mtime=123456,
            last_seen=123456,
            base_directory="/models",
            metadata={}
        )

        resolved = ResolvedModel(
            workflow="test_workflow",
            reference=ref1,  # Primary ref
            match_type="exact",
            resolved_model=resolved_model,
            match_confidence=1.0,
        )

        workflow_manager.model_repository.get_sources.return_value = []

        # Act: Write grouped resolution with both refs
        all_refs = [ref1, ref2]
        workflow_manager._write_model_resolution_grouped("test_workflow", resolved, all_refs)

        # Assert: pyproject.workflows.add_workflow_model called with grouped refs
        workflow_manager.pyproject.workflows.add_workflow_model.assert_called_once()
        call_args = workflow_manager.pyproject.workflows.add_workflow_model.call_args

        assert call_args[0][0] == "test_workflow"
        manifest_model = call_args[0][1]

        assert isinstance(manifest_model, ManifestWorkflowModel)
        assert len(manifest_model.nodes) == 2
        assert manifest_model.nodes[0] == ref1
        assert manifest_model.nodes[1] == ref2
        assert manifest_model.hash == "abc123"
        assert manifest_model.status == "resolved"

    def test_different_models_not_grouped(self):
        """Different models should not be grouped together."""
        # This test verifies the grouping key logic
        ref1 = WorkflowNodeWidgetRef(
            node_id="39",
            node_type="VAELoader",
            widget_index=0,
            widget_value="model_a.safetensors"
        )
        ref2 = WorkflowNodeWidgetRef(
            node_id="40",
            node_type="VAELoader",
            widget_index=0,
            widget_value="model_b.safetensors"
        )

        # Different widget_value should create different grouping keys
        key1 = (ref1.widget_value, ref1.node_type)
        key2 = (ref2.widget_value, ref2.node_type)

        assert key1 != key2

    def test_same_model_different_node_types_not_grouped(self):
        """Same model in different node types should not be grouped (safety)."""
        ref1 = WorkflowNodeWidgetRef(
            node_id="39",
            node_type="VAELoader",
            widget_index=0,
            widget_value="qwen_image_vae.safetensors"
        )
        ref2 = WorkflowNodeWidgetRef(
            node_id="40",
            node_type="CustomVAELoader",  # Different node type
            widget_index=0,
            widget_value="qwen_image_vae.safetensors"
        )

        # Different node_type should create different grouping keys
        key1 = (ref1.widget_value, ref1.node_type)
        key2 = (ref2.widget_value, ref2.node_type)

        assert key1 != key2

    def test_download_intent_with_multiple_refs(self, workflow_manager):
        """Download intents should also support multiple node refs."""
        ref1 = WorkflowNodeWidgetRef(
            node_id="39",
            node_type="VAELoader",
            widget_index=0,
            widget_value="qwen_image_vae.safetensors"
        )
        ref2 = WorkflowNodeWidgetRef(
            node_id="337",
            node_type="VAELoader",
            widget_index=0,
            widget_value="qwen_image_vae.safetensors"
        )

        resolved = ResolvedModel(
            workflow="test_workflow",
            reference=ref1,
            match_type="download_intent",
            resolved_model=None,
            model_source="https://civitai.com/api/download/models/12345",
            target_path=Path("vae/qwen_image_vae.safetensors"),
            match_confidence=1.0,
        )

        all_refs = [ref1, ref2]
        workflow_manager._write_model_resolution_grouped("test_workflow", resolved, all_refs)

        # Assert: Manifest has download intent with both refs
        call_args = workflow_manager.pyproject.workflows.add_workflow_model.call_args
        manifest_model = call_args[0][1]

        assert len(manifest_model.nodes) == 2
        assert manifest_model.status == "unresolved"
        assert manifest_model.sources == ["https://civitai.com/api/download/models/12345"]
        assert manifest_model.relative_path == "vae/qwen_image_vae.safetensors"

    def test_optional_model_with_multiple_refs(self, workflow_manager):
        """Optional models should support multiple node refs."""
        ref1 = WorkflowNodeWidgetRef(
            node_id="39",
            node_type="VAELoader",
            widget_index=0,
            widget_value="optional_vae.safetensors"
        )
        ref2 = WorkflowNodeWidgetRef(
            node_id="337",
            node_type="VAELoader",
            widget_index=0,
            widget_value="optional_vae.safetensors"
        )

        resolved = ResolvedModel(
            workflow="test_workflow",
            reference=ref1,
            match_type="workflow_context",
            resolved_model=None,
            is_optional=True,
            match_confidence=1.0,
        )

        all_refs = [ref1, ref2]
        workflow_manager._write_model_resolution_grouped("test_workflow", resolved, all_refs)

        # Assert: Manifest has optional criticality with both refs
        call_args = workflow_manager.pyproject.workflows.add_workflow_model.call_args
        manifest_model = call_args[0][1]

        assert len(manifest_model.nodes) == 2
        assert manifest_model.criticality == "optional"
        assert manifest_model.status == "unresolved"


class TestDeduplicationIntegration:
    """Integration tests for full deduplication flow."""

    def test_grouping_key_logic(self):
        """Verify the grouping key correctly identifies duplicates."""
        # Same model, same node type → should group
        refs_same = [
            WorkflowNodeWidgetRef("39", "VAELoader", 0, "model.safetensors"),
            WorkflowNodeWidgetRef("337", "VAELoader", 0, "model.safetensors"),
        ]

        groups = {}
        for ref in refs_same:
            key = (ref.widget_value, ref.node_type)
            if key not in groups:
                groups[key] = []
            groups[key].append(ref)

        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 2

    def test_grouping_preserves_all_refs(self):
        """Verify all refs are preserved during grouping."""
        refs = [
            WorkflowNodeWidgetRef("1", "VAELoader", 0, "model_a.safetensors"),
            WorkflowNodeWidgetRef("2", "VAELoader", 0, "model_a.safetensors"),
            WorkflowNodeWidgetRef("3", "VAELoader", 0, "model_b.safetensors"),
            WorkflowNodeWidgetRef("4", "CheckpointLoaderSimple", 0, "model_a.safetensors"),
        ]

        groups = {}
        for ref in refs:
            key = (ref.widget_value, ref.node_type)
            if key not in groups:
                groups[key] = []
            groups[key].append(ref)

        # Should have 3 groups:
        # 1. (model_a, VAELoader) → refs 1, 2
        # 2. (model_b, VAELoader) → ref 3
        # 3. (model_a, CheckpointLoaderSimple) → ref 4
        assert len(groups) == 3
        assert len(groups[("model_a.safetensors", "VAELoader")]) == 2
        assert len(groups[("model_b.safetensors", "VAELoader")]) == 1
        assert len(groups[("model_a.safetensors", "CheckpointLoaderSimple")]) == 1


class TestResolveWorkflowDeduplication:
    """Test that resolve_workflow() deduplicates model refs in status reporting."""

    def test_resolve_workflow_deduplicates_model_refs_in_unresolved_list(self):
        """When same model appears in multiple nodes, models_unresolved should contain unique refs only.

        This test verifies that status reporting shows accurate counts by deduplicating
        model references at the resolve_workflow() level, not just in fix_resolution().

        Example: If workflow has qwen_image_vae.safetensors in nodes #39 and #337,
        models_unresolved should contain 1 representative ref, not 2 duplicate refs.
        """
        # ARRANGE: Create workflow dependencies with duplicate model refs
        ref1 = WorkflowNodeWidgetRef(
            node_id="39",
            node_type="VAELoader",
            widget_index=0,
            widget_value="qwen_image_vae.safetensors"
        )
        ref2 = WorkflowNodeWidgetRef(
            node_id="337",
            node_type="VAELoader",
            widget_index=0,
            widget_value="qwen_image_vae.safetensors"
        )
        ref3 = WorkflowNodeWidgetRef(
            node_id="38",
            node_type="CLIPLoader",
            widget_index=0,
            widget_value="qwen_2.5_vl_7b_fp8_scaled.safetensors"
        )
        ref4 = WorkflowNodeWidgetRef(
            node_id="338",
            node_type="CLIPLoader",
            widget_index=0,
            widget_value="qwen_2.5_vl_7b_fp8_scaled.safetensors"
        )

        # Create analysis with 4 model refs (2 unique models)
        analysis = WorkflowDependencies(
            workflow_name="test_workflow",
            found_models=[ref1, ref2, ref3, ref4],
            builtin_nodes=[],
            non_builtin_nodes=[]
        )

        # Create mocked workflow manager
        manager = Mock(spec=WorkflowManager)
        manager.environment_name = "test_env"
        manager.pyproject = Mock()
        manager.pyproject.nodes = Mock()
        manager.pyproject.nodes.get_existing.return_value = {}
        manager.pyproject.workflows = Mock()
        manager.pyproject.workflows.get_custom_node_map.return_value = {}
        manager.pyproject.workflows.get_workflow_models.return_value = []
        manager._get_consensus_custom_node_map = Mock(return_value={})
        manager.pyproject_manager = Mock()
        manager.pyproject_manager.models = Mock()
        manager.pyproject_manager.models.get_all.return_value = {}

        manager.global_node_resolver = Mock()
        manager.model_resolver = Mock()
        manager.workflow_cache = Mock()
        manager.builtin_versions_repository = None
        manager.get_workflow_path = Mock(return_value=Path("/fake/path.json"))
        manager.workflow_resolution_context_builder = Mock()
        manager.workflow_resolution_context_builder.build_runtime_context.return_value = ResolutionContext(
            workflow_name="test_workflow",
        )

        # All models unresolved (return None)
        manager.model_resolver.resolve_model.return_value = None

        # Bind actual resolve_workflow method
        manager.resolve_workflow = WorkflowManager.resolve_workflow.__get__(manager)
        policy = Mock()
        manager._get_workflow_model_path_policy = Mock(return_value=policy)

        # ACT: Resolve workflow
        result = manager.resolve_workflow(analysis)

        # ASSERT: Should have 2 unique unresolved models, not 4
        # Current bug: This will fail because models_unresolved contains all 4 refs
        # Expected: models_unresolved should contain 2 representative refs (one per unique model)
        assert len(result.models_unresolved) == 2, (
            f"Expected 2 unique unresolved models (deduplicated), "
            f"got {len(result.models_unresolved)}: {result.models_unresolved}"
        )

        # Verify the unique models are the right ones
        unresolved_keys = {(ref.widget_value, ref.node_type) for ref in result.models_unresolved}
        expected_keys = {
            ("qwen_image_vae.safetensors", "VAELoader"),
            ("qwen_2.5_vl_7b_fp8_scaled.safetensors", "CLIPLoader")
        }
        assert unresolved_keys == expected_keys, (
            f"Expected unique model keys {expected_keys}, got {unresolved_keys}"
        )

    def test_resolve_workflow_checks_path_sync_for_unsaved_workflow(self):
        """Path sync should still be evaluated for unsaved workflows analyzed from JSON."""
        ref = WorkflowNodeWidgetRef(
            node_id="301",
            node_type="CheckpointLoaderSimple",
            widget_index=0,
            widget_value="Z-Image\\qwen_3_4b.safetensors"
        )

        analysis = WorkflowDependencies(
            workflow_name="unsaved",
            found_models=[ref],
            builtin_nodes=[],
            non_builtin_nodes=[],
        )

        manager = Mock(spec=WorkflowManager)
        manager.environment_name = "test_env"
        manager.pyproject = Mock()
        manager.pyproject.nodes = Mock()
        manager.pyproject.nodes.get_existing.return_value = {}
        manager.pyproject.workflows = Mock()
        manager.pyproject.workflows.get_custom_node_map.return_value = {}
        manager.pyproject.workflows.get_workflow_models.return_value = []
        manager._get_consensus_custom_node_map = Mock(return_value={})
        manager.pyproject_manager = Mock()
        manager.pyproject_manager.models = Mock()
        manager.pyproject_manager.models.get_all.return_value = {}

        manager.global_node_resolver = Mock()
        manager.model_resolver = Mock()
        manager.workflow_cache = Mock()
        manager.builtin_versions_repository = None
        manager.get_workflow_path = Mock(side_effect=FileNotFoundError("unsaved workflow"))
        manager.workflow_resolution_context_builder = Mock()
        manager.workflow_resolution_context_builder.build_runtime_context.return_value = ResolutionContext(
            workflow_name="unsaved",
        )

        resolved_model = ModelWithLocation(
            hash="hash-123",
            file_size=1234,
            blake3_hash="blake3-hash-123",
            sha256_hash=None,
            relative_path="checkpoints/qwen_3_4b.safetensors",
            filename="qwen_3_4b.safetensors",
            mtime=123456,
            last_seen=123456,
            base_directory="/models",
            metadata={}
        )
        manager.model_resolver.resolve_model.return_value = [
            ResolvedModel(
                workflow="unsaved",
                reference=ref,
                resolved_model=resolved_model,
                match_type="exact",
                match_confidence=1.0,
            )
        ]

        manager.resolve_workflow = WorkflowManager.resolve_workflow.__get__(manager)
        policy = Mock()

        def annotate_resolution(resolution):
            resolution.models_resolved[0].needs_path_sync = True

        policy.annotate_resolution.side_effect = annotate_resolution
        manager._get_workflow_model_path_policy = Mock(return_value=policy)

        result = manager.resolve_workflow(analysis)

        assert len(result.models_resolved) == 1
        assert result.models_resolved[0].needs_path_sync is True
        policy.annotate_resolution.assert_called_once_with(result)
