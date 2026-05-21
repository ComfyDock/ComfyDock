"""Tests for ModelConfig dynamic loading with cec_path parameter."""
import json

from comfygit_core.configs.model_config import ModelConfig


class TestModelConfigCecPathLoading:
    """Tests for ModelConfig.load() with cec_path parameter."""

    def test_load_without_cec_path_uses_static_config(self):
        """Test that load() without cec_path uses the static COMFYUI_MODELS_CONFIG."""
        config = ModelConfig.load()

        # Should have standard static config properties
        assert config.version == "2024.1"
        assert "checkpoints" in config.standard_directories
        assert "loras" in config.standard_directories

        # Should have known model loader nodes
        assert "CheckpointLoaderSimple" in config.node_directory_mappings
        assert "LoraLoader" in config.node_directory_mappings
        assert "FrameInterpolationModelLoader" in config.node_directory_mappings
        assert "frame_interpolation" in config.standard_directories

    def test_load_with_cec_path_none_uses_static_config(self):
        """Test that load(cec_path=None) uses static config."""
        config = ModelConfig.load(cec_path=None)

        assert config.version == "2024.1"
        assert "CheckpointLoaderSimple" in config.node_directory_mappings

    def test_load_with_cec_path_loads_folder_mappings(self, tmp_path):
        """Test that load() with cec_path loads and merges folder mappings."""
        # Create .cec directory with folder_paths JSON
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        folder_paths_data = {
            "metadata": {
                "extraction_date": "2026-01-21T12:00:00",
                "comfyui_version": "v0.3.68",
            },
            "folder_mappings": {
                "text_encoders": ["text_encoders", "clip"],
                "diffusion_models": ["unet", "diffusion_models"],
            },
            "legacy_aliases": {
                "clip": "text_encoders",
                "unet": "diffusion_models",
            },
        }

        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        config = ModelConfig.load(cec_path=cec_path)

        # CLIPLoader should now accept both text_encoders and clip directories
        clip_dirs = config.get_directories_for_node("CLIPLoader")
        assert "text_encoders" in clip_dirs
        assert "clip" in clip_dirs

    def test_load_with_cec_path_loads_generated_model_loaders(self, tmp_path):
        """Test generated model loader metadata adds loader nodes and widgets."""
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        folder_paths_data = {
            "metadata": {},
            "folder_mappings": {
                "frame_interpolation": ["frame_interpolation"],
            },
            "legacy_aliases": {},
        }
        with open(cec_path / "comfyui_folder_paths.json", "w") as f:
            json.dump(folder_paths_data, f)

        model_loaders_data = {
            "metadata": {},
            "model_loaders": {
                "FrameInterpolationModelLoader": [
                    {
                        "widget_name": "model_name",
                        "widget_index": 0,
                        "directories": ["frame_interpolation"],
                        "source": "generated",
                    }
                ]
            },
        }
        with open(cec_path / "comfyui_model_loaders.json", "w") as f:
            json.dump(model_loaders_data, f)

        config = ModelConfig.load(cec_path=cec_path)

        assert config.is_model_loader_node("FrameInterpolationModelLoader")
        assert config.get_directories_for_node("FrameInterpolationModelLoader") == [
            "frame_interpolation",
        ]
        assert "frame_interpolation" in config.standard_directories

        widgets = config.get_model_loader_widgets("FrameInterpolationModelLoader")
        assert len(widgets) == 1
        assert widgets[0].widget_name == "model_name"
        assert widgets[0].widget_index == 0
        assert widgets[0].directories == ["frame_interpolation"]
        assert widgets[0].source == "generated"

    def test_load_expands_clip_loader_directories(self, tmp_path):
        """Test CLIPLoader gets ["text_encoders", "clip"] from merged config."""
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        folder_paths_data = {
            "metadata": {},
            "folder_mappings": {
                "text_encoders": ["text_encoders", "clip"],
            },
            "legacy_aliases": {},
        }

        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        config = ModelConfig.load(cec_path=cec_path)

        # CLIPLoader maps to ["clip"] in static config, and "clip" appears
        # in folder_mappings["text_encoders"], so it should expand
        clip_dirs = config.get_directories_for_node("CLIPLoader")
        assert set(clip_dirs) == {"text_encoders", "clip"}

    def test_load_expands_unet_loader_directories(self, tmp_path):
        """Test UNETLoader gets ["unet", "diffusion_models"] from merged config."""
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        folder_paths_data = {
            "metadata": {},
            "folder_mappings": {
                "diffusion_models": ["unet", "diffusion_models"],
            },
            "legacy_aliases": {},
        }

        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        config = ModelConfig.load(cec_path=cec_path)

        # UNETLoader maps to diffusion_models in static config,
        # which should now expand to include unet
        unet_dirs = config.get_directories_for_node("UNETLoader")
        assert "diffusion_models" in unet_dirs
        assert "unet" in unet_dirs

    def test_load_gracefully_handles_missing_folder_paths_json(self, tmp_path):
        """Test that load() falls back when comfyui_folder_paths.json is missing."""
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()
        # No folder_paths JSON file

        config = ModelConfig.load(cec_path=cec_path)

        # Should still work with static config
        assert "CheckpointLoaderSimple" in config.node_directory_mappings
        assert config.version == "2024.1"

    def test_load_gracefully_handles_invalid_json(self, tmp_path):
        """Test that load() falls back when JSON is invalid."""
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        folder_paths_file.write_text("not valid json {{{")

        config = ModelConfig.load(cec_path=cec_path)

        # Should still work with static config
        assert "CheckpointLoaderSimple" in config.node_directory_mappings
        assert config.version == "2024.1"

    def test_load_gracefully_handles_malformed_data(self, tmp_path):
        """Test that load() handles JSON with unexpected structure."""
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        # Valid JSON but not the expected structure
        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump({"unexpected_key": "value"}, f)

        config = ModelConfig.load(cec_path=cec_path)

        # Should still work (empty folder_mappings means no expansion)
        assert "CheckpointLoaderSimple" in config.node_directory_mappings

    def test_load_preserves_unmapped_directories(self, tmp_path):
        """Test that directories without mappings are preserved as-is."""
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        folder_paths_data = {
            "metadata": {},
            "folder_mappings": {
                "checkpoints": ["checkpoints"],  # No additional directories
            },
            "legacy_aliases": {},
        }

        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        config = ModelConfig.load(cec_path=cec_path)

        # CheckpointLoaderSimple should still map to checkpoints
        checkpoint_dirs = config.get_directories_for_node("CheckpointLoaderSimple")
        assert "checkpoints" in checkpoint_dirs

    def test_config_path_and_cec_path_can_be_used_together(self, tmp_path):
        """Test that explicit config_path and cec_path can work together."""
        # Create custom config
        config_file = tmp_path / "custom_config.json"
        custom_config = {
            "version": "custom",
            "default_extensions": [".safetensors"],
            "standard_directories": ["custom_dir"],
            "directory_overrides": {},
            "node_directory_mappings": {
                "CustomLoader": ["custom_dir"],
            },
            "node_widget_indices": {},
        }
        with open(config_file, "w") as f:
            json.dump(custom_config, f)

        # Create cec_path with folder mappings
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        folder_paths_data = {
            "metadata": {},
            "folder_mappings": {
                "custom_dir": ["custom_dir", "alt_dir"],
            },
            "legacy_aliases": {},
        }

        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        config = ModelConfig.load(config_path=config_file, cec_path=cec_path)

        # Should use custom config with expanded directories
        assert config.version == "custom"
        custom_dirs = config.get_directories_for_node("CustomLoader")
        assert "custom_dir" in custom_dirs
        assert "alt_dir" in custom_dirs


class TestModelConfigMergeFolderMappings:
    """Tests for the _merge_folder_mappings static method."""

    def test_merge_expands_directories(self):
        """Test that merge expands directory lists based on folder_mappings."""
        base_config = {
            "node_directory_mappings": {
                "CLIPLoader": ["text_encoders"],
                "UNETLoader": ["diffusion_models"],
            },
        }

        folder_data = {
            "folder_mappings": {
                "text_encoders": ["text_encoders", "clip"],
                "diffusion_models": ["unet", "diffusion_models"],
            },
            "legacy_aliases": {},
        }

        merged = ModelConfig._merge_folder_mappings(base_config, folder_data)

        assert set(merged["node_directory_mappings"]["CLIPLoader"]) == {
            "text_encoders",
            "clip",
        }
        assert set(merged["node_directory_mappings"]["UNETLoader"]) == {
            "unet",
            "diffusion_models",
        }

    def test_merge_preserves_unknown_directories(self):
        """Test that directories not in folder_mappings are kept as-is."""
        base_config = {
            "node_directory_mappings": {
                "LoraLoader": ["loras"],
            },
        }

        folder_data = {
            "folder_mappings": {
                # loras not included
            },
            "legacy_aliases": {},
        }

        merged = ModelConfig._merge_folder_mappings(base_config, folder_data)

        assert merged["node_directory_mappings"]["LoraLoader"] == ["loras"]

    def test_merge_handles_empty_folder_mappings(self):
        """Test merge with empty folder_mappings returns base config unchanged."""
        base_config = {
            "node_directory_mappings": {
                "CLIPLoader": ["text_encoders"],
            },
            "other_key": "preserved",
        }

        folder_data = {
            "folder_mappings": {},
            "legacy_aliases": {},
        }

        merged = ModelConfig._merge_folder_mappings(base_config, folder_data)

        assert merged["node_directory_mappings"]["CLIPLoader"] == ["text_encoders"]
        assert merged["other_key"] == "preserved"

    def test_merge_does_not_modify_original_config(self):
        """Test that merge doesn't mutate the original base_config."""
        base_config = {
            "node_directory_mappings": {
                "CLIPLoader": ["text_encoders"],
            },
        }

        folder_data = {
            "folder_mappings": {
                "text_encoders": ["text_encoders", "clip"],
            },
            "legacy_aliases": {},
        }

        original_dirs = base_config["node_directory_mappings"]["CLIPLoader"].copy()
        merged = ModelConfig._merge_folder_mappings(base_config, folder_data)

        # Original should be unchanged
        assert base_config["node_directory_mappings"]["CLIPLoader"] == original_dirs
        # Merged should be expanded
        assert set(merged["node_directory_mappings"]["CLIPLoader"]) == {
            "text_encoders",
            "clip",
        }


class TestModelConfigReconstructModelPath:
    """Tests for ModelConfig.reconstruct_model_path() with equivalent directories."""

    def test_reconstruct_model_path_with_static_config(self):
        """Test reconstruct_model_path without dynamic config uses static mappings."""
        config = ModelConfig.load()

        # CLIPLoader maps to ["clip"] in static config
        paths = config.reconstruct_model_path("CLIPLoader", "model.safetensors")
        assert paths == ["clip/model.safetensors"]

    def test_reconstruct_model_path_clip_loader_with_dynamic_config(self, tmp_path):
        """Test CLIPLoader reconstruct_model_path returns both text_encoders and clip paths."""
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        folder_paths_data = {
            "metadata": {},
            "folder_mappings": {
                "text_encoders": ["text_encoders", "clip"],
            },
            "legacy_aliases": {},
        }

        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        config = ModelConfig.load(cec_path=cec_path)

        # Should return paths for BOTH equivalent directories
        paths = config.reconstruct_model_path("CLIPLoader", "model.safetensors")
        assert set(paths) == {
            "text_encoders/model.safetensors",
            "clip/model.safetensors",
        }

    def test_reconstruct_model_path_unet_loader_with_dynamic_config(self, tmp_path):
        """Test UNETLoader reconstruct_model_path returns both unet and diffusion_models paths."""
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        folder_paths_data = {
            "metadata": {},
            "folder_mappings": {
                "diffusion_models": ["unet", "diffusion_models"],
            },
            "legacy_aliases": {},
        }

        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        config = ModelConfig.load(cec_path=cec_path)

        # Should return paths for BOTH equivalent directories
        paths = config.reconstruct_model_path("UNETLoader", "flux_dev.safetensors")
        assert set(paths) == {
            "unet/flux_dev.safetensors",
            "diffusion_models/flux_dev.safetensors",
        }

    def test_reconstruct_model_path_with_subdirectories(self, tmp_path):
        """Test reconstruct_model_path handles widget values with subdirectories."""
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        folder_paths_data = {
            "metadata": {},
            "folder_mappings": {
                "text_encoders": ["text_encoders", "clip"],
            },
            "legacy_aliases": {},
        }

        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        config = ModelConfig.load(cec_path=cec_path)

        # Widget value can contain subdirectories
        paths = config.reconstruct_model_path("CLIPLoader", "sd3/clip_l.safetensors")
        assert set(paths) == {
            "text_encoders/sd3/clip_l.safetensors",
            "clip/sd3/clip_l.safetensors",
        }

    def test_reconstruct_model_path_unknown_node_type(self):
        """Test reconstruct_model_path returns empty list for unknown node types."""
        config = ModelConfig.load()

        paths = config.reconstruct_model_path("UnknownNode", "model.safetensors")
        assert paths == []

    def test_reconstruct_model_path_preserves_order(self, tmp_path):
        """Test that reconstruct_model_path returns paths in a consistent manner."""
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        folder_paths_data = {
            "metadata": {},
            "folder_mappings": {
                "text_encoders": ["text_encoders", "clip"],
            },
            "legacy_aliases": {},
        }

        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        config = ModelConfig.load(cec_path=cec_path)

        # Call multiple times to ensure consistency
        paths1 = config.reconstruct_model_path("CLIPLoader", "model.safetensors")
        paths2 = config.reconstruct_model_path("CLIPLoader", "model.safetensors")

        # Should return the same paths in the same order
        assert paths1 == paths2
        # Should have both paths
        assert len(paths1) == 2
