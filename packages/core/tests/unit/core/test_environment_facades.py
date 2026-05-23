"""Tests for Environment facade methods that hide manager internals from adapters."""

from __future__ import annotations

from unittest.mock import Mock

from comfygit_core.models import ManifestModel, ManifestWorkflowModel, ModelWithLocation


def test_runtime_config_facades_expose_manifest_and_torch_state(test_env):
    status = test_env.get_torch_backend_status()

    assert status.backend == "cu121"
    assert status.is_configured is True
    assert status.backend_file == test_env.cec_path / ".pytorch-backend"
    assert test_env.get_python_version() == "3.12"
    assert test_env.get_manifest_path() == test_env.pyproject.path
    assert test_env.load_manifest_config()["project"]["name"] == "comfygit-env-test-env"


def test_dependency_group_removal_facade_returns_typed_result(test_env):
    config = test_env.pyproject.load()
    config["dependency-groups"] = {
        "optional-cuda": ["sageattention>=1.0", "xformers"],
    }
    test_env.pyproject.save(config)

    result = test_env.remove_dependencies_from_group(
        "optional-cuda",
        ["sageattention", "missing-package"],
    )

    assert result.removed == ["sageattention"]
    assert result.skipped == ["missing-package"]
    assert result.to_dict() == {
        "removed": ["sageattention"],
        "skipped": ["missing-package"],
    }


def test_overlay_facades_create_and_activate_template(test_env):
    created = test_env.create_overlay_template("facade-test")

    assert created.created is True
    assert created.scope == "shared"
    assert created.path.exists()
    assert "[overlay]" in created.path.read_text(encoding="utf-8")

    overlays = {overlay.name: overlay for overlay in test_env.list_overlays()}
    assert overlays["facade-test"].is_active is False

    enabled = test_env.enable_overlay("facade-test")
    assert enabled.name == "facade-test"
    assert enabled.changed is True
    assert enabled.is_compatible is True

    enabled_again = test_env.enable_overlay("facade-test")
    assert enabled_again.changed is False

    disabled = test_env.disable_overlay("facade-test")
    assert disabled.changed is True


def test_workflow_manifest_facades_hide_pyproject_handlers(test_env):
    workflow_model = ManifestWorkflowModel(
        filename="film_net_fp16.safetensors",
        category="frame_interpolation",
        criticality="required",
        status="resolved",
        nodes=[],
        hash="abc12345",
        relative_path="frame_interpolation/film_net_fp16.safetensors",
        declared_by="manual",
    )
    manifest_model = ManifestModel(
        hash="abc12345",
        filename="film_net_fp16.safetensors",
        size=123,
        relative_path="frame_interpolation/film_net_fp16.safetensors",
        category="frame_interpolation",
        sources=["https://example.com/film_net_fp16.safetensors"],
    )

    test_env.add_manifest_model(manifest_model)
    test_env.set_workflow_manifest_models("flow", [workflow_model])
    test_env.set_workflow_custom_node_mapping("flow", "CustomLoader", "custom-node-pack")

    assert test_env.get_manifest_model("abc12345") == manifest_model
    assert test_env.get_workflow_manifest_models("flow") == (workflow_model,)
    assert dict(test_env.get_workflow_custom_node_map("flow")) == {
        "CustomLoader": "custom-node-pack"
    }

    removed = test_env.remove_workflow_custom_node_mapping("flow", "CustomLoader")
    assert removed is True
    assert dict(test_env.get_workflow_custom_node_map("flow")) == {}


def test_workflow_resolution_facades_delegate_to_workflow_manager(test_env, monkeypatch):
    workflow_manager = test_env.workflow_manager
    dependencies = Mock()
    resolution = Mock()
    fixed_resolution = Mock()
    node_strategy = Mock()
    model_strategy = Mock()

    analyze = Mock(return_value=(dependencies, resolution))
    resolve = Mock(return_value=resolution)
    fix = Mock(return_value=fixed_resolution)
    update_paths = Mock(return_value=2)
    search_models = Mock(return_value=["model-match"])

    monkeypatch.setattr(workflow_manager, "analyze_and_resolve_workflow", analyze)
    monkeypatch.setattr(workflow_manager, "resolve_workflow", resolve)
    monkeypatch.setattr(workflow_manager, "fix_resolution", fix)
    monkeypatch.setattr(workflow_manager, "update_workflow_model_paths", update_paths)
    monkeypatch.setattr(workflow_manager, "search_models", search_models)

    assert test_env.analyze_workflow_dependencies("flow") == (dependencies, resolution)
    assert test_env.resolve_workflow_dependencies(dependencies) is resolution
    assert test_env.fix_workflow_resolution(resolution, node_strategy, model_strategy) is fixed_resolution
    assert test_env.update_workflow_model_paths(resolution) == 2
    assert test_env.search_workflow_models("film", node_type="LoadFoo", limit=3) == ["model-match"]

    analyze.assert_called_once_with("flow")
    resolve.assert_called_once_with(dependencies)
    fix.assert_called_once_with(resolution, node_strategy, model_strategy)
    update_paths.assert_called_once_with(resolution)
    search_models.assert_called_once_with("film", "LoadFoo", 3)


def test_mark_workflow_model_download_resolved_updates_manifest_tables(test_env, monkeypatch):
    unresolved = ManifestWorkflowModel(
        filename="download-me.safetensors",
        category="checkpoints",
        criticality="required",
        status="unresolved",
        nodes=[],
        sources=["https://example.com/download-me.safetensors"],
        relative_path="checkpoints/download-me.safetensors",
    )
    indexed = ModelWithLocation(
        hash="def67890",
        file_size=456,
        relative_path="checkpoints/download-me.safetensors",
        filename="download-me.safetensors",
        mtime=0.0,
        last_seen=1,
    )

    test_env.set_workflow_manifest_models("flow", [unresolved])
    monkeypatch.setattr(test_env.workspace, "get_indexed_model", lambda model_hash: indexed)

    changed = test_env.mark_workflow_model_download_resolved(
        "flow",
        filename="download-me.safetensors",
        model_hash="def67890",
    )

    assert changed is True
    assert test_env.get_manifest_model("def67890") == ManifestModel(
        hash="def67890",
        filename="download-me.safetensors",
        size=456,
        relative_path="checkpoints/download-me.safetensors",
        category="checkpoints",
        sources=["https://example.com/download-me.safetensors"],
    )

    workflow_model = test_env.get_workflow_manifest_models("flow")[0]
    assert workflow_model.hash == "def67890"
    assert workflow_model.status == "resolved"
    assert workflow_model.sources == []
    assert workflow_model.relative_path is None
