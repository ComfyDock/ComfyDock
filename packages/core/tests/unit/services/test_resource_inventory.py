import os
from datetime import datetime
from pathlib import Path

import pytest
from comfygit_core.utils.environment_cleanup import mark_environment_complete


def _index_model(test_workspace, path: Path, *, source: bool = True) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"inventory-model-bytes")
    repository = test_workspace.model_repository
    relative_path = path.relative_to(test_workspace.get_models_directory()).as_posix()
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
        relative_path=relative_path,
        filename=path.name,
        mtime=path.stat().st_mtime,
    )
    if source:
        repository.add_source(
            model_hash,
            "huggingface",
            f"https://huggingface.co/example/model/resolve/main/{path.name}",
            metadata={
                "repo_id": "example/model",
                "repo_type": "model",
                "revision": "main",
                "resolved_revision": "c" * 40,
                "path_in_repo": path.name,
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

    lightweight = test_workspace.get_resource_inventory()
    assert lightweight.environments[0].storage.measured is False
    assert lightweight.environments[0].storage.input_bytes == 0

    inventory = test_workspace.get_resource_inventory(include_storage=True)

    assert inventory.workspace_path == str(test_workspace.path)
    assert inventory.workspace_id == test_workspace.get_workspace_id()
    assert datetime.fromisoformat(inventory.observed_at).tzinfo is not None
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
    assert model.sources[0].to_dict()["is_reproducible"] is True
    assert model.locations[0].observation_state == "present"
    assert model.locations[0].independently_usable is True

    assert len(inventory.environments) == 1
    environment = inventory.environments[0]
    assert environment.comfyui_revision == "test"
    assert len(environment.model_dependencies) == 1
    assert environment.model_dependencies[0].workflow_names == ("example",)
    assert environment.custom_node_dependencies[0].identifier == "example-node"
    assert environment.storage.input_bytes == len(b"reference")
    assert environment.storage.measured is True
    serialized = inventory.to_dict()
    assert serialized["schema_version"] == 2
    assert serialized["models"][0]["source_hint_available"] is True
    assert serialized["models"][0]["strong_hash_available"] is True
    assert serialized["models"][0]["immutable_source_available"] is True


def test_lightweight_inventory_does_not_walk_storage(test_workspace, test_env, monkeypatch):
    _declare_environment_model(test_env, "not-indexed")

    def fail_if_measured(_path):
        raise AssertionError("lightweight inventory must not measure directories")

    monkeypatch.setattr(
        "comfygit_core.services.resource_inventory._directory_size",
        fail_if_measured,
    )

    inventory = test_workspace.get_resource_inventory()

    assert inventory.environments[0].storage.measured is False


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


def test_moving_source_is_hint_but_not_complete_recovery(test_workspace):
    model_path = test_workspace.get_models_directory() / "checkpoints" / "moving.safetensors"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"moving")
    model_hash = test_workspace.model_repository.calculate_short_hash(model_path)
    test_workspace.model_repository.ensure_model(
        model_hash,
        model_path.stat().st_size,
        blake3_hash="b" * 64,
    )
    test_workspace.model_repository.add_location(
        model_hash,
        test_workspace.get_models_directory(),
        "checkpoints/moving.safetensors",
        model_path.name,
        model_path.stat().st_mtime,
    )
    source_url = "https://huggingface.co/example/model/resolve/main/moving.safetensors"
    test_workspace.model_repository.add_source(model_hash, "huggingface", source_url)
    location_id = test_workspace.get_model_locations(model_hash)[0].id
    assert location_id is not None

    moving_plan = test_workspace.plan_model_deletion(model_hash, location_id=location_id)
    assert moving_plan.source_hint_available is True
    assert moving_plan.strong_hash_available is True
    assert moving_plan.immutable_source_available is False
    assert moving_plan.recovery_complete is False
    assert "final_copy_lacks_recovery_proof" in moving_plan.blockers
    assert "huggingface_source_not_reproducible" in moving_plan.warnings

    test_workspace.model_repository.add_source(
        model_hash,
        "huggingface",
        source_url,
        metadata={"resolved_revision": "c" * 40},
    )
    immutable_plan = test_workspace.plan_model_deletion(model_hash, location_id=location_id)
    assert immutable_plan.immutable_source_available is True
    assert immutable_plan.recovery_complete is True


def test_inventory_redacts_source_credentials(test_workspace):
    model_path = test_workspace.get_models_directory() / "checkpoints" / "private.safetensors"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"private")
    model_hash = test_workspace.model_repository.calculate_short_hash(model_path)
    test_workspace.model_repository.ensure_model(model_hash, model_path.stat().st_size)
    test_workspace.model_repository.add_location(
        model_hash,
        test_workspace.get_models_directory(),
        "checkpoints/private.safetensors",
        model_path.name,
        model_path.stat().st_mtime,
    )
    test_workspace.model_repository.add_source(
        model_hash,
        "custom",
        "https://example.com/private.safetensors?token=secret-value",
        metadata={"access_token": "secret-value", "label": "safe"},
    )

    source = test_workspace.get_model_inventory()[0].sources[0]

    assert "secret-value" not in source.url
    assert source.metadata["access_token"] == "<redacted>"
    assert source.metadata["label"] == "safe"
    assert source.is_reproducible is False


def test_inventory_observes_missing_changed_and_dangling_locations(test_workspace):
    models_dir = test_workspace.get_models_directory()
    present_path = models_dir / "checkpoints" / "observed.safetensors"
    model_hash, _ = _index_model(test_workspace, present_path)
    missing_path = models_dir / "checkpoints" / "missing-alias.safetensors"
    test_workspace.model_repository.add_location(
        model_hash,
        models_dir,
        "checkpoints/missing-alias.safetensors",
        missing_path.name,
        present_path.stat().st_mtime,
    )
    dangling_path = models_dir / "checkpoints" / "dangling-alias.safetensors"
    dangling_path.symlink_to(models_dir / "checkpoints" / "not-there.safetensors")
    test_workspace.model_repository.add_location(
        model_hash,
        models_dir,
        "checkpoints/dangling-alias.safetensors",
        dangling_path.name,
        present_path.stat().st_mtime,
    )
    present_path.write_bytes(b"changed-size")
    os.utime(present_path, (present_path.stat().st_atime, present_path.stat().st_mtime + 5))

    locations = {
        location.filename: location
        for location in test_workspace.get_model_inventory()[0].locations
    }

    assert locations["observed.safetensors"].observation_state == "changed"
    assert locations["observed.safetensors"].present is True
    assert locations["observed.safetensors"].independently_usable is False
    assert locations["missing-alias.safetensors"].observation_state == "missing"
    assert locations["missing-alias.safetensors"].present is False
    assert locations["dangling-alias.safetensors"].observation_state == "dangling_symlink"
    assert locations["dangling-alias.safetensors"].is_symlink is True
    assert locations["dangling-alias.safetensors"].target_present is False


def test_remaining_symlink_to_selected_file_is_not_an_independent_copy(test_workspace):
    models_dir = test_workspace.get_models_directory()
    primary_path = models_dir / "checkpoints" / "target.safetensors"
    primary_path.parent.mkdir(parents=True, exist_ok=True)
    primary_path.write_bytes(b"target")
    model_hash = test_workspace.model_repository.calculate_short_hash(primary_path)
    test_workspace.model_repository.ensure_model(
        model_hash,
        primary_path.stat().st_size,
        blake3_hash="b" * 64,
    )
    test_workspace.model_repository.add_location(
        model_hash,
        models_dir,
        "checkpoints/target.safetensors",
        primary_path.name,
        primary_path.stat().st_mtime,
    )
    alias_path = models_dir / "checkpoints" / "target-alias.safetensors"
    alias_path.symlink_to(primary_path)
    test_workspace.model_repository.add_location(
        model_hash,
        models_dir,
        "checkpoints/target-alias.safetensors",
        alias_path.name,
        primary_path.stat().st_mtime,
    )
    test_workspace.model_repository.add_source(
        model_hash,
        "huggingface",
        "https://huggingface.co/example/model/resolve/main/target.safetensors",
    )
    primary_location = next(
        location
        for location in test_workspace.get_model_inventory()[0].locations
        if location.filename == "target.safetensors"
    )
    assert primary_location.id is not None

    plan = test_workspace.plan_model_deletion(
        model_hash,
        location_id=primary_location.id,
    )

    assert len(plan.remaining_locations) == 1
    assert plan.remaining_locations[0].is_symlink is True
    assert "remaining_index_contains_unusable_locations" in plan.warnings
    assert "final_copy_lacks_recovery_proof" in plan.blockers


def test_apply_rejects_file_changed_after_plan(test_workspace):
    model_path = test_workspace.get_models_directory() / "checkpoints" / "stale.safetensors"
    model_hash, location_id = _index_model(test_workspace, model_path)
    plan = test_workspace.plan_model_deletion(model_hash, location_id=location_id)
    model_path.write_bytes(b"changed-after-plan")
    os.utime(model_path, (model_path.stat().st_atime, model_path.stat().st_mtime + 5))

    with pytest.raises(ValueError, match="selected_location_changed"):
        test_workspace.apply_model_deletion_plan(plan)
    assert model_path.exists()
