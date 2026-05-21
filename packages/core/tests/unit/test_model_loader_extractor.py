"""Tests for generated ComfyUI model loader metadata extraction."""

from comfygit_core.utils.model_loader_extractor import extract_comfyui_model_loaders


class TestModelLoaderExtractor:
    """Tests for folder-backed model loader discovery."""

    def test_extracts_schema_style_combo_loader(self, tmp_path):
        comfyui_path = tmp_path / "ComfyUI"
        extras_path = comfyui_path / "comfy_extras"
        extras_path.mkdir(parents=True)
        (comfyui_path / "nodes.py").write_text("NODE_CLASS_MAPPINGS = {}\n", encoding="utf-8")
        (extras_path / "nodes_frame_interpolation.py").write_text(
            '''
import folder_paths
from comfy_api.latest import io

class FrameInterpolationModelLoader(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="FrameInterpolationModelLoader",
            inputs=[
                io.Combo.Input(
                    "model_name",
                    options=folder_paths.get_filename_list("frame_interpolation"),
                ),
            ],
        )
''',
            encoding="utf-8",
        )

        output_path = tmp_path / "comfyui_model_loaders.json"
        result = extract_comfyui_model_loaders(comfyui_path, output_path)

        assert output_path.exists()
        loader = result["model_loaders"]["FrameInterpolationModelLoader"][0]
        assert loader["widget_name"] == "model_name"
        assert loader["widget_index"] == 0
        assert loader["directories"] == ["frame_interpolation"]
        assert loader["source_file"] == "comfy_extras/nodes_frame_interpolation.py"

    def test_extracts_classic_input_types_loaders(self, tmp_path):
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        (comfyui_path / "nodes.py").write_text(
            '''
import folder_paths

class CheckpointLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "config_name": (folder_paths.get_filename_list("configs"),),
            "ckpt_name": (folder_paths.get_filename_list("checkpoints"),),
        }}

NODE_CLASS_MAPPINGS = {
    "CheckpointLoader": CheckpointLoader,
}
''',
            encoding="utf-8",
        )

        result = extract_comfyui_model_loaders(
            comfyui_path,
            tmp_path / "comfyui_model_loaders.json",
        )

        widgets = result["model_loaders"]["CheckpointLoader"]
        assert {widget["widget_name"] for widget in widgets} == {
            "config_name",
            "ckpt_name",
        }
        assert {tuple(widget["directories"]) for widget in widgets} == {
            ("configs",),
            ("checkpoints",),
        }
