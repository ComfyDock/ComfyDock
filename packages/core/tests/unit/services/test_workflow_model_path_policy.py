from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import Mock

from comfygit_core.models.shared import ModelWithLocation
from comfygit_core.models.workflow import ResolvedModel, WorkflowNodeWidgetRef
from comfygit_core.services.workflow_file_store import WorkflowFileStore
from comfygit_core.services.workflow_model_path_policy import WorkflowModelPathPolicy


@dataclass
class FakeModelConfig:
    mappings: dict[str, list[str]] = field(default_factory=dict)

    def get_directories_for_node(self, node_type: str) -> list[str]:
        return self.mappings.get(node_type, [])

    def is_model_loader_node(self, node_type: str) -> bool:
        return node_type in self.mappings

    def reconstruct_model_path(self, node_type: str, widget_value: str) -> list[str]:
        return [
            f"{directory}/{widget_value}"
            for directory in self.get_directories_for_node(node_type)
        ]


class FakeModelRepository:
    def __init__(self, models: list[ModelWithLocation]) -> None:
        self.models = models

    def get_all_models(self) -> list[ModelWithLocation]:
        return self.models

    def get_locations(self, model_hash: str) -> list[dict]:
        return [
            {
                "model_hash": model.hash,
                "relative_path": model.relative_path,
            }
            for model in self.models
            if model.hash == model_hash
        ]


def make_model(hash_value: str, relative_path: str) -> ModelWithLocation:
    return ModelWithLocation(
        hash=hash_value,
        file_size=100,
        relative_path=relative_path,
        filename=relative_path.rsplit("/", 1)[-1],
        mtime=0,
        last_seen=0,
    )


def make_policy(tmp_path, models: list[ModelWithLocation]) -> WorkflowModelPathPolicy:
    file_store = WorkflowFileStore(
        tmp_path / "ComfyUI",
        tmp_path / ".cec",
        environment_name="test-env",
        workflow_cache=None,
    )
    return WorkflowModelPathPolicy(
        model_repository=FakeModelRepository(models),
        model_config=FakeModelConfig(
            {
                "CheckpointLoaderSimple": ["checkpoints"],
                "LoraLoader": ["loras"],
                "CLIPLoader": ["text_encoders", "clip"],
            }
        ),
        workflow_file_store=file_store,
        workflow_cache=Mock(),
        environment_name="test-env",
    )


def test_strip_base_directory_for_builtin_loader_preserves_subdirectories(tmp_path):
    policy = make_policy(tmp_path, [])

    result = policy.strip_base_directory_for_node(
        "CheckpointLoaderSimple",
        r"checkpoints\SD1.5\model.safetensors",
    )

    assert result == "SD1.5/model.safetensors"


def test_path_sync_ignores_duplicate_current_path_with_same_hash(tmp_path):
    model = make_model("same-hash", "loras/WAN/copy.safetensors")
    current_location = make_model("same-hash", "loras/original.safetensors")
    policy = make_policy(tmp_path, [model, current_location])
    resolved = ResolvedModel(
        workflow="test",
        reference=WorkflowNodeWidgetRef(
            node_id="1",
            node_type="LoraLoader",
            widget_index=0,
            widget_value="original.safetensors",
        ),
        resolved_model=model,
    )

    assert policy.path_needs_sync(resolved) is False


def test_category_mismatch_ignores_resolved_location_when_same_hash_has_valid_location(tmp_path):
    wrong_location = make_model("same-hash", "checkpoints/style_lora.safetensors")
    valid_location = make_model("same-hash", "loras/style_lora.safetensors")
    policy = make_policy(tmp_path, [wrong_location, valid_location])
    resolved = ResolvedModel(
        workflow="test",
        reference=WorkflowNodeWidgetRef(
            node_id="1",
            node_type="LoraLoader",
            widget_index=0,
            widget_value="style_lora.safetensors",
        ),
        resolved_model=wrong_location,
    )

    has_mismatch, expected, actual = policy.category_mismatch(resolved)

    assert has_mismatch is False
    assert expected == ["loras"]
    assert actual == "checkpoints"


def test_category_mismatch_flags_wrong_directory_without_valid_duplicate(tmp_path):
    wrong_location = make_model("same-hash", "checkpoints/style_lora.safetensors")
    policy = make_policy(tmp_path, [wrong_location])
    resolved = ResolvedModel(
        workflow="test",
        reference=WorkflowNodeWidgetRef(
            node_id="1",
            node_type="LoraLoader",
            widget_index=0,
            widget_value="style_lora.safetensors",
        ),
        resolved_model=wrong_location,
    )

    has_mismatch, expected, actual = policy.category_mismatch(resolved)

    assert has_mismatch is True
    assert expected == ["loras"]
    assert actual == "checkpoints"
