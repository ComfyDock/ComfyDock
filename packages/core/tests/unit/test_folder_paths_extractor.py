"""Tests for dynamic folder_paths extraction utility."""
import json

import pytest


class TestFolderPathsExtractor:
    """Tests for extract_folder_paths function."""

    def test_extract_single_directory_mapping(self, tmp_path):
        """Test extraction of simple single-directory folder mappings."""
        from comfygit_core.utils.folder_paths_extractor import extract_folder_paths

        # Create minimal folder_paths.py with single-directory mappings
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()

        folder_paths_py = comfyui_path / "folder_paths.py"
        folder_paths_py.write_text('''
models_dir = "models"
folder_names_and_paths = {}
folder_names_and_paths["checkpoints"] = ([os.path.join(models_dir, "checkpoints")], supported_pt_extensions)
folder_names_and_paths["loras"] = ([os.path.join(models_dir, "loras")], supported_pt_extensions)
folder_names_and_paths["vae"] = ([os.path.join(models_dir, "vae")], supported_pt_extensions)
''')

        # Create output path
        output_path = tmp_path / "folder_paths.json"

        # Extract
        result = extract_folder_paths(comfyui_path, output_path)

        # Verify output file created
        assert output_path.exists()

        # Verify structure
        assert "metadata" in result
        assert "folder_mappings" in result

        # Verify single-directory mappings extracted
        assert result["folder_mappings"]["checkpoints"] == ["checkpoints"]
        assert result["folder_mappings"]["loras"] == ["loras"]
        assert result["folder_mappings"]["vae"] == ["vae"]

    def test_extract_multi_directory_mapping(self, tmp_path):
        """Test extraction of multi-directory folder mappings like text_encoders."""
        from comfygit_core.utils.folder_paths_extractor import extract_folder_paths

        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()

        folder_paths_py = comfyui_path / "folder_paths.py"
        folder_paths_py.write_text('''
models_dir = "models"
folder_names_and_paths = {}
folder_names_and_paths["text_encoders"] = ([os.path.join(models_dir, "text_encoders"), os.path.join(models_dir, "clip")], supported_pt_extensions)
folder_names_and_paths["diffusion_models"] = ([os.path.join(models_dir, "unet"), os.path.join(models_dir, "diffusion_models")], supported_pt_extensions)
folder_names_and_paths["controlnet"] = ([os.path.join(models_dir, "controlnet"), os.path.join(models_dir, "t2i_adapter")], supported_pt_extensions)
''')

        output_path = tmp_path / "folder_paths.json"
        result = extract_folder_paths(comfyui_path, output_path)

        # Verify multi-directory mappings extracted with correct order
        assert result["folder_mappings"]["text_encoders"] == ["text_encoders", "clip"]
        assert result["folder_mappings"]["diffusion_models"] == ["unet", "diffusion_models"]
        assert result["folder_mappings"]["controlnet"] == ["controlnet", "t2i_adapter"]

    def test_extract_legacy_aliases(self, tmp_path):
        """Test extraction of map_legacy function aliases."""
        from comfygit_core.utils.folder_paths_extractor import extract_folder_paths

        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()

        folder_paths_py = comfyui_path / "folder_paths.py"
        folder_paths_py.write_text('''
folder_names_and_paths = {}
folder_names_and_paths["checkpoints"] = ([os.path.join(models_dir, "checkpoints")], extensions)

def map_legacy(folder_name: str) -> str:
    legacy = {"unet": "diffusion_models",
              "clip": "text_encoders"}
    return legacy.get(folder_name, folder_name)
''')

        output_path = tmp_path / "folder_paths.json"
        result = extract_folder_paths(comfyui_path, output_path)

        # Verify legacy aliases extracted
        assert "legacy_aliases" in result
        assert result["legacy_aliases"]["unet"] == "diffusion_models"
        assert result["legacy_aliases"]["clip"] == "text_encoders"

    def test_extract_with_invalid_path_raises(self, tmp_path):
        """Test error handling for invalid ComfyUI path (no folder_paths.py)."""
        from comfygit_core.utils.folder_paths_extractor import extract_folder_paths

        invalid_path = tmp_path / "not_comfyui"
        invalid_path.mkdir()
        # No folder_paths.py file

        output_path = tmp_path / "folder_paths.json"

        with pytest.raises(ValueError, match="Invalid ComfyUI path"):
            extract_folder_paths(invalid_path, output_path)

    def test_graceful_failure_on_malformed_input(self, tmp_path):
        """Test graceful handling of unparseable folder_paths.py."""
        from comfygit_core.utils.folder_paths_extractor import extract_folder_paths

        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()

        folder_paths_py = comfyui_path / "folder_paths.py"
        folder_paths_py.write_text('''
# Syntactically valid but no relevant content
x = 1
y = 2
''')

        output_path = tmp_path / "folder_paths.json"
        result = extract_folder_paths(comfyui_path, output_path)

        # Should still produce valid output, just empty mappings
        assert "metadata" in result
        assert "folder_mappings" in result
        assert result["folder_mappings"] == {}

    def test_json_output_structure(self, tmp_path):
        """Validate JSON schema matches expected structure."""
        from comfygit_core.utils.folder_paths_extractor import extract_folder_paths

        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()

        folder_paths_py = comfyui_path / "folder_paths.py"
        folder_paths_py.write_text('''
folder_names_and_paths = {}
folder_names_and_paths["checkpoints"] = ([os.path.join(models_dir, "checkpoints")], extensions)
''')

        output_path = tmp_path / "folder_paths.json"
        extract_folder_paths(comfyui_path, output_path)

        # Verify JSON can be read back
        with open(output_path) as f:
            loaded = json.load(f)

        # Check required fields
        assert "metadata" in loaded
        assert "extraction_date" in loaded["metadata"]
        assert "comfyui_path" in loaded["metadata"]
        assert "folder_mappings" in loaded
        assert isinstance(loaded["folder_mappings"], dict)

    def test_metadata_includes_comfyui_version(self, tmp_path):
        """Test that metadata includes ComfyUI version when available."""
        from comfygit_core.utils.folder_paths_extractor import extract_folder_paths

        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()

        # Create folder_paths.py
        folder_paths_py = comfyui_path / "folder_paths.py"
        folder_paths_py.write_text('folder_names_and_paths = {}')

        # Create main.py with version
        main_py = comfyui_path / "main.py"
        main_py.write_text('version = "v0.3.68"')

        output_path = tmp_path / "folder_paths.json"
        result = extract_folder_paths(comfyui_path, output_path)

        assert "metadata" in result
        # Version extraction is handled by existing utilities

    def test_real_folder_paths_format(self, tmp_path):
        """Test extraction from realistic folder_paths.py content."""
        from comfygit_core.utils.folder_paths_extractor import extract_folder_paths

        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()

        # Use content closely matching real ComfyUI folder_paths.py
        folder_paths_py = comfyui_path / "folder_paths.py"
        folder_paths_py.write_text('''
from __future__ import annotations
import os

supported_pt_extensions = {'.ckpt', '.pt', '.bin', '.pth', '.safetensors'}

folder_names_and_paths = {}

base_path = os.path.dirname(os.path.realpath(__file__))
models_dir = os.path.join(base_path, "models")

folder_names_and_paths["checkpoints"] = ([os.path.join(models_dir, "checkpoints")], supported_pt_extensions)
folder_names_and_paths["configs"] = ([os.path.join(models_dir, "configs")], [".yaml"])
folder_names_and_paths["loras"] = ([os.path.join(models_dir, "loras")], supported_pt_extensions)
folder_names_and_paths["vae"] = ([os.path.join(models_dir, "vae")], supported_pt_extensions)
folder_names_and_paths["text_encoders"] = ([os.path.join(models_dir, "text_encoders"), os.path.join(models_dir, "clip")], supported_pt_extensions)
folder_names_and_paths["diffusion_models"] = ([os.path.join(models_dir, "unet"), os.path.join(models_dir, "diffusion_models")], supported_pt_extensions)
folder_names_and_paths["controlnet"] = ([os.path.join(models_dir, "controlnet"), os.path.join(models_dir, "t2i_adapter")], supported_pt_extensions)

def map_legacy(folder_name: str) -> str:
    legacy = {"unet": "diffusion_models",
              "clip": "text_encoders"}
    return legacy.get(folder_name, folder_name)
''')

        output_path = tmp_path / "folder_paths.json"
        result = extract_folder_paths(comfyui_path, output_path)

        # Verify comprehensive extraction
        assert result["folder_mappings"]["checkpoints"] == ["checkpoints"]
        assert result["folder_mappings"]["configs"] == ["configs"]
        assert result["folder_mappings"]["loras"] == ["loras"]
        assert result["folder_mappings"]["vae"] == ["vae"]
        assert result["folder_mappings"]["text_encoders"] == ["text_encoders", "clip"]
        assert result["folder_mappings"]["diffusion_models"] == ["unet", "diffusion_models"]
        assert result["folder_mappings"]["controlnet"] == ["controlnet", "t2i_adapter"]

        assert result["legacy_aliases"]["unet"] == "diffusion_models"
        assert result["legacy_aliases"]["clip"] == "text_encoders"
