"""Integration test for model index show command."""

import tempfile
from pathlib import Path

import pytest
from comfygit_core.factories.workspace_factory import WorkspaceFactory


def test_get_model_details():
    """Test workspace.get_model_details() returns complete information."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Create workspace
        workspace = WorkspaceFactory.create(tmp_path / "workspace")

        # Setup models directory
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        workspace.set_models_directory(models_dir)

        # Create a test model file
        test_file = models_dir / "checkpoints" / "test.safetensors"
        test_file.parent.mkdir(parents=True)
        test_file.write_bytes(b"test" * 1000)

        # Sync to index
        workspace.sync_model_directory()

        # Get model hash
        models = workspace.list_models()
        assert len(models) == 1
        model_hash = models[0].hash

        # Add a source through the public workspace facade.
        source_type = workspace.add_indexed_model_source(
            model_hash=model_hash,
            source_url="https://civitai.com/api/download/models/12345",
        )
        assert source_type == "civitai"
        assert workspace.has_model(model_hash)
        assert workspace.model_has_sources(model_hash)

        # Test get_model_details using the new interface
        details = workspace.get_model_details(model_hash)

        # Verify structure
        assert details.model.hash == model_hash
        assert details.model.filename == "test.safetensors"
        assert details.model.relative_path == "checkpoints/test.safetensors"
        assert details.model.category == "checkpoints"
        # blake3_hash may be None (lazily computed)

        # Verify sources
        assert len(details.sources) == 1
        assert details.sources[0]['type'] == 'civitai'
        assert details.sources[0]['url'] == "https://civitai.com/api/download/models/12345"
        assert workspace.find_model_by_source_url("https://civitai.com/api/download/models/12345").hash == model_hash

        # Verify locations
        assert len(details.all_locations) == 1
        assert details.all_locations[0]['relative_path'] == "checkpoints/test.safetensors"
        assert details.all_locations[0]['filename'] == "test.safetensors"

        refreshed = workspace.ensure_model_hashes(model_hash)
        assert refreshed.model.blake3_hash
        assert refreshed.model.sha256_hash

        assert workspace.remove_indexed_model_source(
            model_hash,
            "https://civitai.com/api/download/models/12345",
        )
        assert not workspace.model_has_sources(model_hash)


def test_get_model_details_not_found():
    """Test get_model_details raises KeyError when model not found."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        workspace = WorkspaceFactory.create(tmp_path / "workspace")
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        workspace.set_models_directory(models_dir)

        with pytest.raises(KeyError):
            workspace.get_model_details("nonexistent")


def test_get_model_details_ambiguous():
    """Test get_model_details raises ValueError when multiple matches found."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        workspace = WorkspaceFactory.create(tmp_path / "workspace")
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        workspace.set_models_directory(models_dir)

        # Create two files with same name in different categories
        test_file1 = models_dir / "checkpoints" / "test.safetensors"
        test_file1.parent.mkdir(parents=True)
        test_file1.write_bytes(b"test1" * 1000)

        test_file2 = models_dir / "loras" / "test.safetensors"
        test_file2.parent.mkdir(parents=True)
        test_file2.write_bytes(b"test2" * 1000)

        workspace.sync_model_directory()

        # Searching by filename should raise ValueError
        with pytest.raises(ValueError, match="Multiple models found"):
            workspace.get_model_details("test.safetensors")
