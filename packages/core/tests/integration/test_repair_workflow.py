"""Integration tests for repair command simulating git pull workflow."""

import json


def test_repair_restores_workflows_from_cec(test_env):
    """After git pull, repair should copy workflows from .cec/ to ComfyUI/."""
    # ARRANGE: Simulate git pull scenario
    # Someone pushed workflows to .cec/ (via git)
    workflow_data = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "model.safetensors"}
        }
    }

    # Simulate workflow in .cec/ (from git pull)
    cec_workflow = test_env.cec_path / "workflows" / "pulled_workflow.json"
    cec_workflow.parent.mkdir(parents=True, exist_ok=True)
    with open(cec_workflow, 'w') as f:
        json.dump(workflow_data, f)

    # ComfyUI doesn't have this workflow yet
    comfyui_workflow = test_env.comfyui_path / "user" / "default" / "workflows" / "pulled_workflow.json"
    assert not comfyui_workflow.exists(), "Workflow should not exist in ComfyUI yet"

    # ACT: Run repair (sync)
    result = test_env.sync()

    # ASSERT: Workflow should now be in ComfyUI
    assert result.success, "Sync should succeed"
    assert comfyui_workflow.exists(), "Workflow should be copied to ComfyUI"

    with open(comfyui_workflow) as f:
        copied_data = json.load(f)
    assert copied_data == workflow_data, "Workflow content should match"


def test_repair_removes_workflows_not_in_cec(test_env):
    """Repair should remove workflows from ComfyUI that don't exist in .cec/."""
    # ARRANGE: Workflow exists in ComfyUI but not in .cec/
    workflow_data = {"1": {"class_type": "KSampler"}}
    comfyui_workflow = test_env.comfyui_path / "user" / "default" / "workflows" / "local_only.json"
    with open(comfyui_workflow, 'w') as f:
        json.dump(workflow_data, f)

    assert comfyui_workflow.exists(), "Setup: workflow should exist in ComfyUI"

    # ACT: Run repair
    result = test_env.sync()

    # ASSERT: Workflow should be removed
    assert result.success
    assert not comfyui_workflow.exists(), "Local-only workflow should be removed"


def test_repair_enriches_model_sources_from_pyproject(test_env, test_workspace):
    """Repair should sync model sources from pyproject to SQLite index."""
    # ARRANGE: Simulate teammate has model with source URL in pyproject
    # Create a model file locally
    models_dir = test_workspace.workspace_config_manager.get_models_directory()
    model_path = models_dir / "checkpoints" / "flux.safetensors"
    model_path.parent.mkdir(parents=True, exist_ok=True)

    # Create 4MB stub file with deterministic content
    with open(model_path, 'wb') as f:
        f.write(b'SAFETENSORS_HEADER' * (4 * 1024 * 1024 // 18))

    # Index the model (simulating user already has it locally)
    test_workspace.sync_model_directory()

    # Get the hash from index
    all_models = test_workspace.model_repository.get_all_models()
    model = next(m for m in all_models if m.filename == "flux.safetensors")
    model_hash = model.hash

    # Verify model has no sources initially
    sources = test_workspace.model_repository.get_sources(model_hash)
    assert len(sources) == 0, "Model should have no sources initially"

    # Simulate git pull: pyproject now has source URL for this model (from teammate)
    config = test_env.pyproject.load()
    if "models" not in config["tool"]["comfygit"]:
        config["tool"]["comfygit"]["models"] = {}

    config["tool"]["comfygit"]["models"][model_hash] = {
        "filename": "flux.safetensors",
        "hash": model_hash,
        "size": 4 * 1024 * 1024,  # 4MB
        "relative_path": "checkpoints/flux.safetensors",
        "category": "checkpoints",
        "sources": ["https://huggingface.co/flux/model/resolve/main/flux.safetensors"]
    }
    test_env.pyproject.save(config)

    # Add a workflow that uses this model (reload config to get fresh tomlkit document)
    config = test_env.pyproject.load()
    if "workflows" not in config["tool"]["comfygit"]:
        config["tool"]["comfygit"]["workflows"] = {}
    config["tool"]["comfygit"]["workflows"] = {
        "test_workflow": {
            "models": [
                {
                    "filename": "flux.safetensors",
                    "hash": model_hash,
                    "status": "resolved",
                    "criticality": "flexible",
                    "category": "checkpoints",
                    "nodes": [
                        {
                            "node_id": "1",
                            "node_type": "CheckpointLoaderSimple",
                            "widget_idx": 0,
                            "widget_value": "flux.safetensors"
                        }
                    ]
                }
            ]
        }
    }
    test_env.pyproject.save(config)

    # ACT: Run prepare_import_with_model_strategy (called by repair)
    test_env.model_manager.prepare_import_with_model_strategy(strategy="all")

    # ASSERT: Source URL should now be in SQLite index
    sources_after = test_workspace.model_repository.get_sources(model_hash)
    assert len(sources_after) == 1, "Model should have source URL in index"
    assert sources_after[0]["url"] == "https://huggingface.co/flux/model/resolve/main/flux.safetensors"


def test_repair_skips_download_intent_for_existing_models(test_env, test_workspace):
    """Repair should not create download intents for models that exist locally."""
    # ARRANGE: Model exists locally and in pyproject
    models_dir = test_workspace.workspace_config_manager.get_models_directory()
    model_path = models_dir / "checkpoints" / "existing.safetensors"
    model_path.parent.mkdir(parents=True, exist_ok=True)

    with open(model_path, 'wb') as f:
        f.write(b'MODEL_DATA' * (4 * 1024 * 1024 // 10))

    # Index the model
    test_workspace.sync_model_directory()

    all_models = test_workspace.model_repository.get_all_models()
    model = next(m for m in all_models if m.filename == "existing.safetensors")
    model_hash = model.hash

    # Add to pyproject (simulating git pull)
    config = test_env.pyproject.load()
    config["tool"]["comfygit"]["models"] = {
        model_hash: {
            "filename": "existing.safetensors",
            "hash": model_hash,
            "relative_path": "checkpoints/existing.safetensors",
            "category": "checkpoints",
            "sources": ["https://example.com/model.safetensors"]
        }
    }
    config["tool"]["comfygit"]["workflows"] = {
        "test_workflow": {
            "models": [
                {
                    "filename": "existing.safetensors",
                    "hash": model_hash,
                    "status": "resolved",
                    "criticality": "flexible",
                    "category": "checkpoints",
                    "nodes": [
                        {
                            "node_id": "1",
                            "node_type": "CheckpointLoaderSimple",
                            "widget_idx": 0,
                            "widget_value": "existing.safetensors"
                        }
                    ]
                }
            ]
        }
    }
    test_env.pyproject.save(config)

    # ACT: Run prepare_import_with_model_strategy
    workflows_with_intents = test_env.model_manager.prepare_import_with_model_strategy(strategy="all")

    # ASSERT: No download intents should be created
    assert len(workflows_with_intents) == 0, "No workflows should have download intents"

    # Verify model stayed resolved in pyproject
    workflow_models = test_env.pyproject.workflows.get_workflow_models("test_workflow")
    assert workflow_models[0].status == "resolved"
    assert workflow_models[0].hash == model_hash


def test_repair_creates_download_intent_for_missing_models(test_env):
    """Repair should create download intents for models with sources that don't exist locally."""
    # ARRANGE: Model in pyproject but not locally
    fake_hash = "abc123def456"
    config = test_env.pyproject.load()
    config["tool"]["comfygit"]["models"] = {
        fake_hash: {
            "filename": "missing.safetensors",
            "hash": fake_hash,
            "size": 4 * 1024 * 1024,  # 4MB
            "relative_path": "checkpoints/missing.safetensors",
            "category": "checkpoints",
            "sources": ["https://example.com/missing.safetensors"]
        }
    }
    config["tool"]["comfygit"]["workflows"] = {
        "test_workflow": {
            "models": [
                {
                    "filename": "missing.safetensors",
                    "hash": fake_hash,
                    "status": "resolved",
                    "criticality": "flexible",
                    "category": "checkpoints",
                    "nodes": [
                        {
                            "node_id": "1",
                            "node_type": "CheckpointLoaderSimple",
                            "widget_idx": 0,
                            "widget_value": "missing.safetensors"
                        }
                    ]
                }
            ]
        }
    }
    test_env.pyproject.save(config)

    # ACT: Run prepare_import_with_model_strategy
    workflows_with_intents = test_env.model_manager.prepare_import_with_model_strategy(strategy="all")

    # ASSERT: Download intent should be created
    assert len(workflows_with_intents) == 1
    assert "test_workflow" in workflows_with_intents

    # Verify model became download intent in pyproject
    workflow_models = test_env.pyproject.workflows.get_workflow_models("test_workflow")
    assert workflow_models[0].status == "unresolved"
    assert workflow_models[0].hash is None
    assert workflow_models[0].sources == ["https://example.com/missing.safetensors"]
