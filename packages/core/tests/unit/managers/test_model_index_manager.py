"""Unit tests for ModelIndexManager."""

import time
from comfygit_core.repositories.model_repository import ModelRepository


def test_add_and_find_models(tmp_path):
    """Test adding models and finding by hash and filename."""
    db_path = tmp_path / "test_models.db"
    base_path = tmp_path / "models"
    base_path.mkdir()
    index_mgr = ModelRepository(db_path, current_directory=base_path)

    # Model info to use for testing (but we'll add directly to index)

    # Add models to index with locations
    model1_path = "checkpoints/test_model.safetensors"
    model2_path = "loras/another_model.ckpt"

    # Create actual files for testing
    (base_path / "checkpoints").mkdir()
    (base_path / "loras").mkdir()
    (base_path / model1_path).write_bytes(b"test" * 256000)  # Create dummy content
    (base_path / model2_path).write_bytes(b"test" * 512000)  # Create dummy content

    # Ensure models exist in the index
    index_mgr.ensure_model("abc123def456", 1024000, blake3_hash="abc123def456")
    index_mgr.ensure_model("xyz789uvw012", 2048000, blake3_hash="xyz789uvw012")

    # Add locations for the models
    index_mgr.add_location("abc123def456", base_path, model1_path, "test_model.safetensors", time.time())
    index_mgr.add_location("xyz789uvw012", base_path, model2_path, "another_model.ckpt", time.time())

    # Find by hash prefix
    results = index_mgr.find_model_by_hash("abc123")
    assert len(results) == 1
    assert results[0].hash == "abc123def456"
    assert results[0].filename == "test_model.safetensors"

    # Find by filename (exact match)
    filename_results = index_mgr.find_by_filename("test_model.safetensors")
    assert len(filename_results) == 1
    assert filename_results[0].hash == "abc123def456"

    # Get all models
    all_models = index_mgr.get_all_models()
    assert len(all_models) == 2


def test_models_by_path_and_stats(tmp_path):
    """Test filtering models by path pattern and getting statistics."""
    db_path = tmp_path / "test_types.db"
    base_path = tmp_path / "models"
    base_path.mkdir()
    index_mgr = ModelRepository(db_path, current_directory=base_path)

    # Add models in different directories
    models_data = [
        ("hash1", "checkpoints/model1.safetensors", "model1.safetensors", 1000000),
        ("hash2", "checkpoints/model2.safetensors", "model2.safetensors", 1500000),
        ("hash3", "loras/lora1.safetensors", "lora1.safetensors", 500000),
        ("hash4", "vae/vae1.safetensors", "vae1.safetensors", 800000),
    ]

    for hash_val, rel_path, filename, size in models_data:
        index_mgr.ensure_model(hash_val, size, blake3_hash=hash_val)
        index_mgr.add_location(hash_val, base_path, rel_path, filename, time.time())

    # Get all models and filter by path
    all_locations = index_mgr.get_all_locations()

    checkpoint_models = [loc for loc in all_locations if "checkpoints/" in loc['relative_path']]
    assert len(checkpoint_models) == 2

    lora_models = [loc for loc in all_locations if "loras/" in loc['relative_path']]
    assert len(lora_models) == 1
    assert lora_models[0]['filename'] == "lora1.safetensors"

    vae_models = [loc for loc in all_locations if "vae/" in loc['relative_path']]
    assert len(vae_models) == 1

    # Get statistics
    stats = index_mgr.get_stats()
    assert stats['total_models'] == 4
    assert stats['total_locations'] == 4


def test_update_and_remove_models(tmp_path):
    """Test updating model locations and removing models."""
    db_path = tmp_path / "test_updates.db"
    base_path = tmp_path / "models"
    base_path.mkdir()
    index_mgr = ModelRepository(db_path, current_directory=base_path)

    # Add a model
    original_path = "original/update_test.safetensors"
    index_mgr.ensure_model("update_test_hash", 1024, blake3_hash="update_test_hash")
    index_mgr.add_location("update_test_hash", base_path, original_path, "update_test.safetensors", time.time())

    # Verify it was added
    results = index_mgr.find_model_by_hash("update_test_hash")
    assert len(results) == 1
    assert results[0].relative_path == original_path

    # Update the path (add the model at a new location)
    new_path = "moved/update_test.safetensors"
    index_mgr.add_location("update_test_hash", base_path, new_path, "update_test.safetensors", time.time())

    # Verify we now have the model at the new location
    updated_results = index_mgr.find_model_by_hash("update_test_hash")
    # Should have both locations now
    assert any(r.relative_path == new_path for r in updated_results)

    # Remove the model location
    removed = index_mgr.remove_location(original_path)
    assert removed

    # Verify the location was removed
    location_results = index_mgr.get_all_locations()
    assert not any(loc['relative_path'] == original_path for loc in location_results)

    # Remove the remaining location
    index_mgr.remove_location(new_path)

    # Verify no locations remain (model still in database but no locations)
    removed_results = index_mgr.find_model_by_hash("update_test_hash")
    assert len(removed_results) == 0  # No locations means no results from find


def test_path_separator_normalization(tmp_path):
    """Test that Windows backslashes are normalized to forward slashes."""
    db_path = tmp_path / "test_separators.db"
    base_path = tmp_path / "models"
    base_path.mkdir()
    index_mgr = ModelRepository(db_path, current_directory=base_path)

    # Add model with Windows-style backslash path
    windows_path = r"checkpoints\v1-5-pruned.safetensors"
    index_mgr.ensure_model("win_hash", 2000000, blake3_hash="win_hash")
    index_mgr.add_location("win_hash", base_path, windows_path, "v1-5-pruned.safetensors", time.time())

    # Query should work with forward slashes (get_by_category uses forward slashes)
    checkpoints = index_mgr.get_by_category("checkpoints")
    assert len(checkpoints) == 1
    assert checkpoints[0].filename == "v1-5-pruned.safetensors"
    # Path stored in DB should be normalized to forward slashes
    assert "/" in checkpoints[0].relative_path
    assert "\\" not in checkpoints[0].relative_path

    # find_by_exact_path should work with either separator
    result_forward = index_mgr.find_by_exact_path("checkpoints/v1-5-pruned.safetensors")
    assert result_forward is not None
    assert result_forward.hash == "win_hash"

    result_backward = index_mgr.find_by_exact_path(r"checkpoints\v1-5-pruned.safetensors")
    assert result_backward is not None
    assert result_backward.hash == "win_hash"


def test_workflow_search_with_path_separators(tmp_path):
    """Test model search as used in workflow resolution with mixed separators."""
    db_path = tmp_path / "test_search.db"
    base_path = tmp_path / "models"
    base_path.mkdir()
    index_mgr = ModelRepository(db_path, current_directory=base_path)

    # Add several models with Windows paths (as they would be added on Windows)
    models = [
        ("hash1", r"checkpoints\v1-5-pruned-emaonly-fp16.safetensors", "v1-5-pruned-emaonly-fp16.safetensors"),
        ("hash2", r"checkpoints\sd15-inpainting.safetensors", "sd15-inpainting.safetensors"),
        ("hash3", r"loras\detail-tweaker.safetensors", "detail-tweaker.safetensors"),
    ]

    for hash_val, rel_path, filename in models:
        index_mgr.ensure_model(hash_val, 2000000, blake3_hash=hash_val)
        index_mgr.add_location(hash_val, base_path, rel_path, filename, time.time())

    # Simulate workflow_manager.search_models() behavior:
    # Get all checkpoints (this was failing before the fix)
    checkpoints = index_mgr.get_by_category("checkpoints")
    assert len(checkpoints) == 2, "Should find both checkpoint models"

    checkpoint_names = {m.filename for m in checkpoints}
    assert "v1-5-pruned-emaonly-fp16.safetensors" in checkpoint_names
    assert "sd15-inpainting.safetensors" in checkpoint_names

    # Get loras
    loras = index_mgr.get_by_category("loras")
    assert len(loras) == 1
    assert loras[0].filename == "detail-tweaker.safetensors"

    # Test search functionality
    search_results = index_mgr.search("v1-5")
    assert len(search_results) >= 1
    assert any("v1-5" in m.filename for m in search_results)
