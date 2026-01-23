"""Tests for WorkflowDependencyParser multi-model extraction."""
import pytest
from pathlib import Path
import json

from comfygit_core.analyzers.workflow_dependency_parser import WorkflowDependencyParser
from comfygit_core.models.workflow import Workflow, WorkflowNode, WorkflowNodeWidgetRef


class TestMultiModelExtraction:
    """Tests for multi-model widget extraction from DualCLIPLoader, TripleCLIPLoader, etc."""

    def _create_workflow_file(self, tmp_path: Path, nodes: list[dict]) -> Path:
        """Create a minimal workflow JSON file with given nodes."""
        workflow = {
            "nodes": nodes,
            "links": [],
            "groups": [],
            "version": 0.4
        }
        wf_path = tmp_path / "test_workflow.json"
        wf_path.write_text(json.dumps(workflow))
        return wf_path

    def test_dual_clip_loader_extracts_two_models(self, tmp_path):
        """DualCLIPLoader should extract both clip_name1 and clip_name2."""
        nodes = [{
            "id": 1,
            "type": "DualCLIPLoader",
            "widgets_values": ["clip1.safetensors", "clip2.safetensors", "flux", "default"]
        }]
        wf_path = self._create_workflow_file(tmp_path, nodes)

        parser = WorkflowDependencyParser(wf_path)
        deps = parser.analyze_dependencies()

        assert len(deps.found_models) == 2
        values = {m.widget_value for m in deps.found_models}
        assert values == {"clip1.safetensors", "clip2.safetensors"}

    def test_triple_clip_loader_extracts_three_models(self, tmp_path):
        """TripleCLIPLoader should extract all three clip models."""
        nodes = [{
            "id": 1,
            "type": "TripleCLIPLoader",
            "widgets_values": ["clip1.safetensors", "clip2.safetensors", "clip3.safetensors", "sd3"]
        }]
        wf_path = self._create_workflow_file(tmp_path, nodes)

        parser = WorkflowDependencyParser(wf_path)
        deps = parser.analyze_dependencies()

        assert len(deps.found_models) == 3
        values = {m.widget_value for m in deps.found_models}
        assert values == {"clip1.safetensors", "clip2.safetensors", "clip3.safetensors"}

    def test_quadruple_clip_loader_extracts_four_models(self, tmp_path):
        """QuadrupleCLIPLoader should extract all four clip models."""
        nodes = [{
            "id": 1,
            "type": "QuadrupleCLIPLoader",
            "widgets_values": [
                "clip1.safetensors", "clip2.safetensors",
                "clip3.safetensors", "clip4.safetensors", "type"
            ]
        }]
        wf_path = self._create_workflow_file(tmp_path, nodes)

        parser = WorkflowDependencyParser(wf_path)
        deps = parser.analyze_dependencies()

        assert len(deps.found_models) == 4
        values = {m.widget_value for m in deps.found_models}
        assert values == {
            "clip1.safetensors", "clip2.safetensors",
            "clip3.safetensors", "clip4.safetensors"
        }

    def test_checkpoint_loader_extracts_both_checkpoint_and_config(self, tmp_path):
        """CheckpointLoader should extract both checkpoint and config file.

        Multi-model configs are explicit about which widgets contain models,
        so we trust them without extension filtering.
        """
        nodes = [{
            "id": 1,
            "type": "CheckpointLoader",
            "widgets_values": ["model.safetensors", "v1-inference.yaml"]
        }]
        wf_path = self._create_workflow_file(tmp_path, nodes)

        parser = WorkflowDependencyParser(wf_path)
        deps = parser.analyze_dependencies()

        assert len(deps.found_models) == 2
        values = {m.widget_value for m in deps.found_models}
        assert values == {"model.safetensors", "v1-inference.yaml"}


class TestPropertiesModelsExtraction:
    """Tests for properties.models extraction with URL metadata."""

    def _create_workflow_file(self, tmp_path: Path, nodes: list[dict]) -> Path:
        """Create a minimal workflow JSON file with given nodes."""
        workflow = {
            "nodes": nodes,
            "links": [],
            "groups": [],
            "version": 0.4
        }
        wf_path = tmp_path / "test_workflow.json"
        wf_path.write_text(json.dumps(workflow))
        return wf_path

    def test_properties_models_extracts_url_metadata(self, tmp_path):
        """properties.models should extract URL and directory metadata."""
        nodes = [{
            "id": 1,
            "type": "DualCLIPLoader",
            "widgets_values": ["clip_l.safetensors", "t5xxl.safetensors", "flux"],
            "properties": {
                "models": [
                    {
                        "name": "clip_l.safetensors",
                        "url": "https://example.com/clip_l.safetensors",
                        "directory": "text_encoders"
                    },
                    {
                        "name": "t5xxl.safetensors",
                        "url": "https://example.com/t5xxl.safetensors",
                        "directory": "text_encoders"
                    }
                ]
            }
        }]
        wf_path = self._create_workflow_file(tmp_path, nodes)

        parser = WorkflowDependencyParser(wf_path)
        deps = parser.analyze_dependencies()

        assert len(deps.found_models) == 2

        # Find refs by value
        refs_by_value = {m.widget_value: m for m in deps.found_models}

        clip_ref = refs_by_value["clip_l.safetensors"]
        assert clip_ref.property_url == "https://example.com/clip_l.safetensors"
        assert clip_ref.property_directory == "text_encoders"

        t5_ref = refs_by_value["t5xxl.safetensors"]
        assert t5_ref.property_url == "https://example.com/t5xxl.safetensors"
        assert t5_ref.property_directory == "text_encoders"

    def test_properties_models_without_url(self, tmp_path):
        """properties.models without URL should still extract model refs."""
        nodes = [{
            "id": 1,
            "type": "CLIPLoader",
            "widgets_values": ["clip_l.safetensors"],
            "properties": {
                "models": [
                    {"name": "clip_l.safetensors", "directory": "clip"}
                ]
            }
        }]
        wf_path = self._create_workflow_file(tmp_path, nodes)

        parser = WorkflowDependencyParser(wf_path)
        deps = parser.analyze_dependencies()

        assert len(deps.found_models) == 1
        ref = deps.found_models[0]
        assert ref.widget_value == "clip_l.safetensors"
        assert ref.property_url is None
        assert ref.property_directory == "clip"

    def test_deduplication_prefers_property_metadata(self, tmp_path):
        """When both properties.models and widgets have same value, keep property metadata."""
        nodes = [{
            "id": 1,
            "type": "DualCLIPLoader",
            "widgets_values": ["clip_l.safetensors", "t5xxl.safetensors", "flux"],
            "properties": {
                "models": [
                    {
                        "name": "clip_l.safetensors",
                        "url": "https://example.com/clip_l.safetensors",
                        "directory": "text_encoders"
                    }
                    # Note: t5xxl is NOT in properties.models
                ]
            }
        }]
        wf_path = self._create_workflow_file(tmp_path, nodes)

        parser = WorkflowDependencyParser(wf_path)
        deps = parser.analyze_dependencies()

        assert len(deps.found_models) == 2

        refs_by_value = {m.widget_value: m for m in deps.found_models}

        # clip_l should have property metadata
        clip_ref = refs_by_value["clip_l.safetensors"]
        assert clip_ref.property_url == "https://example.com/clip_l.safetensors"

        # t5xxl should be extracted from widgets (no metadata)
        t5_ref = refs_by_value["t5xxl.safetensors"]
        assert t5_ref.property_url is None


class TestWorkflowNodeWidgetRefEquality:
    """Tests for WorkflowNodeWidgetRef hash/eq behavior with optional metadata."""

    def test_refs_equal_regardless_of_property_metadata(self):
        """Two refs with same core fields should be equal even with different metadata."""
        ref1 = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="DualCLIPLoader",
            widget_index=0,
            widget_value="clip.safetensors",
            property_url="https://example.com/clip.safetensors",
            property_directory="text_encoders"
        )
        ref2 = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="DualCLIPLoader",
            widget_index=0,
            widget_value="clip.safetensors",
            property_url=None,
            property_directory=None
        )

        assert ref1 == ref2
        assert hash(ref1) == hash(ref2)

    def test_refs_in_set_deduplicate_correctly(self):
        """Refs should deduplicate in sets based on core fields only."""
        ref1 = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="DualCLIPLoader",
            widget_index=0,
            widget_value="clip.safetensors",
            property_url="https://example.com/clip.safetensors"
        )
        ref2 = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="DualCLIPLoader",
            widget_index=0,
            widget_value="clip.safetensors"
        )

        ref_set = {ref1, ref2}
        assert len(ref_set) == 1


class TestWorkflowObjectInput:
    """Tests for WorkflowDependencyParser accepting Workflow object directly."""

    def test_workflow_object_input_with_name(self):
        """Parser should accept Workflow object and use provided name."""
        # Create workflow object directly (no file I/O)
        workflow = Workflow(
            nodes={
                "1": WorkflowNode(
                    id="1",
                    type="DualCLIPLoader",
                    widgets_values=["clip1.safetensors", "clip2.safetensors", "flux"]
                )
            }
        )

        parser = WorkflowDependencyParser(workflow, workflow_name="my_workflow")
        deps = parser.analyze_dependencies()

        assert deps.workflow_name == "my_workflow"
        assert len(deps.found_models) == 2
        values = {m.widget_value for m in deps.found_models}
        assert values == {"clip1.safetensors", "clip2.safetensors"}

    def test_workflow_object_input_defaults_to_unnamed(self):
        """Parser should default workflow_name to 'unnamed' when not provided."""
        workflow = Workflow(
            nodes={
                "1": WorkflowNode(
                    id="1",
                    type="CheckpointLoaderSimple",
                    widgets_values=["model.safetensors"]
                )
            }
        )

        parser = WorkflowDependencyParser(workflow)
        deps = parser.analyze_dependencies()

        assert deps.workflow_name == "unnamed"
        assert len(deps.found_models) == 1

    def test_path_input_still_works(self, tmp_path):
        """Path input should continue to work as before (backward compat)."""
        workflow_data = {
            "nodes": [{
                "id": 1,
                "type": "CheckpointLoaderSimple",
                "widgets_values": ["test_model.safetensors"]
            }],
            "links": [],
            "groups": [],
            "version": 0.4
        }
        wf_path = tmp_path / "backward_compat_test.json"
        wf_path.write_text(json.dumps(workflow_data))

        parser = WorkflowDependencyParser(wf_path)
        deps = parser.analyze_dependencies()

        # Should use filename stem as workflow name
        assert deps.workflow_name == "backward_compat_test"
        assert len(deps.found_models) == 1

    def test_path_input_with_custom_name(self, tmp_path):
        """Path input should allow overriding workflow_name."""
        workflow_data = {
            "nodes": [{
                "id": 1,
                "type": "CheckpointLoaderSimple",
                "widgets_values": ["model.safetensors"]
            }],
            "links": [],
            "groups": [],
            "version": 0.4
        }
        wf_path = tmp_path / "file_name.json"
        wf_path.write_text(json.dumps(workflow_data))

        parser = WorkflowDependencyParser(wf_path, workflow_name="custom_name")
        deps = parser.analyze_dependencies()

        assert deps.workflow_name == "custom_name"
