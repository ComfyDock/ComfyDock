"""Integration tests for switching model directories with metadata preservation."""



class TestModelDirectorySwitch:
    """Test model index behavior when switching between different model directories."""

    def test_switching_directories_preserves_matching_models_and_clears_orphans(
        self, test_workspace
    ):
        """Test that switching directories preserves metadata for matching models.

        Scenario:
        1. Set initial directory with 3 models
        2. Add metadata (sources, sha256) to models
        3. Switch to new directory with 2 models (1 overlaps, 1 new)
        4. Verify:
           - Overlapping model keeps its metadata
           - New model is added fresh
           - Non-overlapping models from old dir are removed
           - Index only shows models in current directory

        This ensures users get accurate status and don't see phantom models.
        """
        # ARRANGE: Create first models directory with 3 models
        models_dir_1 = test_workspace.paths.root / "models_dir_1"
        models_dir_1.mkdir()

        # Create subdirectories
        (models_dir_1 / "checkpoints").mkdir()
        (models_dir_1 / "loras").mkdir()

        # Model 1: Will exist in both directories (same hash)
        shared_model = models_dir_1 / "checkpoints" / "shared_model.safetensors"
        shared_content = b"SHARED_MODEL" + b"\x00" * (4 * 1024 * 1024)
        shared_model.write_bytes(shared_content)

        # Model 2: Only in dir_1
        unique_1 = models_dir_1 / "checkpoints" / "unique_to_dir1.safetensors"
        unique_1_content = b"UNIQUE_DIR1" + b"\x00" * (4 * 1024 * 1024)
        unique_1.write_bytes(unique_1_content)

        # Model 3: Only in dir_1
        lora_1 = models_dir_1 / "loras" / "lora_only_dir1.safetensors"
        lora_1_content = b"LORA_DIR1" + b"\x00" * (2 * 1024 * 1024)
        lora_1.write_bytes(lora_1_content)

        # Set first directory and index
        test_workspace.set_models_directory(models_dir_1)

        # Verify initial state
        initial_stats = test_workspace.get_model_stats()
        assert initial_stats["total_models"] == 3, "Should have 3 unique models"
        assert initial_stats["total_locations"] == 3, "Should have 3 file locations"

        # Get hash of shared model for later verification
        shared_models = test_workspace.model_repository.find_by_filename("shared_model.safetensors")
        assert len(shared_models) == 1
        shared_hash = shared_models[0].hash

        # Add metadata to shared model (simulating download info)
        test_workspace.model_repository.add_source(
            model_hash=shared_hash,
            source_type="civitai",
            source_url="https://civitai.com/api/download/models/12345",
            metadata={"model_id": 12345, "version_id": 67890}
        )
        test_workspace.model_repository.update_sha256(
            hash=shared_hash,
            sha256_hash="a" * 64  # Mock SHA256
        )

        # Verify metadata was added
        sources_before = test_workspace.model_repository.get_sources(shared_hash)
        assert len(sources_before) == 1, "Should have 1 source"
        assert sources_before[0]["type"] == "civitai"

        model_before = test_workspace.model_repository.get_model(shared_hash)
        assert model_before.sha256_hash == "a" * 64

        # ACT: Create second directory with different models
        models_dir_2 = test_workspace.paths.root / "models_dir_2"
        models_dir_2.mkdir()
        (models_dir_2 / "checkpoints").mkdir()
        (models_dir_2 / "loras").mkdir()

        # Copy shared model (same content = same hash)
        shared_model_2 = models_dir_2 / "checkpoints" / "shared_model.safetensors"
        shared_model_2.write_bytes(shared_content)

        # New model only in dir_2
        unique_2 = models_dir_2 / "loras" / "unique_to_dir2.safetensors"
        unique_2_content = b"UNIQUE_DIR2" + b"\x00" * (3 * 1024 * 1024)
        unique_2.write_bytes(unique_2_content)

        # Switch to second directory
        test_workspace.set_models_directory(models_dir_2)

        # ASSERT: Verify index reflects new directory state
        final_stats = test_workspace.get_model_stats()
        assert final_stats["total_models"] == 2, (
            f"Should have exactly 2 models after switch. Got {final_stats['total_models']}. "
            "Orphaned models from old directory should be removed."
        )
        assert final_stats["total_locations"] == 2, (
            f"Should have exactly 2 file locations. Got {final_stats['total_locations']}"
        )

        # Verify shared model still exists with metadata preserved
        shared_models_after = test_workspace.model_repository.find_by_filename("shared_model.safetensors")
        assert len(shared_models_after) == 1, "Shared model should still exist"
        assert shared_models_after[0].hash == shared_hash, "Hash should be unchanged"

        # Verify metadata was preserved
        sources_after = test_workspace.model_repository.get_sources(shared_hash)
        assert len(sources_after) == 1, "Source metadata should be preserved"
        assert sources_after[0]["type"] == "civitai", "Source type should be preserved"
        assert sources_after[0]["metadata"]["model_id"] == 12345, "Source metadata should be intact"

        model_after = test_workspace.model_repository.get_model(shared_hash)
        assert model_after.sha256_hash == "a" * 64, "SHA256 hash should be preserved"

        # Verify location exists (relative_path doesn't contain absolute directory,
        # it's relative to the models directory base)
        assert shared_models_after[0].relative_path == "checkpoints/shared_model.safetensors", (
            "Location should be properly indexed"
        )

        # Verify new model exists
        unique_2_models = test_workspace.model_repository.find_by_filename("unique_to_dir2.safetensors")
        assert len(unique_2_models) == 1, "New model should be indexed"

        # Verify old unique models are gone
        unique_1_models = test_workspace.model_repository.find_by_filename("unique_to_dir1.safetensors")
        assert len(unique_1_models) == 0, (
            "Models from old directory should be removed from index"
        )

        lora_1_models = test_workspace.model_repository.find_by_filename("lora_only_dir1.safetensors")
        assert len(lora_1_models) == 0, (
            "Lora from old directory should be removed from index"
        )

    def test_switching_to_empty_directory_clears_index(self, test_workspace):
        """Test that switching to an empty directory clears the model index."""
        # ARRANGE: Create directory with models
        models_dir_1 = test_workspace.paths.root / "models_with_content"
        models_dir_1.mkdir()
        (models_dir_1 / "checkpoints").mkdir()

        model = models_dir_1 / "checkpoints" / "test_model.safetensors"
        model.write_bytes(b"TEST" + b"\x00" * (4 * 1024 * 1024))

        test_workspace.set_models_directory(models_dir_1)

        initial_stats = test_workspace.get_model_stats()
        assert initial_stats["total_models"] == 1

        # ACT: Switch to empty directory
        empty_dir = test_workspace.paths.root / "empty_models"
        empty_dir.mkdir()
        test_workspace.set_models_directory(empty_dir)

        # ASSERT: Index should be empty
        final_stats = test_workspace.get_model_stats()
        assert final_stats["total_models"] == 0, (
            "Index should be empty when switching to empty directory"
        )
        assert final_stats["total_locations"] == 0

    def test_switching_back_to_original_directory_rescans_correctly(self, test_workspace):
        """Test that switching back to a previous directory re-indexes correctly."""
        # ARRANGE: Create two directories
        dir_1 = test_workspace.paths.root / "dir_1"
        dir_1.mkdir()
        (dir_1 / "checkpoints").mkdir()

        model_1 = dir_1 / "checkpoints" / "model_in_dir1.safetensors"
        model_1_content = b"DIR1_MODEL" + b"\x00" * (4 * 1024 * 1024)
        model_1.write_bytes(model_1_content)

        dir_2 = test_workspace.paths.root / "dir_2"
        dir_2.mkdir()
        (dir_2 / "checkpoints").mkdir()

        model_2 = dir_2 / "checkpoints" / "model_in_dir2.safetensors"
        model_2.write_bytes(b"DIR2_MODEL" + b"\x00" * (4 * 1024 * 1024))

        # Set dir_1, then dir_2
        test_workspace.set_models_directory(dir_1)
        test_workspace.set_models_directory(dir_2)

        stats_dir2 = test_workspace.get_model_stats()
        assert stats_dir2["total_models"] == 1
        assert len(test_workspace.model_repository.find_by_filename("model_in_dir2.safetensors")) == 1
        assert len(test_workspace.model_repository.find_by_filename("model_in_dir1.safetensors")) == 0

        # ACT: Switch back to dir_1
        test_workspace.set_models_directory(dir_1)

        # ASSERT: Dir_1 model should be back
        final_stats = test_workspace.get_model_stats()
        assert final_stats["total_models"] == 1
        assert len(test_workspace.model_repository.find_by_filename("model_in_dir1.safetensors")) == 1
        assert len(test_workspace.model_repository.find_by_filename("model_in_dir2.safetensors")) == 0

    def test_metadata_preserved_when_switching_directories(self, test_workspace):
        """Verify that hashes and sources are preserved across directory switches."""
        # Create dir_1 with a model
        dir_1 = test_workspace.paths.root / "dir_1"
        dir_1.mkdir()
        (dir_1 / "checkpoints").mkdir()

        model_1 = dir_1 / "checkpoints" / "test_model.safetensors"
        model_content = b"TEST_MODEL" + b"\x00" * (4 * 1024 * 1024)
        model_1.write_bytes(model_content)

        # Index dir_1
        test_workspace.set_models_directory(dir_1)

        # Get model hash and add metadata
        models = test_workspace.model_repository.find_by_filename("test_model.safetensors")
        assert len(models) == 1
        original_hash = models[0].hash

        # Add source metadata
        test_workspace.model_repository.add_source(
            model_hash=original_hash,
            source_type="civitai",
            source_url="https://civitai.com/test",
            metadata={"model_id": 999}
        )

        # Create dir_2 (empty)
        dir_2 = test_workspace.paths.root / "dir_2"
        dir_2.mkdir()
        (dir_2 / "checkpoints").mkdir()

        # Switch to dir_2 (model no longer visible)
        test_workspace.set_models_directory(dir_2)
        stats = test_workspace.get_model_stats()
        assert stats["total_models"] == 0, "Dir 2 is empty, so no models should be visible"

        # Switch back to dir_1
        test_workspace.set_models_directory(dir_1)

        # Verify model appears again
        models_after = test_workspace.model_repository.find_by_filename("test_model.safetensors")
        assert len(models_after) == 1

        # KEY ASSERTION: Hash should be preserved (no re-hashing needed)
        assert models_after[0].hash == original_hash, (
            "Hash should be preserved from previous indexing, not recomputed"
        )

        # KEY ASSERTION: Source metadata should be preserved
        sources = test_workspace.model_repository.get_sources(original_hash)
        assert len(sources) == 1, "Source should be preserved"
        assert sources[0]["url"] == "https://civitai.com/test"
        assert sources[0]["type"] == "civitai"

    def test_hash_search_filters_by_current_directory(self, test_workspace):
        """Hash-based search should only return models in the current directory."""
        # Create two directories with different models
        dir_1 = test_workspace.paths.root / "dir_1"
        dir_1.mkdir()
        (dir_1 / "checkpoints").mkdir()

        model_1 = dir_1 / "checkpoints" / "model1.safetensors"
        model_1_content = b"MODEL1" + b"\x00" * (4 * 1024 * 1024)
        model_1.write_bytes(model_1_content)

        dir_2 = test_workspace.paths.root / "dir_2"
        dir_2.mkdir()
        (dir_2 / "checkpoints").mkdir()

        model_2 = dir_2 / "checkpoints" / "model2.safetensors"
        model_2_content = b"MODEL2" + b"\x00" * (4 * 1024 * 1024)
        model_2.write_bytes(model_2_content)

        # Index dir_1
        test_workspace.set_models_directory(dir_1)
        model_1_hash = test_workspace.model_repository.find_by_filename("model1.safetensors")[0].hash

        # Index dir_2
        test_workspace.set_models_directory(dir_2)
        model_2_hash = test_workspace.model_repository.find_by_filename("model2.safetensors")[0].hash

        # Search by hash should only find model2 (current directory)
        hash_results = test_workspace.search_models(model_2_hash[:8])
        assert len(hash_results) == 1
        assert hash_results[0].hash == model_2_hash

        # Searching for model1's hash should return nothing (wrong directory)
        hash_results_other = test_workspace.search_models(model_1_hash[:8])
        assert len(hash_results_other) == 0, "Should not find models from other directory"

    def test_same_model_in_multiple_directories_tracked_separately(self, test_workspace):
        """The same model file (same hash) should be trackable in multiple directories."""
        # Create two directories
        dir_1 = test_workspace.paths.root / "dir_1"
        dir_1.mkdir()
        (dir_1 / "checkpoints").mkdir()

        dir_2 = test_workspace.paths.root / "dir_2"
        dir_2.mkdir()
        (dir_2 / "checkpoints").mkdir()

        # Same content in both directories (same hash)
        shared_content = b"SHARED" + b"\x00" * (4 * 1024 * 1024)
        model_1 = dir_1 / "checkpoints" / "shared.safetensors"
        model_1.write_bytes(shared_content)

        model_2 = dir_2 / "checkpoints" / "shared.safetensors"
        model_2.write_bytes(shared_content)

        # Index dir_1
        test_workspace.set_models_directory(dir_1)
        model_hash = test_workspace.model_repository.find_by_filename("shared.safetensors")[0].hash

        # Index dir_2 (same model)
        test_workspace.set_models_directory(dir_2)

        # Should see 1 model in current directory
        stats = test_workspace.get_model_stats()
        assert stats["total_models"] == 1
        assert stats["total_locations"] == 1

        # But get_locations should show both locations
        all_locations = test_workspace.model_repository.get_locations(model_hash)
        assert len(all_locations) == 2, "Should track both locations for same model"

        # Verify both directory paths are present
        location_dirs = {loc['base_directory'] for loc in all_locations}
        assert str(dir_1.resolve()) in location_dirs
        assert str(dir_2.resolve()) in location_dirs
