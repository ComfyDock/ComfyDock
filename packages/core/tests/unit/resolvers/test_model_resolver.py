from unittest.mock import Mock

from comfygit_core.models.shared import ModelWithLocation
from comfygit_core.models.workflow import ModelResolutionContext, WorkflowNodeWidgetRef
from comfygit_core.resolvers.model_resolver import ModelResolver


def _make_model(model_hash: str, relative_path: str) -> ModelWithLocation:
    filename = relative_path.rsplit("/", 1)[-1]
    return ModelWithLocation(
        hash=model_hash,
        file_size=1,
        relative_path=relative_path,
        filename=filename,
        mtime=0.0,
        last_seen=0,
    )


class TestModelResolverPathNormalization:
    def test_resolves_exact_match_with_windows_backslashes(self):
        repo = Mock()
        model = _make_model("h1", "Z-Image/qwen_3_4b.safetensors")
        repo.get_all_models.return_value = [model]
        repo.find_by_filename.return_value = []

        resolver = ModelResolver(repo)
        ref = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="CustomLoader",
            widget_index=0,
            widget_value=r"Z-Image\qwen_3_4b.safetensors",
        )

        result = resolver.resolve_model(ref, ModelResolutionContext(workflow_name="wf"))

        assert result is not None
        assert len(result) == 1
        assert result[0].match_type == "exact"
        assert result[0].resolved_model == model

    def test_filename_match_uses_basename_for_windows_paths(self):
        repo = Mock()
        model = _make_model("h2", "checkpoints/qwen_3_4b.safetensors")
        repo.get_all_models.return_value = []
        repo.find_by_filename.return_value = [model]

        resolver = ModelResolver(repo)
        ref = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="CustomLoader",
            widget_index=0,
            widget_value=r"Z-Image\qwen_3_4b.safetensors",
        )

        result = resolver.resolve_model(ref, ModelResolutionContext(workflow_name="wf"))

        assert result is not None
        assert len(result) == 1
        assert result[0].match_type == "filename"
        assert result[0].resolved_model == model
        repo.find_by_filename.assert_called_once_with("qwen_3_4b.safetensors")

    def test_property_download_intent_target_path_strips_windows_prefix(self):
        repo = Mock()
        repo.get_all_models.return_value = []
        repo.find_by_filename.return_value = []

        resolver = ModelResolver(repo)
        ref = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="CustomLoader",
            widget_index=0,
            widget_value=r"Z-Image\qwen_3_4b.safetensors",
            property_url="https://example.com/qwen_3_4b.safetensors",
            property_directory="checkpoints",
        )

        result = resolver.resolve_model(ref, ModelResolutionContext(workflow_name="wf"))

        assert result is not None
        assert len(result) == 1
        assert result[0].match_type == "property_download_intent"
        assert result[0].resolved_model is None
        assert result[0].target_path is not None
        assert result[0].target_path.as_posix() == "checkpoints/qwen_3_4b.safetensors"
