"""Tests for dynamic builtin node extraction utility."""
import json

import pytest


class TestBuiltinExtractor:
    """Tests for extract_comfyui_builtins function."""

    def test_extract_from_minimal_comfyui(self, tmp_path):
        """Test extraction from minimal ComfyUI directory structure."""
        from comfygit_core.utils.builtin_extractor import extract_comfyui_builtins

        # Create minimal ComfyUI structure
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()

        # Create nodes.py with NODE_CLASS_MAPPINGS
        nodes_py = comfyui_path / "nodes.py"
        nodes_py.write_text('''
NODE_CLASS_MAPPINGS = {
    "KSampler": KSampler,
    "CheckpointLoaderSimple": CheckpointLoaderSimple,
    "CLIPTextEncode": CLIPTextEncode,
}
''')

        # Create output path
        output_path = tmp_path / "builtins.json"

        # Extract
        result = extract_comfyui_builtins(comfyui_path, output_path)

        # Verify output file created
        assert output_path.exists()

        # Verify structure
        assert "metadata" in result
        assert "all_builtin_nodes" in result
        assert "nodes_by_category" in result

        # Verify core nodes extracted
        assert "KSampler" in result["all_builtin_nodes"]
        assert "CheckpointLoaderSimple" in result["all_builtin_nodes"]
        assert "CLIPTextEncode" in result["all_builtin_nodes"]

        # Verify metadata
        assert result["metadata"]["total_nodes"] >= 3

    def test_extract_from_comfy_extras(self, tmp_path):
        """Test extraction from comfy_extras directory."""
        from comfygit_core.utils.builtin_extractor import extract_comfyui_builtins

        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()

        # Create minimal nodes.py
        (comfyui_path / "nodes.py").write_text('NODE_CLASS_MAPPINGS = {}')

        # Create comfy_extras with nodes
        extras_dir = comfyui_path / "comfy_extras"
        extras_dir.mkdir()

        (extras_dir / "nodes_custom_sampler.py").write_text('''
NODE_CLASS_MAPPINGS = {
    "BasicScheduler": BasicScheduler,
    "SamplerCustom": SamplerCustom,
}
''')

        output_path = tmp_path / "builtins.json"
        result = extract_comfyui_builtins(comfyui_path, output_path)

        # Verify extras nodes extracted
        assert "BasicScheduler" in result["all_builtin_nodes"]
        assert "SamplerCustom" in result["all_builtin_nodes"]

    def test_extract_v3_comfynode_pattern(self, tmp_path):
        """Test extraction of V3 io.ComfyNode pattern nodes."""
        from comfygit_core.utils.builtin_extractor import extract_comfyui_builtins

        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        (comfyui_path / "nodes.py").write_text('NODE_CLASS_MAPPINGS = {}')

        # Create comfy_api_nodes with V3 pattern
        api_dir = comfyui_path / "comfy_api_nodes"
        api_dir.mkdir()

        (api_dir / "nodes_bfl.py").write_text('''
class FluxProUltraImageNode(io.ComfyNode):
    def define_schema(self):
        return IO.NodeSchema(
            node_id="FluxProUltraImageNode",
            display_name="Flux Pro Ultra Image",
        )
''')

        output_path = tmp_path / "builtins.json"
        result = extract_comfyui_builtins(comfyui_path, output_path)

        # Verify V3 node extracted
        assert "FluxProUltraImageNode" in result["all_builtin_nodes"]

    def test_extract_with_invalid_path_raises(self, tmp_path):
        """Test error handling for invalid ComfyUI path."""
        from comfygit_core.utils.builtin_extractor import extract_comfyui_builtins

        invalid_path = tmp_path / "not_comfyui"
        invalid_path.mkdir()
        # No nodes.py file

        output_path = tmp_path / "builtins.json"

        with pytest.raises(ValueError, match="Invalid ComfyUI path"):
            extract_comfyui_builtins(invalid_path, output_path)

    def test_json_output_structure(self, tmp_path):
        """Validate JSON schema matches expected structure."""
        from comfygit_core.utils.builtin_extractor import extract_comfyui_builtins

        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        (comfyui_path / "nodes.py").write_text('''
NODE_CLASS_MAPPINGS = {"TestNode": TestNode}
''')

        output_path = tmp_path / "builtins.json"
        extract_comfyui_builtins(comfyui_path, output_path)

        # Verify JSON can be read back
        with open(output_path) as f:
            loaded = json.load(f)

        # Check required fields
        assert "metadata" in loaded
        assert "extraction_date" in loaded["metadata"]
        assert "total_nodes" in loaded["metadata"]
        assert "categories" in loaded["metadata"]
        assert "nodes_by_category" in loaded
        assert "all_builtin_nodes" in loaded
        assert isinstance(loaded["all_builtin_nodes"], list)

    def test_includes_frontend_nodes(self, tmp_path):
        """Test that known frontend nodes are included."""
        from comfygit_core.utils.builtin_extractor import extract_comfyui_builtins

        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        (comfyui_path / "nodes.py").write_text('NODE_CLASS_MAPPINGS = {}')

        output_path = tmp_path / "builtins.json"
        result = extract_comfyui_builtins(comfyui_path, output_path)

        # Frontend nodes should always be included
        assert "Reroute" in result["all_builtin_nodes"]
        assert "Note" in result["all_builtin_nodes"]
        assert "PrimitiveNode" in result["all_builtin_nodes"]

    def test_ast_node_mapping_with_dynamic_key(self, tmp_path):
        """AST parser should ignore dynamic dict keys without crashing."""
        from comfygit_core.utils.builtin_extractor import _extract_from_ast

        nodes_py = tmp_path / "nodes.py"
        nodes_py.write_text('''
dynamic_key = "DynamicNode"
NODE_CLASS_MAPPINGS = {
    dynamic_key: DynamicNode,
    "KSampler": KSampler,
}
''')

        extracted = _extract_from_ast(str(nodes_py))
        assert "KSampler" in extracted

    def test_ast_comfynode_with_non_constant_node_id(self, tmp_path):
        """AST parser should skip non-constant node_id values without crashing."""
        from comfygit_core.utils.builtin_extractor import _extract_comfynode_from_ast

        api_py = tmp_path / "nodes_api.py"
        api_py.write_text('''
NODE_ID = "DynamicComfyNode"

class DynamicNode(io.ComfyNode):
    def define_schema(self):
        return IO.NodeSchema(node_id=NODE_ID)

class StaticNode(io.ComfyNode):
    def define_schema(self):
        return IO.NodeSchema(node_id="StaticComfyNode")
''')

        extracted = _extract_comfynode_from_ast(str(api_py))
        assert "StaticComfyNode" in extracted

    def test_ast_comfynode_with_class_constant_node_id(self, tmp_path):
        """AST parser should resolve cls.NODE_ID when class constant is a string."""
        from comfygit_core.utils.builtin_extractor import _extract_comfynode_from_ast

        api_py = tmp_path / "nodes_api.py"
        api_py.write_text('''
class FluxNode(io.ComfyNode):
    NODE_ID = "FluxKontextProImageNode"

    @classmethod
    def define_schema(cls):
        return IO.NodeSchema(node_id=cls.NODE_ID)
''')

        extracted = _extract_comfynode_from_ast(str(api_py))
        assert "FluxKontextProImageNode" in extracted

    def test_ast_comfynode_with_custom_class_constant_name(self, tmp_path):
        """AST parser should resolve cls.<CONST> for non-NODE_ID names."""
        from comfygit_core.utils.builtin_extractor import _extract_comfynode_from_ast

        api_py = tmp_path / "nodes_api.py"
        api_py.write_text('''
class FluxNode(io.ComfyNode):
    SOME_OTHER_CONST = "Flux2ProImageNode"

    @classmethod
    def define_schema(cls):
        return IO.NodeSchema(node_id=cls.SOME_OTHER_CONST)
''')

        extracted = _extract_comfynode_from_ast(str(api_py))
        assert "Flux2ProImageNode" in extracted

    def test_ast_comfynode_ignores_non_string_class_constant(self, tmp_path):
        """AST parser should ignore cls.<CONST> when class constant is not a string."""
        from comfygit_core.utils.builtin_extractor import _extract_comfynode_from_ast

        api_py = tmp_path / "nodes_api.py"
        api_py.write_text('''
class BadNode(io.ComfyNode):
    NODE_ID = 123

    @classmethod
    def define_schema(cls):
        return IO.NodeSchema(node_id=cls.NODE_ID)
''')

        extracted = _extract_comfynode_from_ast(str(api_py))
        assert "123" not in extracted
        assert extracted == []

    def test_extract_node_names_supports_nodeid_pattern(self, tmp_path):
        """Regex fallback should still support old-style NodeId patterns."""
        from comfygit_core.utils.builtin_extractor import _extract_node_names

        api_py = tmp_path / "nodes_api.py"
        api_py.write_text('''
class LegacyNode:
    NodeId = "LegacyNodeIdPattern"
''')

        extracted = _extract_node_names(str(api_py))
        assert "LegacyNodeIdPattern" in extracted


class TestNodeClassifierWithEnvironment:
    """Tests for NodeClassifier loading from environment-specific config."""

    def test_classifier_loads_from_environment(self, tmp_path):
        """Test loading builtins from .cec/comfyui_builtins.json."""
        from comfygit_core.analyzers.node_classifier import NodeClassifier

        # Create .cec directory with builtins config
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        builtins_file = cec_path / "comfyui_builtins.json"
        builtins_data = {
            "metadata": {
                "comfyui_version": "v0.3.68",
                "total_nodes": 2
            },
            "all_builtin_nodes": ["CustomBuiltin1", "CustomBuiltin2"]
        }
        with open(builtins_file, 'w') as f:
            json.dump(builtins_data, f)

        # Create classifier with cec_path
        classifier = NodeClassifier(cec_path)

        # Verify it loaded environment-specific config
        assert "CustomBuiltin1" in classifier.builtin_nodes
        assert "CustomBuiltin2" in classifier.builtin_nodes
        # Should not have global static config
        assert len(classifier.builtin_nodes) == 2

    def test_classifier_falls_back_to_global(self, tmp_path):
        """Test fallback when environment config missing."""
        from comfygit_core.analyzers.node_classifier import NodeClassifier

        # Create empty .cec directory (no builtins file)
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        # Create classifier - should fall back to global
        classifier = NodeClassifier(cec_path)

        # Should have nodes from global static config
        assert "KSampler" in classifier.builtin_nodes
        assert len(classifier.builtin_nodes) > 100  # Global has ~480 nodes

    def test_classifier_with_none_uses_global(self):
        """Test that None cec_path uses global config."""
        from comfygit_core.analyzers.node_classifier import NodeClassifier

        classifier = NodeClassifier(None)

        # Should use global config
        assert "KSampler" in classifier.builtin_nodes
        assert "CLIPTextEncode" in classifier.builtin_nodes

    def test_classify_single_node_with_environment_builtins(self, tmp_path):
        """Test classification uses environment-specific config."""
        from comfygit_core.analyzers.node_classifier import NodeClassifier
        from comfygit_core.models.workflow import WorkflowNode

        # Create environment config with custom builtins
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        builtins_file = cec_path / "comfyui_builtins.json"
        builtins_data = {
            "metadata": {"total_nodes": 1},
            "all_builtin_nodes": ["MyCustomBuiltin"]
        }
        with open(builtins_file, 'w') as f:
            json.dump(builtins_data, f)

        classifier = NodeClassifier(cec_path)

        # Create test nodes
        builtin_node = WorkflowNode(id="1", type="MyCustomBuiltin", widgets_values=[])
        custom_node = WorkflowNode(id="2", type="UnknownNode", widgets_values=[])

        # Classify
        assert classifier.classify_single_node(builtin_node) == "builtin"
        assert classifier.classify_single_node(custom_node) == "custom"

        # KSampler is NOT in this environment's builtins
        ksampler_node = WorkflowNode(id="3", type="KSampler", widgets_values=[])
        assert classifier.classify_single_node(ksampler_node) == "custom"

    def test_classify_nodes_static_with_cec_path(self, tmp_path):
        """Test static classify_nodes method with cec_path parameter."""
        from comfygit_core.analyzers.node_classifier import NodeClassifier
        from comfygit_core.models.workflow import Workflow, WorkflowNode

        # Create environment config
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        builtins_file = cec_path / "comfyui_builtins.json"
        builtins_data = {
            "metadata": {"total_nodes": 1},
            "all_builtin_nodes": ["EnvBuiltin"]
        }
        with open(builtins_file, 'w') as f:
            json.dump(builtins_data, f)

        # Create workflow with mixed nodes
        nodes = {
            "1": WorkflowNode(id="1", type="EnvBuiltin", widgets_values=[]),
            "2": WorkflowNode(id="2", type="CustomNode", widgets_values=[])
        }
        workflow = Workflow(nodes=nodes)

        # Classify using static method with cec_path
        result = NodeClassifier.classify_nodes(workflow, cec_path)

        assert len(result.builtin_nodes) == 1
        assert result.builtin_nodes[0].type == "EnvBuiltin"
        assert len(result.custom_nodes) == 1
        assert result.custom_nodes[0].type == "CustomNode"

    def test_corrupted_json_falls_back(self, tmp_path):
        """Test fallback when JSON is corrupted."""
        from comfygit_core.analyzers.node_classifier import NodeClassifier

        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        builtins_file = cec_path / "comfyui_builtins.json"
        builtins_file.write_text("not valid json {{{")

        # Should fall back to global without raising
        classifier = NodeClassifier(cec_path)
        assert "KSampler" in classifier.builtin_nodes


class TestWorkflowDependencyParserWithCecPath:
    """Tests for WorkflowDependencyParser with cec_path support."""

    def test_parser_uses_environment_builtins(self, tmp_path, workflow_fixtures):
        """Test that parser uses environment-specific builtins for classification."""
        import json

        from comfygit_core.analyzers.workflow_dependency_parser import WorkflowDependencyParser

        # Create environment config where KSampler is NOT a builtin
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()

        builtins_file = cec_path / "comfyui_builtins.json"
        builtins_data = {
            "metadata": {"total_nodes": 1},
            "all_builtin_nodes": ["CLIPTextEncode"]  # Only this is builtin
        }
        with open(builtins_file, 'w') as f:
            json.dump(builtins_data, f)

        # Create workflow with KSampler
        workflow_path = tmp_path / "test.json"
        workflow_data = {
            "nodes": [
                {"id": 1, "type": "KSampler", "widgets_values": []},
                {"id": 2, "type": "CLIPTextEncode", "widgets_values": []}
            ]
        }
        with open(workflow_path, 'w') as f:
            json.dump(workflow_data, f)

        # Parse with cec_path
        parser = WorkflowDependencyParser(workflow_path, cec_path=cec_path)
        deps = parser.analyze_dependencies()

        # KSampler should be classified as custom (missing) in this environment
        assert len(deps.non_builtin_nodes) == 1
        assert deps.non_builtin_nodes[0].type == "KSampler"

        # CLIPTextEncode should be builtin
        assert len(deps.builtin_nodes) == 1
        assert deps.builtin_nodes[0].type == "CLIPTextEncode"
