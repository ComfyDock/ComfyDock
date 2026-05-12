from pathlib import Path


def _index_model(workspace, model_hash: str, base_dir: Path, relative_path: str, data: bytes = b"model"):
    model_path = base_dir / relative_path
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(data)

    workspace.model_repository.ensure_model(model_hash, len(data))
    workspace.model_repository.add_location(
        model_hash=model_hash,
        base_directory=base_dir,
        relative_path=relative_path,
        filename=Path(relative_path).name,
        mtime=model_path.stat().st_mtime,
    )
    return model_path


def test_delete_model_removes_all_locations_and_orphaned_sources(test_workspace, tmp_path):
    model_hash = "abc123def4567890"
    models_dir = test_workspace.get_models_directory()
    second_dir = tmp_path / "other-models"

    first_path = _index_model(test_workspace, model_hash, models_dir, "loras/model.safetensors")
    second_path = _index_model(test_workspace, model_hash, second_dir, "loras/model.safetensors")
    test_workspace.model_repository.add_source(model_hash, "custom", "https://example.com/model.safetensors")

    result = test_workspace.delete_model(model_hash)

    assert result.status == "success"
    assert sorted(result.deleted_paths) == sorted([str(first_path), str(second_path)])
    assert result.missing_paths == []
    assert result.errors == []
    assert result.remaining_locations == 0
    assert not first_path.exists()
    assert not second_path.exists()
    assert test_workspace.model_repository.get_model(model_hash) is None
    assert test_workspace.model_repository.get_sources(model_hash) == []


def test_delete_model_cleans_missing_locations(test_workspace):
    model_hash = "abc123def4567890"
    models_dir = test_workspace.get_models_directory()
    missing_path = models_dir / "vae" / "missing.safetensors"

    test_workspace.model_repository.ensure_model(model_hash, 128)
    test_workspace.model_repository.add_location(
        model_hash=model_hash,
        base_directory=models_dir,
        relative_path="vae/missing.safetensors",
        filename="missing.safetensors",
        mtime=1.0,
    )

    result = test_workspace.delete_model(model_hash)

    assert result.status == "success"
    assert result.deleted_paths == []
    assert result.missing_paths == [str(missing_path)]
    assert result.remaining_locations == 0
    assert test_workspace.model_repository.get_model(model_hash) is None


def test_delete_model_refuses_locations_outside_base_directory(test_workspace, tmp_path):
    model_hash = "abc123def4567890"
    models_dir = test_workspace.get_models_directory()
    outside_path = models_dir.parent / "outside.safetensors"
    outside_path.write_bytes(b"model")

    test_workspace.model_repository.ensure_model(model_hash, outside_path.stat().st_size)
    test_workspace.model_repository.add_location(
        model_hash=model_hash,
        base_directory=models_dir,
        relative_path="../outside.safetensors",
        filename="outside.safetensors",
        mtime=outside_path.stat().st_mtime,
    )

    result = test_workspace.delete_model(model_hash)

    assert result.status == "partial"
    assert result.deleted_paths == []
    assert result.missing_paths == []
    assert len(result.errors) == 1
    assert "Refusing to delete model outside indexed base directory" in result.errors[0]["error"]
    assert result.remaining_locations == 1
    assert outside_path.exists()
    assert test_workspace.model_repository.get_model(model_hash) is not None
