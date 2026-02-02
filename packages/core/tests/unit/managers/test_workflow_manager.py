"""Tests for WorkflowManager normalization logic."""
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from comfygit_core.managers.workflow_manager import WorkflowManager
from comfygit_core.utils.workflow_hash import normalize_workflow


@pytest.fixture
def workflow_manager(tmp_path):
    """Create a minimal WorkflowManager for testing normalization."""
    with patch('comfygit_core.managers.workflow_manager.GlobalNodeResolver'):
        with patch('comfygit_core.managers.workflow_manager.ModelResolver'):
            # Create a mock workflow cache
            from comfygit_core.caching.workflow_cache import WorkflowCacheRepository
            cache_db = WorkflowCacheRepository(tmp_path / "workflows.db")

            manager = WorkflowManager(
                comfyui_path=Path("/tmp/comfyui"),
                cec_path=Path("/tmp/cec"),
                pyproject=Mock(),
                model_repository=Mock(),
                node_mapping_repository=Mock(),
                model_downloader=Mock(),
                workflow_cache=cache_db,
                environment_name="test-env"
            )
            return manager


def test_normalize_workflow_removes_volatile_fields(workflow_manager):
    """Test that workflow normalization removes volatile metadata fields."""

    workflow = {
        "id": "test-workflow",
        "revision": 5,
        "nodes": [],
        "links": [],
        "extra": {
            "ds": {"scale": 1.0, "offset": [0, 0]},
            "frontendVersion": "1.25.11",
            "someOtherField": "preserved"
        }
    }

    normalized = normalize_workflow(workflow)

    # Check volatile fields removed
    assert "revision" not in normalized
    assert "ds" not in normalized.get("extra", {})
    assert "frontendVersion" not in normalized.get("extra", {})

    # Check other fields preserved
    assert normalized["id"] == "test-workflow"
    assert normalized["extra"]["someOtherField"] == "preserved"


def test_normalize_workflow_handles_randomize_seeds(workflow_manager):
    """Test that auto-generated seeds with 'randomize' mode are normalized."""

    workflow = {
        "nodes": [
            {
                "id": "3",
                "type": "KSampler",
                "widgets_values": [609167611557182, "randomize", 20, 8, "euler", "normal", 1],
                "api_widget_values": [609167611557182, "randomize", 20, 8, "euler", "normal", 1]
            }
        ]
    }

    normalized = normalize_workflow(workflow)

    # Seed should be normalized to 0 when control is "randomize"
    assert normalized["nodes"][0]["widgets_values"][0] == 0
    assert normalized["nodes"][0]["api_widget_values"][0] == 0

    # Other values should be preserved
    assert normalized["nodes"][0]["widgets_values"][2] == 20  # steps
    assert normalized["nodes"][0]["widgets_values"][3] == 8  # cfg


def test_normalize_workflow_preserves_fixed_seeds(workflow_manager):
    """Test that user-set fixed seeds are NOT normalized."""

    workflow = {
        "nodes": [
            {
                "id": "3",
                "type": "KSampler",
                "widgets_values": [12345, "fixed", 20, 8, "euler", "normal", 1],
                "api_widget_values": [12345, "fixed", 20, 8, "euler", "normal", 1]
            }
        ]
    }

    normalized = normalize_workflow(workflow)

    # Fixed seed should be preserved
    assert normalized["nodes"][0]["widgets_values"][0] == 12345
    assert normalized["nodes"][0]["api_widget_values"][0] == 12345


def test_workflows_differ_detects_real_changes():
    """Test that _workflows_differ detects actual workflow changes."""
    # This would require more setup with actual files
    # Skipping for now as it's integration-level


def test_apply_resolution_preserves_existing_sources(workflow_manager):
    """Test that apply_resolution preserves sources from existing models in global table."""
    from comfygit_core.models.manifest import ManifestModel
    from comfygit_core.models.shared import ModelWithLocation
    from comfygit_core.models.workflow import (
        ResolutionResult,
        ResolvedModel,
        WorkflowNodeWidgetRef,
    )

    # Setup: Create a model that already exists in global table with sources
    existing_hash = "abc123"
    existing_sources = ["https://civitai.com/model/123"]

    existing_model = ManifestModel(
        hash=existing_hash,
        filename="model.safetensors",
        size=1000,
        relative_path="checkpoints/model.safetensors",
        category="checkpoints",
        sources=existing_sources
    )

    # Mock get_by_hash to return existing model
    workflow_manager.pyproject.models.get_by_hash = Mock(return_value=existing_model)
    workflow_manager.pyproject.models.add_model = Mock()
    workflow_manager.pyproject.workflows.set_workflow_models = Mock()
    workflow_manager.pyproject.workflows.set_node_packs = Mock()
    workflow_manager.pyproject.workflows.get_custom_node_map = Mock(return_value={})
    workflow_manager.pyproject.workflows.get_workflow_models = Mock(return_value=[])
    workflow_manager.pyproject.workflows.remove_custom_node_mapping = Mock()
    workflow_manager.pyproject.workflows.remove_workflows = Mock(return_value=0)
    workflow_manager.pyproject.load = Mock(return_value={'tool': {'comfygit': {'workflows': {'test_workflow': {}}}}})
    workflow_manager.update_workflow_model_paths = Mock()
    workflow_manager.model_repository.get_sources = Mock(return_value=[
        {'url': 'https://civitai.com/model/123', 'type': 'civitai', 'metadata': {}, 'added_time': 0}
    ])

    # Create resolution result with a resolved model
    model_with_location = ModelWithLocation(
        hash=existing_hash,
        filename="model.safetensors",
        relative_path="checkpoints/model.safetensors",
        file_size=1000,
        mtime=0.0,
        last_seen=0
    )

    ref = WorkflowNodeWidgetRef(
        node_id="4",
        node_type="CheckpointLoaderSimple",
        widget_index=0,
        widget_value="model.safetensors"
    )

    resolved = ResolvedModel(
        workflow="test_workflow",
        reference=ref,
        resolved_model=model_with_location,
        match_type="exact",
        match_confidence=1.0
    )

    resolution = ResolutionResult(
        workflow_name="test_workflow",
        models_resolved=[resolved]
    )

    # Execute apply_resolution
    workflow_manager.apply_resolution(resolution)

    # Verify that add_model was called with sources preserved
    workflow_manager.pyproject.models.add_model.assert_called_once()
    added_model = workflow_manager.pyproject.models.add_model.call_args[0][0]

    assert added_model.sources == existing_sources, "Sources should be preserved from existing model"


def test_apply_resolution_empty_sources_for_new_models(workflow_manager):
    """Test that apply_resolution uses empty sources for new models."""
    from comfygit_core.models.shared import ModelWithLocation
    from comfygit_core.models.workflow import (
        ResolutionResult,
        ResolvedModel,
        WorkflowNodeWidgetRef,
    )

    # Mock get_by_hash to return None (model doesn't exist yet)
    workflow_manager.pyproject.models.get_by_hash = Mock(return_value=None)
    workflow_manager.pyproject.models.add_model = Mock()
    workflow_manager.pyproject.workflows.set_workflow_models = Mock()
    workflow_manager.pyproject.workflows.set_node_packs = Mock()
    workflow_manager.pyproject.workflows.get_custom_node_map = Mock(return_value={})
    workflow_manager.pyproject.workflows.get_workflow_models = Mock(return_value=[])
    workflow_manager.pyproject.workflows.remove_custom_node_mapping = Mock()
    workflow_manager.pyproject.workflows.remove_workflows = Mock(return_value=0)
    workflow_manager.pyproject.load = Mock(return_value={'tool': {'comfygit': {'workflows': {'test_workflow': {}}}}})
    workflow_manager.update_workflow_model_paths = Mock()
    workflow_manager.model_repository.get_sources = Mock(return_value=[])

    # Create resolution result
    model_with_location = ModelWithLocation(
        hash="newmodel123",
        filename="newmodel.safetensors",
        relative_path="checkpoints/newmodel.safetensors",
        file_size=2000,
        mtime=0.0,
        last_seen=0
    )

    ref = WorkflowNodeWidgetRef(
        node_id="5",
        node_type="CheckpointLoaderSimple",
        widget_index=0,
        widget_value="newmodel.safetensors"
    )

    resolved = ResolvedModel(
        workflow="test_workflow",
        reference=ref,
        resolved_model=model_with_location,
        match_type="exact",
        match_confidence=1.0
    )

    resolution = ResolutionResult(
        workflow_name="test_workflow",
        models_resolved=[resolved]
    )

    # Execute apply_resolution
    workflow_manager.apply_resolution(resolution)

    # Verify that add_model was called with empty sources for new model
    workflow_manager.pyproject.models.add_model.assert_called_once()
    added_model = workflow_manager.pyproject.models.add_model.call_args[0][0]

    assert added_model.sources == [], "New models should have empty sources"
    pass


class TestStripBaseDirectoryForNode:
    """Test path stripping logic for ComfyUI node loaders.

    Note: Path stripping is still needed even with symlinks!
    See: docs/context/comfyui-node-loader-base-directories.md
    """

    @pytest.fixture
    def workflow_manager_with_config(self, tmp_path):
        """Create WorkflowManager with a properly configured ModelConfig."""
        from comfygit_core.caching.workflow_cache import WorkflowCacheRepository
        from comfygit_core.configs.model_config import ModelConfig

        # Create a ModelConfig with equivalent directories
        model_config = ModelConfig(
            version="1.0",
            default_extensions=[".safetensors", ".ckpt", ".pt", ".pth"],
            standard_directories=["checkpoints", "loras", "vae", "clip", "unet"],
            directory_overrides={},
            node_directory_mappings={
                "CheckpointLoaderSimple": ["checkpoints"],
                "CheckpointLoader": ["checkpoints"],
                "LoraLoader": ["loras"],
                "VAELoader": ["vae"],
                "ControlNetLoader": ["controlnet"],
                "UpscaleModelLoader": ["upscale_models"],
                "CLIPLoader": ["text_encoders", "clip"],  # Equivalent directories
                "UNETLoader": ["unet", "diffusion_models"],  # Equivalent directories
            },
            node_widget_indices={}
        )

        cache_db = WorkflowCacheRepository(tmp_path / "workflows.db")

        with patch('comfygit_core.managers.workflow_manager.GlobalNodeResolver'):
            manager = WorkflowManager(
                comfyui_path=Path("/tmp/comfyui"),
                cec_path=Path("/tmp/cec"),
                pyproject=Mock(),
                model_repository=Mock(),
                node_mapping_repository=Mock(),
                model_downloader=Mock(),
                workflow_cache=cache_db,
                environment_name="test-env"
            )
            # Set the model_config on the model_resolver
            manager.model_resolver.model_config = model_config
            return manager

    def test_strip_checkpoint_loader_simple(self, workflow_manager_with_config):
        """CheckpointLoaderSimple expects path without 'checkpoints/' prefix."""
        node_type = "CheckpointLoaderSimple"
        relative_path = "checkpoints/SD1.5/helloyoung25d_V15jvae.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "SD1.5/helloyoung25d_V15jvae.safetensors"

    def test_strip_lora_loader(self, workflow_manager_with_config):
        """LoraLoader expects path without 'loras/' prefix."""
        node_type = "LoraLoader"
        relative_path = "loras/realistic/detail_tweaker.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "realistic/detail_tweaker.safetensors"

    def test_strip_vae_loader(self, workflow_manager_with_config):
        """VAELoader expects path without 'vae/' prefix."""
        node_type = "VAELoader"
        relative_path = "vae/vae-ft-mse-840000.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "vae-ft-mse-840000.safetensors"

    def test_strip_controlnet_loader(self, workflow_manager_with_config):
        """ControlNetLoader expects path without 'controlnet/' prefix."""
        node_type = "ControlNetLoader"
        relative_path = "controlnet/depth/control_v11f1p_sd15_depth.pth"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "depth/control_v11f1p_sd15_depth.pth"

    def test_multiple_base_dirs_uses_first_match(self, workflow_manager_with_config):
        """Nodes with multiple base dirs (like CheckpointLoader) strip first match."""
        node_type = "CheckpointLoader"  # Can load from checkpoints or configs
        relative_path = "checkpoints/model.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "model.safetensors"

    def test_no_matching_prefix_returns_unchanged(self, workflow_manager_with_config):
        """If path doesn't start with expected base, return as-is."""
        node_type = "CheckpointLoaderSimple"
        relative_path = "custom_folder/model.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "custom_folder/model.safetensors"

    def test_unknown_node_type_returns_unchanged(self, workflow_manager_with_config):
        """Unknown node types return path unchanged."""
        node_type = "CustomUnknownNode"
        relative_path = "checkpoints/model.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "checkpoints/model.safetensors"

    def test_path_already_stripped_returns_unchanged(self, workflow_manager_with_config):
        """If path is already without base prefix, return as-is."""
        node_type = "CheckpointLoaderSimple"
        relative_path = "SD1.5/model.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "SD1.5/model.safetensors"

    def test_nested_subdirectories_preserved(self, workflow_manager_with_config):
        """Nested paths after base are preserved."""
        node_type = "CheckpointLoaderSimple"
        relative_path = "checkpoints/SD1.5/special/subfolder/model.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "SD1.5/special/subfolder/model.safetensors"

    def test_filename_only_without_base(self, workflow_manager_with_config):
        """Filename without any directory returns as-is."""
        node_type = "CheckpointLoaderSimple"
        relative_path = "model.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "model.safetensors"

    def test_upscale_model_loader(self, workflow_manager_with_config):
        """UpscaleModelLoader expects path without 'upscale_models/' prefix."""
        node_type = "UpscaleModelLoader"
        relative_path = "upscale_models/4x-UltraSharp.pth"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "4x-UltraSharp.pth"

    def test_windows_backslash_normalized_to_forward_slash(self, workflow_manager_with_config):
        """Windows backslash paths are normalized to forward slashes."""
        node_type = "CheckpointLoaderSimple"
        relative_path = r"checkpoints\SD1.5\model.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "SD1.5/model.safetensors"

    def test_windows_backslash_stripped_correctly(self, workflow_manager_with_config):
        """Windows paths with backslashes have base directory stripped correctly."""
        node_type = "CheckpointLoaderSimple"
        relative_path = r"checkpoints\v1-5-pruned-emaonly-fp16.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "v1-5-pruned-emaonly-fp16.safetensors"

    def test_mixed_slashes_normalized(self, workflow_manager_with_config):
        """Mixed forward and backslashes are normalized."""
        node_type = "LoraLoader"
        relative_path = r"loras\style/detail_tweaker.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "style/detail_tweaker.safetensors"

    def test_clip_loader_text_encoders_prefix(self, workflow_manager_with_config):
        """CLIPLoader should strip 'text_encoders/' prefix (equivalent to 'clip/')."""
        node_type = "CLIPLoader"
        relative_path = "text_encoders/clip_model.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "clip_model.safetensors"

    def test_clip_loader_clip_prefix(self, workflow_manager_with_config):
        """CLIPLoader should strip 'clip/' prefix (equivalent to 'text_encoders/')."""
        node_type = "CLIPLoader"
        relative_path = "clip/clip_model.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "clip_model.safetensors"

    def test_unet_loader_unet_prefix(self, workflow_manager_with_config):
        """UNETLoader should strip 'unet/' prefix (equivalent to 'diffusion_models/')."""
        node_type = "UNETLoader"
        relative_path = "unet/model.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "model.safetensors"

    def test_unet_loader_diffusion_models_prefix(self, workflow_manager_with_config):
        """UNETLoader should strip 'diffusion_models/' prefix (equivalent to 'unet/')."""
        node_type = "UNETLoader"
        relative_path = "diffusion_models/model.safetensors"

        result = workflow_manager_with_config._strip_base_directory_for_node(node_type, relative_path)

        assert result == "model.safetensors"


class TestOptionalUnresolvedModelPersistence:
    """Test that optional unresolved models persist through resolution cycles.

    This tests the bug fix for models marked as optional (like RIFE) that don't
    have actual model files but need to be preserved in pyproject.toml.

    Background:
    There are THREE types of models in ResolutionResult.models_resolved:
    - Type A: resolved_model != None, is_optional = False → Normal resolved
    - Type B: resolved_model != None, is_optional = True → Optional but found
    - Type C: resolved_model == None, is_optional = True → Optional unresolved

    Type C represents models where the user made a decision ("mark as optional")
    but we don't have the actual model file. These must be preserved in
    pyproject.toml as unresolved with criticality="optional".

    The bug: apply_resolution() only handled Types A and B in the hash_to_refs
    loop, causing Type C models to disappear from pyproject.toml on subsequent
    resolution cycles.
    """

    def test_optional_unresolved_model_survives_apply_resolution(self, workflow_manager):
        """Test that optional unresolved models are preserved in apply_resolution()."""
        from comfygit_core.models.manifest import ManifestWorkflowModel
        from comfygit_core.models.workflow import (
            ResolutionResult,
            ResolvedModel,
            WorkflowNodeWidgetRef,
        )

        # Setup: Create a resolution with an optional unresolved model (Type C)
        model_ref = WorkflowNodeWidgetRef(
            node_id="11",
            node_type="RIFE VFI",
            widget_index=0,
            widget_value="rife49.pth"
        )

        optional_unresolved = ResolvedModel(
            workflow="test_workflow",
            reference=model_ref,
            resolved_model=None,  # No actual model file
            is_optional=True,     # But marked optional by user
            match_type="workflow_context",
            match_confidence=1.0
        )

        resolution = ResolutionResult(
            workflow_name="test_workflow",
            nodes_resolved=[],
            models_resolved=[optional_unresolved],  # In resolved list!
            models_unresolved=[],
            nodes_unresolved=[],
            nodes_ambiguous=[],
            models_ambiguous=[]
        )

        # Mock pyproject to capture what gets written
        written_models = []
        def mock_set_workflow_models(workflow_name, models, config=None):
            written_models.extend(models)

        workflow_manager.pyproject.workflows.set_workflow_models = mock_set_workflow_models
        workflow_manager.pyproject.workflows.set_node_packs = Mock()
        workflow_manager.pyproject.workflows.get_custom_node_map = Mock(return_value={})
        workflow_manager.pyproject.workflows.get_workflow_models = Mock(return_value=[])
        workflow_manager.pyproject.workflows.remove_custom_node_mapping = Mock()
        workflow_manager.pyproject.workflows.remove_workflows = Mock(return_value=0)
        workflow_manager.pyproject.load = Mock(return_value={'tool': {'comfygit': {'workflows': {'test_workflow': {}}}}})
        workflow_manager.pyproject.models.add_model = Mock()
        workflow_manager.pyproject.models.cleanup_orphans = Mock()

        # Mock model config and workflow path updates
        with patch.object(workflow_manager.model_resolver, 'model_config') as mock_config:
            mock_config.get_directories_for_node.return_value = []

            with patch.object(workflow_manager, 'update_workflow_model_paths'):
                # Execute
                workflow_manager.apply_resolution(resolution)

        # Verify: Optional unresolved model was written to pyproject
        assert len(written_models) == 1
        model = written_models[0]

        assert isinstance(model, ManifestWorkflowModel)
        assert model.filename == "rife49.pth"
        assert model.status == "unresolved"
        assert model.criticality == "optional"
        assert model.hash is None
        assert len(model.nodes) == 1
        assert model.nodes[0] == model_ref

    def test_mixed_model_types_all_preserved(self, workflow_manager):
        """Test all three model types are preserved: resolved, optional resolved, optional unresolved."""
        from comfygit_core.models.shared import ModelWithLocation
        from comfygit_core.models.workflow import (
            ResolutionResult,
            ResolvedModel,
            WorkflowNodeWidgetRef,
        )

        # Type A: Normal resolved (has model, not optional)
        ref_a = WorkflowNodeWidgetRef(
            node_id="1", node_type="CheckpointLoaderSimple",
            widget_index=0, widget_value="model_a.safetensors"
        )
        model_a = ModelWithLocation(
            hash="hash_a", filename="model_a.safetensors",
            file_size=1000, relative_path="checkpoints/model_a.safetensors",
            mtime=0, last_seen=0
        )
        resolved_a = ResolvedModel(
            workflow="test", reference=ref_a,
            resolved_model=model_a, is_optional=False
        )

        # Type B: Optional resolved (has model, marked optional)
        ref_b = WorkflowNodeWidgetRef(
            node_id="2", node_type="UpscaleModelLoader",
            widget_index=0, widget_value="model_b.pth"
        )
        model_b = ModelWithLocation(
            hash="hash_b", filename="model_b.pth",
            file_size=2000, relative_path="upscale_models/model_b.pth",
            mtime=0, last_seen=0
        )
        resolved_b = ResolvedModel(
            workflow="test", reference=ref_b,
            resolved_model=model_b, is_optional=True
        )

        # Type C: Optional unresolved (no model, marked optional)
        ref_c = WorkflowNodeWidgetRef(
            node_id="3", node_type="RIFE VFI",
            widget_index=0, widget_value="rife49.pth"
        )
        resolved_c = ResolvedModel(
            workflow="test", reference=ref_c,
            resolved_model=None, is_optional=True
        )

        resolution = ResolutionResult(
            workflow_name="test",
            nodes_resolved=[],
            models_resolved=[resolved_a, resolved_b, resolved_c],
            models_unresolved=[],
            nodes_unresolved=[],
            nodes_ambiguous=[],
            models_ambiguous=[]
        )

        # Setup mocks
        written_models = []
        workflow_manager.pyproject.workflows.set_workflow_models = lambda w, m, config=None: written_models.extend(m)
        workflow_manager.pyproject.workflows.set_node_packs = Mock()
        workflow_manager.pyproject.workflows.get_custom_node_map = Mock(return_value={})
        workflow_manager.pyproject.workflows.get_workflow_models = Mock(return_value=[])
        workflow_manager.pyproject.workflows.remove_custom_node_mapping = Mock()
        workflow_manager.pyproject.workflows.remove_workflows = Mock(return_value=0)
        workflow_manager.pyproject.load = Mock(return_value={'tool': {'comfygit': {'workflows': {'test': {}}}}})
        workflow_manager.pyproject.models.add_model = Mock()
        workflow_manager.pyproject.models.cleanup_orphans = Mock()
        workflow_manager.model_repository.get_sources = Mock(return_value=[])

        with patch.object(workflow_manager.model_resolver, 'model_config') as mock_config:
            mock_config.get_directories_for_node.return_value = []

            with patch.object(workflow_manager, 'update_workflow_model_paths'):
                workflow_manager.apply_resolution(resolution)

        # Verify all three types were preserved
        assert len(written_models) == 3

        # Find each model in the written list
        model_a_written = next(m for m in written_models if m.filename == "model_a.safetensors")
        model_b_written = next(m for m in written_models if m.filename == "model_b.pth")
        model_c_written = next(m for m in written_models if m.filename == "rife49.pth")

        # Type A: Normal resolved
        assert model_a_written.status == "resolved"
        assert model_a_written.hash == "hash_a"
        assert model_a_written.criticality != "optional"

        # Type B: Optional resolved
        # Note: Criticality is based on category defaults, not is_optional flag
        # upscale_models category has default criticality of "flexible"
        assert model_b_written.status == "resolved"
        assert model_b_written.hash == "hash_b"
        assert model_b_written.criticality == "flexible"

        # Type C: Optional unresolved (THE FIX!)
        assert model_c_written.status == "unresolved"
        assert model_c_written.hash is None
        assert model_c_written.criticality == "optional"
