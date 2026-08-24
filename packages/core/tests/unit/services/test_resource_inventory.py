from pathlib import Path

import pytest
from comfygit_core.utils.environment_cleanup import mark_environment_complete


def _index_model(test_workspace, path: Path, *, source: bool = True) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"inventory-model-bytes")
    repository = test_workspace.model_repository
    model_hash = repository.calculate_short_hash(path)
    repository.ensure_model(
        model_hash,
        path.stat().st_size,
        blake3_hash="b" * 64,
        sha256_hash="a" * 64,
    )
    repository.add_location(
        model_hash=model_hash,
        base_directory=test_workspace.get_models_directory(),
        relative_path="checkpoints/inventory.safetensors",
        filename=path.name,
        mtime=path.stat().st_mtime,
    )
    if source:
        repository.add_source(
            model_hash,
            "huggingface",
            "https://huggingface.co/example/model/resolve/main/inventory.safetensors",
            metadata={
                "repo_id": "example/model",
                "repo_type": "model",
                "revision": "main",
                "resolved_revision": "c" * 40,
                "path_in_repo": "inventory.safetensors",
            },
        )
    location = test_workspace.get_model_locations(model_hash)[0]
    assert location.id is not None
    return model_hash, location.id


def _declare_environment_model(test_env, model_hash: str) -> None:
    config = test_env.pyproject.load()
    comfygit = config["tool"]["comfygit"]
    comfygit["nodes"] = {
        "example-node": {
            "name": "example-node",
            "source": "git",
            "repository": "https://github.com/example/node.git",
            "version": "d" * 40,
            "criticality": "required",
        }
    }
    comfygit["models"] = {
        model_hash: {
            "filename": "inventory.safetensors",
            "size": 21,
            "relative_path": "checkpoints/inventory.safetensors",
            "category": "checkpoints",
            "sources": ["https://huggingface.co/example/model/resolve/main/inventory.safetensors"],
        }
    }
    comfygit["workflows"] = {
        "example": {
            "path": "workflows/example.json",
            "nodes": ["example-node"],
            "models": [
                {
                    "filename": "inventory.safetensors",
                    "category": "checkpoints",
                    "criticality": "required",
                    "status": "resolved",
                    "nodes": [],
                    "hash": model_hash,
                    "relative_path": "checkpoints/inventory.safetensors",
                }
            ],
        }
    }
    test_env.pyproject.save(config)
    mark_environment_complete(test_env.cec_path)


def test_inventory_reports_models_sources_environment_dependencies_and_storage(
    test_workspace,
    test_env,
):
    model_path = test_workspace.get_models_directory() / "checkpoints" / "inventory.safetensors"
    model_hash, _ = _index_model(test_workspace, model_path)
    _declare_environment_model(test_env, model_hash)
    input_path = test_workspace.paths.input / test_env.name / "reference.png"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_bytes(b"reference")

    inventory = test_workspace.get_resource_inventory()

    assert inventory.workspace_path == str(test_workspace.path)
    assert len(inventory.models) == 1
    model = inventory.models[0]
    assert model.short_hash == model_hash
    assert model.sha256_hash == "a" * 64
    assert model.referencing_environments == ("test-env",)
    assert model.sources[0].repo_id == "example/model"
    assert model.sources[0].revision == "main"
    assert model.sources[0].resolved_revision == "c" * 40
    assert model.sources[0].path_in_repo == "inventory.safetensors"
    assert model.sources[0].to_dict()["has_immutable_revision"] is True

    assert len(inventory.environments) == 1
    environment = inventory.environments[0]
    assert environment.comfyui_revision == "test"
    assert len(environment.model_dependencies) == 1
    assert environment.model_dependencies[0].workflow_names == ("example",)
    assert environment.custom_node_dependencies[0].identifier == "example-node"
    assert environment.storage.input_bytes == len(b"reference")
    serialized = inventory.to_dict()
    assert serialized["schema_version"] == 1
    assert serialized["models"][0]["has_recovery_source"] is True


def test_deletion_is_dry_run_by_default_and_location_specific(
    test_workspace,
    test_env,
):
    model_path = test_workspace.get_models_directory() / "checkpoints" / "inventory.safetensors"
    model_hash, location_id = _index_model(test_workspace, model_path)
    _declare_environment_model(test_env, model_hash)

    preview = test_workspace.plan_model_deletion(model_hash)
    assert preview.selection_explicit is False
    assert "explicit_location_selection_required" in preview.blockers
    assert "referenced_by_environments" in preview.blockers
    assert model_path.exists()

    plan = test_workspace.plan_model_deletion(model_hash, location_id=location_id)
    assert plan.selection_explicit is True
    assert plan.recovery_complete is True
    assert plan.can_apply is False

    result = test_workspace.apply_model_deletion_plan(plan, allow_referenced=True)
    assert result.deleted_paths == (str(model_path),)
    assert result.reference_override is True
    assert result.remaining_locations == 0
    assert not model_path.exists()


def test_location_specific_deletion_preserves_other_indexed_copy(
    test_workspace,
    test_env,
):
    models_dir = test_workspace.get_models_directory()
    primary_path = models_dir / "checkpoints" / "inventory.safetensors"
    model_hash, primary_location_id = _index_model(test_workspace, primary_path)
    _declare_environment_model(test_env, model_hash)
    alternate_dir = test_workspace.path / "alternate-models"
    alternate_path = alternate_dir / "checkpoints" / "inventory.safetensors"
    alternate_path.parent.mkdir(parents=True)
    alternate_path.write_bytes(primary_path.read_bytes())
    test_workspace.model_repository.add_location(
        model_hash,
        alternate_dir,
        "checkpoints/inventory.safetensors",
        alternate_path.name,
        alternate_path.stat().st_mtime,
    )

    plan = test_workspace.plan_model_deletion(
        model_hash,
        location_id=primary_location_id,
    )

    assert len(plan.target_locations) == 1
    assert len(plan.remaining_locations) == 1
    result = test_workspace.apply_model_deletion_plan(plan, allow_referenced=True)
    assert result.remaining_locations == 1
    assert not primary_path.exists()
    assert alternate_path.exists()
    assert test_workspace.get_indexed_model(model_hash) is None
    assert len(test_workspace.get_model_locations(model_hash)) == 1


def test_final_copy_without_source_or_strong_hash_is_blocked(test_workspace):
    model_path = test_workspace.get_models_directory() / "checkpoints" / "unsourced.safetensors"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"unsourced")
    model_hash = test_workspace.model_repository.calculate_short_hash(model_path)
    test_workspace.model_repository.ensure_model(model_hash, model_path.stat().st_size)
    test_workspace.model_repository.add_location(
        model_hash,
        test_workspace.get_models_directory(),
        "checkpoints/unsourced.safetensors",
        model_path.name,
        model_path.stat().st_mtime,
    )
    location_id = test_workspace.get_model_locations(model_hash)[0].id
    assert location_id is not None

    plan = test_workspace.plan_model_deletion(model_hash, location_id=location_id)
    assert "final_copy_lacks_recovery_proof" in plan.blockers
    with pytest.raises(ValueError, match="final_copy_lacks_recovery_proof"):
        test_workspace.apply_model_deletion_plan(plan)
    assert model_path.exists()


def test_deletion_plan_blocks_location_outside_indexed_base(test_workspace):
    models_dir = test_workspace.get_models_directory()
    outside_path = test_workspace.path / "outside.safetensors"
    outside_path.write_bytes(b"outside")
    model_hash = test_workspace.model_repository.calculate_short_hash(outside_path)
    test_workspace.model_repository.ensure_model(
        model_hash,
        outside_path.stat().st_size,
        blake3_hash="b" * 64,
    )
    test_workspace.model_repository.add_location(
        model_hash,
        models_dir,
        "../outside.safetensors",
        outside_path.name,
        outside_path.stat().st_mtime,
    )
    test_workspace.model_repository.add_source(
        model_hash,
        "custom",
        "https://example.com/outside.safetensors",
    )
    location_id = test_workspace.get_model_locations(model_hash)[0].id
    assert location_id is not None

    plan = test_workspace.plan_model_deletion(model_hash, location_id=location_id)

    assert "selected_location_outside_indexed_base" in plan.blockers
    with pytest.raises(ValueError, match="outside_indexed_base"):
        test_workspace.apply_model_deletion_plan(plan)
    assert outside_path.exists()
