"""Workflow cache invalidation for generated ComfyUI metadata.

These tests cover semantic inputs that affect dependency analysis and model
resolution while the workflow JSON file itself remains unchanged.
"""

import json

from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder

DYNAMIC_LOADER_NODE = "GeneratedDynamicModelLoader"
DYNAMIC_MODEL = "shared_dynamic_model.safetensors"


def _dynamic_loader_workflow() -> dict:
    return {
        "nodes": [
            {
                "id": "1",
                "type": DYNAMIC_LOADER_NODE,
                "pos": [100, 100],
                "size": [300, 100],
                "flags": {},
                "order": 0,
                "mode": 0,
                "inputs": [],
                "outputs": [],
                "properties": {},
                "widgets_values": [DYNAMIC_MODEL],
            }
        ],
        "links": [],
        "groups": [],
        "config": {},
        "extra": {},
        "version": 0.4,
    }


def _write_generated_metadata(env) -> None:
    (env.cec_path / "comfyui_builtins.json").write_text(
        json.dumps({
            "all_builtin_nodes": [DYNAMIC_LOADER_NODE],
            "metadata": {
                "comfyui_version": "test-generated",
                "total_nodes": 1,
            },
        })
    )
    (env.cec_path / "comfyui_folder_paths.json").write_text(
        json.dumps({
            "folder_mappings": {
                "dynamic_models": ["dynamic_models"],
                "other_models": ["other_models"],
            },
            "legacy_aliases": {},
            "metadata": {"total_folder_types": 2},
        })
    )
    (env.cec_path / "comfyui_model_loaders.json").write_text(
        json.dumps({
            "model_loaders": {
                DYNAMIC_LOADER_NODE: [
                    {
                        "widget_name": "model_name",
                        "widget_index": 0,
                        "directories": ["dynamic_models"],
                        "source": "generated",
                    }
                ]
            },
            "metadata": {"total_model_loaders": 1},
        })
    )


def test_analysis_cache_invalidates_when_generated_loader_metadata_changes(test_env):
    simulate_comfyui_save_workflow(test_env, "dynamic_loader", _dynamic_loader_workflow())

    deps1 = test_env.workflow_manager.analyze_workflow("dynamic_loader")
    assert deps1.found_models == []
    assert [node.type for node in deps1.non_builtin_nodes] == [DYNAMIC_LOADER_NODE]

    _write_generated_metadata(test_env)

    deps2 = test_env.workflow_manager.analyze_workflow("dynamic_loader")

    assert [ref.widget_value for ref in deps2.found_models] == [DYNAMIC_MODEL]
    assert [node.type for node in deps2.builtin_nodes] == [DYNAMIC_LOADER_NODE]
    assert deps2.non_builtin_nodes == []


def test_refresh_metadata_invalidates_cache_and_rebuilds_model_resolver(
    test_env,
    test_workspace,
    monkeypatch,
):
    simulate_comfyui_save_workflow(test_env, "dynamic_loader", _dynamic_loader_workflow())
    ModelIndexBuilder(test_workspace).add_model(
        filename=DYNAMIC_MODEL,
        relative_path="dynamic_models",
    ).add_model(
        filename=DYNAMIC_MODEL,
        relative_path="other_models",
    ).index_all()

    _deps1, resolution1 = test_env.workflow_manager.analyze_and_resolve_workflow("dynamic_loader")
    assert resolution1.models_resolved == []

    def fake_builtins(_comfyui_path, output_path):
        data = {
            "all_builtin_nodes": [DYNAMIC_LOADER_NODE],
            "metadata": {
                "comfyui_version": "test-generated",
                "total_nodes": 1,
            },
        }
        output_path.write_text(json.dumps(data))
        return data

    def fake_folder_paths(_comfyui_path, output_path):
        data = {
            "folder_mappings": {
                "dynamic_models": ["dynamic_models"],
                "other_models": ["other_models"],
            },
            "legacy_aliases": {},
            "metadata": {"total_folder_types": 2},
        }
        output_path.write_text(json.dumps(data))
        return data

    def fake_model_loaders(_comfyui_path, output_path):
        data = {
            "model_loaders": {
                DYNAMIC_LOADER_NODE: [
                    {
                        "widget_name": "model_name",
                        "widget_index": 0,
                        "directories": ["dynamic_models"],
                        "source": "generated",
                    }
                ]
            },
            "metadata": {"total_model_loaders": 1},
        }
        output_path.write_text(json.dumps(data))
        return data

    monkeypatch.setattr(
        "comfygit_core.utils.builtin_extractor.extract_comfyui_builtins",
        fake_builtins,
    )
    monkeypatch.setattr(
        "comfygit_core.utils.folder_paths_extractor.extract_folder_paths",
        fake_folder_paths,
    )
    monkeypatch.setattr(
        "comfygit_core.utils.model_loader_extractor.extract_comfyui_model_loaders",
        fake_model_loaders,
    )

    test_env.refresh_metadata()
    _deps2, resolution2 = test_env.workflow_manager.analyze_and_resolve_workflow("dynamic_loader")

    resolved_paths = [
        model.resolved_model.relative_path
        for model in resolution2.models_resolved
        if model.resolved_model is not None
    ]
    assert resolved_paths == [f"dynamic_models/{DYNAMIC_MODEL}"]
