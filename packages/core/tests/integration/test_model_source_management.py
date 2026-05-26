"""Integration tests for model source management and commit behavior."""
from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder


class TestModelSourceManagement:
    """Test adding download sources to models in pyproject and index."""

    def test_add_source_to_model_updates_both_stores(self, test_env, test_workspace):
        """Adding source should update both pyproject.toml and SQLite index."""
        # ARRANGE - Create and index a model
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model(
            filename="sd15.safetensors",
            relative_path="checkpoints/sd15.safetensors",
            size_mb=4,
            category="checkpoints"
        )
        builder.index_all()

        # Get the ACTUAL hash from the indexed model (not the deterministic builder hash)
        indexed_models = test_workspace.model_repository.get_all_models()
        indexed_model = next((m for m in indexed_models if m.filename == "sd15.safetensors"), None)
        assert indexed_model is not None, "Model should be indexed"
        model_hash = indexed_model.hash

        # Add model to pyproject global section
        from comfygit_core.models.manifest import ManifestModel
        manifest_model = ManifestModel(
            hash=model_hash,
            filename="sd15.safetensors",
            size=indexed_model.file_size,
            relative_path="checkpoints/sd15.safetensors",
            category="checkpoints",
            sources=[]
        )
        test_env.pyproject.models.add_model(manifest_model)

        # Verify initial state - no sources
        model_before = test_env.pyproject.models.get_by_hash(model_hash)
        assert model_before is not None
        assert model_before.sources == []

        # ACT - Add source via core API
        test_url = "https://civitai.com/api/download/models/12345"
        result = test_env.add_model_source(model_hash, test_url)

        # ASSERT - Both stores updated
        assert result.success, f"add_model_source should succeed: {result.error}"
        assert result.model_hash == model_hash
        assert result.url == test_url
        assert result.source_type == "civitai"

        # Check pyproject updated
        model_after = test_env.pyproject.models.get_by_hash(model_hash)
        assert model_after is not None
        assert test_url in model_after.sources, \
            f"Source should be in pyproject. Found: {model_after.sources}"

        # Check SQLite index updated
        indexed_model_after = test_workspace.model_repository.get_model(model_hash)
        assert indexed_model_after is not None, "Model should still be indexed"

    def test_add_source_to_unindexed_model_updates_pyproject_only(self, test_env):
        """Adding source to model not in local index should still update pyproject."""
        # ARRANGE - Create a model entry in pyproject without indexing it
        # (simulates a model that was downloaded but index wasn't updated yet)
        fake_hash = "abc123" * 10  # 60 char hash
        from comfygit_core.models.manifest import ManifestModel
        manifest_model = ManifestModel(
            hash=fake_hash,
            filename="remote_model.safetensors",
            size=1000,
            relative_path="checkpoints/remote_model.safetensors",
            category="checkpoints",
            sources=[]
        )
        test_env.pyproject.models.add_model(manifest_model)

        # ACT - Add source
        test_url = "https://huggingface.co/models/test.safetensors"
        result = test_env.add_model_source(fake_hash, test_url)

        # ASSERT - Pyproject updated, index unchanged
        assert result.success
        model_after = test_env.pyproject.models.get_by_hash(fake_hash)
        assert test_url in model_after.sources


class TestAutoResolvedModelsCommit:
    """Regression tests for the bug where auto-resolved models weren't written to pyproject during commit.

    Bug description:
    - User had a clean workflow with 2 resolved models in pyproject
    - User added a 3rd model (lora) in ComfyUI and saved
    - User ran commit
    - BUG: The 3rd model was auto-resolved but NOT written to pyproject.toml

    Root cause: commit only copied workflow files, didn't apply resolution results.
    """

    def test_newly_resolved_models_written_to_pyproject_on_commit(self, test_env, test_workspace):
        """
        REGRESSION TEST for bug: commit should write auto-resolved models to pyproject.

        Scenario:
        1. User has workflow with 2 models (already in pyproject)
        2. User adds 3rd model in ComfyUI (auto-resolvable from index)
        3. User commits
        4. Expected: pyproject should have all 3 models
        5. Bug: pyproject only had 2 models (3rd was resolved but not written)
        """
        # ARRANGE - Create 3 models in the index
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("checkpoint1.safetensors", "checkpoints/checkpoint1.safetensors", 200, "checkpoints")
        builder.add_model("lora1.safetensors", "loras/lora1.safetensors", 200, "loras")
        builder.add_model("lora2.safetensors", "loras/lora2.safetensors", 19, "loras")  # The 3rd model
        builder.index_all()

        # Create workflow with first 2 models
        workflow_v1 = {
            "id": "test-workflow",
            "nodes": [
                {
                    "id": 1,
                    "type": "CheckpointLoaderSimple",
                    "pos": [0, 0],
                    "size": [315, 98],
                    "flags": {},
                    "order": 0,
                    "mode": 0,
                    "inputs": [],
                    "outputs": [{"name": "MODEL", "type": "MODEL", "links": [1]}],
                    "properties": {},
                    "widgets_values": ["checkpoint1.safetensors"]
                },
                {
                    "id": 2,
                    "type": "LoraLoader",
                    "pos": [100, 100],
                    "size": [270, 126],
                    "flags": {},
                    "order": 1,
                    "mode": 0,
                    "inputs": [],
                    "outputs": [],
                    "properties": {},
                    "widgets_values": ["lora1.safetensors", 1.0, 1.0]
                }
            ],
            "links": [[1, 1, 0, 2, 0, "MODEL"]],
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4
        }

        # Simulate user saving initial workflow and committing
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow_v1)

        # Resolve workflow to fix path sync issues before committing
        _deps, resolution = test_env.workflow_manager.analyze_and_resolve_workflow("test_workflow")
        test_env.workflow_manager.apply_resolution(resolution)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status=workflow_status, message="Initial commit with 2 models")

        # Verify initial state - 2 models in pyproject
        pyproject_v1 = test_env.pyproject.load()
        workflow_models_v1 = pyproject_v1["tool"]["comfygit"]["workflows"]["test_workflow"]["models"]
        assert len(workflow_models_v1) == 2, f"Should have 2 models initially, got {len(workflow_models_v1)}"

        # ACT - User adds 3rd model (lora2) in ComfyUI and saves
        workflow_v2 = workflow_v1.copy()
        workflow_v2["nodes"] = workflow_v1["nodes"].copy()
        workflow_v2["nodes"].append({
            "id": 3,
            "type": "LoraLoader",
            "pos": [200, 200],
            "size": [270, 126],
            "flags": {},
            "order": 2,
            "mode": 0,
            "inputs": [],
            "outputs": [],
            "properties": {},
            "widgets_values": ["lora2.safetensors", 1.0, 1.0]  # New model
        })
        workflow_v2["links"].append([2, 2, 0, 3, 0, "MODEL"])

        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow_v2)

        # Resolve workflow to fix path sync issues before committing
        _deps, resolution = test_env.workflow_manager.analyze_and_resolve_workflow("test_workflow")
        test_env.workflow_manager.apply_resolution(resolution)

        # Commit the changes
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status=workflow_status, message="Added lora2")

        # ASSERT - pyproject should now have all 3 models
        pyproject_v2 = test_env.pyproject.load()
        workflow_models_v2 = pyproject_v2["tool"]["comfygit"]["workflows"]["test_workflow"]["models"]

        assert len(workflow_models_v2) == 3, \
            f"BUG: Expected 3 models after commit, got {len(workflow_models_v2)}. " \
            f"Models: {[m['filename'] for m in workflow_models_v2]}"

        # Verify all 3 models are present
        model_filenames = {m["filename"] for m in workflow_models_v2}
        assert "checkpoint1.safetensors" in model_filenames
        assert "lora1.safetensors" in model_filenames
        assert "lora2.safetensors" in model_filenames, \
            "BUG: Newly added lora2 should be in pyproject after commit"

        # Verify the 3rd model is properly resolved (has hash)
        lora2_model = next(m for m in workflow_models_v2 if m["filename"] == "lora2.safetensors")
        assert lora2_model["status"] == "resolved", \
            f"lora2 should be resolved, got status={lora2_model.get('status')}"
        assert "hash" in lora2_model, "lora2 should have hash after resolution"
        assert lora2_model["category"] == "loras"
