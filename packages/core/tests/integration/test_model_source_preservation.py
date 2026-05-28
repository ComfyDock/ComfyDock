"""
Integration tests for model source preservation.

FIXED: Sources from SQLite repository are now correctly written to global models table,
but NOT to workflow models (which are lightweight references).

Expected behavior:
- Model has source in SQLite repository ✓
- Model is resolved from repository ✓
- Sources are written to global models table in pyproject.toml ✓
- Sources are NOT in workflow models (workflow models only have hash reference) ✓
"""

from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder
from helpers.pyproject_assertions import PyprojectAssertions
from helpers.workflow_builder import WorkflowBuilder


class TestModelSourcePreservation:
    """Test that model sources flow from repository to pyproject during resolution."""

    def test_progressive_resolution_preserves_sources_from_repository(self, test_env, test_workspace):
        """
        Progressive resolution writes sources to global table, not workflow models.

        Scenario:
        1. Download model with source URL (adds to repository with source)
        2. Use model in workflow
        3. Resolve workflow progressively
        4. EXPECTED: Global table has sources, workflow model only has hash
        """
        # ARRANGE - Create model with source in repository
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model(
            filename="test_lora.safetensors",
            relative_path="loras",
            size_mb=1,
            category="loras"
        )
        builder.index_all()

        # Get the ACTUAL hash from indexed model (not builder's deterministic hash)
        indexed_models = test_workspace.model_repository.get_all_models()
        indexed_model = next((m for m in indexed_models if m.filename == "test_lora.safetensors"), None)
        assert indexed_model is not None, "Model should be indexed"
        model_hash = indexed_model.hash

        # Add source to repository (simulates download with URL)
        test_url = "https://civitai.com/api/download/models/12345"
        test_workspace.model_repository.add_source(
            model_hash=model_hash,
            source_type="civitai",
            source_url=test_url
        )

        # Verify source is in repository
        sources = test_workspace.model_repository.get_sources(model_hash)
        assert len(sources) == 1
        assert sources[0]['url'] == test_url

        # Create workflow using this model
        workflow = (
            WorkflowBuilder()
            .add_lora_loader("test_lora.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # ACT - Resolve workflow (progressive mode)
        _deps, resolution = test_env.workflow_manager.analyze_and_resolve_workflow("test_workflow")

        # Apply resolution writes to pyproject
        test_env.workflow_manager.apply_resolution(resolution)

        # ASSERT - Correct behavior: sources in global table, not workflow models
        assertions = PyprojectAssertions(test_env)

        # Check workflow model does NOT have sources (lightweight reference)
        workflow_model = (
            assertions
            .has_workflow("test_workflow")
            .has_model_with_filename("test_lora.safetensors")
        )
        assert workflow_model.config.get("sources", []) == [], \
            f"Workflow model should not have sources (lightweight reference), got {workflow_model.config.get('sources', [])}"

        # Check global model table HAS sources
        global_model = assertions.has_global_model(model_hash)
        global_model.has_source(test_url)

    def test_bulk_resolution_preserves_sources_from_repository(self, test_env, test_workspace):
        """
        Bulk resolution writes sources to global table, not workflow models.

        Scenario:
        1. Create multiple models with sources in repository
        2. Create workflow using these models
        3. Resolve workflow in bulk (apply_resolution path)
        4. EXPECTED: Global table has all sources, workflow models only have hashes
        """
        # ARRANGE - Create two models with sources
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("checkpoint.safetensors", "checkpoints", size_mb=4, category="checkpoints")
        builder.add_model("lora.safetensors", "loras", size_mb=1, category="loras")
        builder.index_all()

        # Get actual hashes from indexed models
        indexed_models = test_workspace.model_repository.get_all_models()
        checkpoint_model = next((m for m in indexed_models if m.filename == "checkpoint.safetensors"), None)
        lora_model = next((m for m in indexed_models if m.filename == "lora.safetensors"), None)
        assert checkpoint_model is not None and lora_model is not None, "Models should be indexed"

        checkpoint_hash = checkpoint_model.hash
        lora_hash = lora_model.hash

        # Add sources to repository
        checkpoint_url = "https://civitai.com/api/download/models/1111"
        lora_url = "https://huggingface.co/models/test/lora.safetensors"

        test_workspace.model_repository.add_source(checkpoint_hash, "civitai", checkpoint_url)
        test_workspace.model_repository.add_source(lora_hash, "huggingface", lora_url)

        # Create workflow with both models
        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("checkpoint.safetensors")
            .add_lora_loader("lora.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "multi_model", workflow)

        # ACT - Resolve in bulk
        _deps, resolution = test_env.workflow_manager.analyze_and_resolve_workflow("multi_model")
        test_env.workflow_manager.apply_resolution(resolution)

        # ASSERT - Correct behavior: sources in global table, not workflow models
        assertions = PyprojectAssertions(test_env)

        # Check checkpoint workflow model does NOT have sources
        checkpoint_wf_model = (
            assertions
            .has_workflow("multi_model")
            .has_model_with_filename("checkpoint.safetensors")
        )
        assert checkpoint_wf_model.config.get("sources", []) == [], \
            "Checkpoint workflow model should not have sources"

        # Check lora workflow model does NOT have sources
        lora_wf_model = (
            assertions
            .has_workflow("multi_model")
            .has_model_with_filename("lora.safetensors")
        )
        assert lora_wf_model.config.get("sources", []) == [], \
            "Lora workflow model should not have sources"

        # Check global models table HAS sources
        assertions.has_global_model(checkpoint_hash).has_source(checkpoint_url)
        assertions.has_global_model(lora_hash).has_source(lora_url)

    def test_collaboration_scenario_succeeds_with_sources(self, test_env, test_workspace):
        """
        Real-world collaboration scenario now works correctly.

        Dev A scenario:
        1. Dev A downloads model (has source in their repository)
        2. Dev A uses model in workflow
        3. Dev A commits workflow
        4. pyproject.toml is pushed to git (with sources in global table)

        Dev B scenario:
        5. Dev B pulls pyproject.toml
        6. Dev B runs repair/import
        7. EXPECTED: Models download using sources from pyproject global table
        8. ACTUAL: Works! Sources are in global table, Dev B can download
        """
        # DEV A - Download and use model
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("shared_model.safetensors", "checkpoints", size_mb=2)
        builder.index_all()

        # Get the ACTUAL hash from the indexed model (not the builder's deterministic hash)
        indexed_models = test_workspace.model_repository.get_all_models()
        indexed_model = next((m for m in indexed_models if m.filename == "shared_model.safetensors"), None)
        assert indexed_model is not None, "Model should be indexed"
        model_hash = indexed_model.hash

        model_url = "https://civitai.com/api/download/models/9999"

        # Simulate download - adds source to repository
        test_workspace.model_repository.add_source(model_hash, "civitai", model_url)

        # Dev A creates workflow
        workflow = WorkflowBuilder().add_checkpoint_loader("shared_model.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "shared_wf", workflow)

        # Dev A resolves and commits
        _deps, resolution = test_env.workflow_manager.analyze_and_resolve_workflow("shared_wf")
        test_env.workflow_manager.apply_resolution(resolution)

        # Check what Dev A commits to pyproject.toml
        pyproject_config = test_env.pyproject.load()
        global_models = pyproject_config.get("tool", {}).get("comfygit", {}).get("models", {})

        # Verify model is in global table WITH sources
        assert model_hash in global_models, "Model should be in global table"
        committed_model = global_models[model_hash]

        # Sources should be in global table - Dev B can download!
        committed_sources = committed_model.get("sources", [])
        assert model_url in committed_sources, \
            f"Model should have source in global table for collaboration. " \
            f"Sources in pyproject: {committed_sources}, Expected: ['{model_url}']"
