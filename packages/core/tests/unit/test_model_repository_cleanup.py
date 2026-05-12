from pathlib import Path

from comfygit_core.repositories.model_repository import ModelRepository


def test_remove_location_by_id_and_clear_orphans(tmp_path: Path):
    repo = ModelRepository(tmp_path / "models.db")
    model_hash = "abc123def4567890"
    models_dir = tmp_path / "models"

    repo.ensure_model(model_hash, 128)
    repo.add_location(
        model_hash=model_hash,
        base_directory=models_dir,
        relative_path="loras/model.safetensors",
        filename="model.safetensors",
        mtime=1.0,
    )
    repo.add_source(model_hash, "custom", "https://example.com/model.safetensors")

    location = repo.get_locations(model_hash)[0]
    assert repo.remove_location_by_id(location["id"]) is True
    assert repo.get_locations(model_hash) == []

    assert repo.clear_orphaned_models() == 1
    assert repo.clear_orphaned_model_sources() == 1
    assert repo.get_model(model_hash) is None
    assert repo.get_sources(model_hash) == []


def test_remove_location_for_directory_does_not_remove_same_relative_path_elsewhere(tmp_path: Path):
    repo = ModelRepository(tmp_path / "models.db")
    model_hash = "abc123def4567890"
    first_dir = tmp_path / "models-a"
    second_dir = tmp_path / "models-b"

    repo.ensure_model(model_hash, 128)
    repo.add_location(model_hash, first_dir, "loras/model.safetensors", "model.safetensors", 1.0)
    repo.add_location(model_hash, second_dir, "loras/model.safetensors", "model.safetensors", 1.0)

    assert repo.remove_location_for_directory(first_dir, "loras/model.safetensors") is True

    locations = repo.get_locations(model_hash)
    assert len(locations) == 1
    assert locations[0]["base_directory"] == str(second_dir.resolve())
