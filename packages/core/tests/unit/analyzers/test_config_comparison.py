"""Tests for config_comparison.py - shared comparison functions for pyproject.toml configs.

These tests verify the pure functions extracted from GitChangeParser for DRY reuse
by both GitChangeParser (HEAD vs working tree) and RefDiffAnalyzer (any ref vs any ref).
"""


from comfygit_core.analyzers.config_comparison import (
    compare_constraint_configs,
    compare_node_configs,
    extract_models_section,
    extract_nodes_section,
    flatten_nodes,
)


class TestFlattenNodes:
    """Test the flatten_nodes function that handles legacy 'development' sections."""

    def test_empty_config(self):
        """Empty config returns empty dict."""
        result = flatten_nodes({})
        assert result == {}

    def test_regular_nodes_flattened(self):
        """Regular nodes with 'name' key are preserved."""
        nodes = {
            "comfyui-custom-scripts": {"name": "ComfyUI-Custom-Scripts", "version": "1.0.0"},
            "comfyui-manager": {"name": "ComfyUI-Manager", "version": "2.0.0"},
        }
        result = flatten_nodes(nodes)
        assert "comfyui-custom-scripts" in result
        assert "comfyui-manager" in result
        assert result["comfyui-custom-scripts"]["name"] == "ComfyUI-Custom-Scripts"

    def test_legacy_development_section_flattened(self):
        """Legacy 'development' nested section is flattened to top level."""
        nodes = {
            "comfyui-manager": {"name": "ComfyUI-Manager", "version": "1.0.0"},
            "development": {
                "my-dev-node": {"name": "My Dev Node", "version": "dev"},
            },
        }
        result = flatten_nodes(nodes)
        # Both regular and dev nodes should be at top level
        assert "comfyui-manager" in result
        assert "my-dev-node" in result
        assert result["my-dev-node"]["version"] == "dev"
        # 'development' key itself should NOT be in result
        assert "development" not in result

    def test_ignores_non_node_entries(self):
        """Entries without 'name' key (not nodes) are ignored."""
        nodes = {
            "comfyui-manager": {"name": "ComfyUI-Manager", "version": "1.0.0"},
            "some_string": "not a dict",  # Should be ignored
            "invalid_node": {"foo": "bar"},  # No 'name', should be ignored
        }
        result = flatten_nodes(nodes)
        assert "comfyui-manager" in result
        assert "some_string" not in result
        assert "invalid_node" not in result


class TestExtractNodesSection:
    """Test extracting nodes section from full pyproject config."""

    def test_extracts_nodes_from_tool_comfygit(self):
        """Correctly extracts [tool.comfygit.nodes] section."""
        config = {
            "tool": {
                "comfygit": {
                    "nodes": {
                        "comfyui-manager": {"name": "ComfyUI-Manager", "version": "1.0.0"}
                    }
                }
            }
        }
        result = extract_nodes_section(config)
        assert "comfyui-manager" in result

    def test_returns_empty_for_missing_tool(self):
        """Returns empty dict if 'tool' section missing."""
        result = extract_nodes_section({})
        assert result == {}

    def test_returns_empty_for_missing_comfygit(self):
        """Returns empty dict if 'comfygit' section missing."""
        result = extract_nodes_section({"tool": {}})
        assert result == {}

    def test_returns_empty_for_missing_nodes(self):
        """Returns empty dict if 'nodes' section missing."""
        result = extract_nodes_section({"tool": {"comfygit": {}}})
        assert result == {}


class TestExtractModelsSection:
    """Test extracting models section from full pyproject config."""

    def test_extracts_models_from_tool_comfygit(self):
        """Correctly extracts [tool.comfygit.models] section."""
        config = {
            "tool": {
                "comfygit": {
                    "models": {
                        "abc123": {"filename": "model.safetensors", "category": "checkpoints"}
                    }
                }
            }
        }
        result = extract_models_section(config)
        assert "abc123" in result
        assert result["abc123"]["filename"] == "model.safetensors"

    def test_returns_empty_for_missing_sections(self):
        """Returns empty dict for missing nested sections."""
        assert extract_models_section({}) == {}
        assert extract_models_section({"tool": {}}) == {}
        assert extract_models_section({"tool": {"comfygit": {}}}) == {}


class TestCompareNodeConfigs:
    """Test comparing two node configurations for changes."""

    def test_empty_both(self):
        """Both empty returns no changes."""
        result = compare_node_configs({}, {})
        assert result["nodes_added"] == []
        assert result["nodes_removed"] == []

    def test_nodes_added(self):
        """Detects newly added nodes."""
        old_config = {"tool": {"comfygit": {"nodes": {}}}}
        new_config = {
            "tool": {
                "comfygit": {
                    "nodes": {
                        "comfyui-manager": {"name": "ComfyUI-Manager", "version": "1.0.0"}
                    }
                }
            }
        }
        result = compare_node_configs(old_config, new_config)
        assert len(result["nodes_added"]) == 1
        assert result["nodes_added"][0]["name"] == "ComfyUI-Manager"
        assert result["nodes_removed"] == []

    def test_nodes_removed(self):
        """Detects removed nodes."""
        old_config = {
            "tool": {
                "comfygit": {
                    "nodes": {
                        "comfyui-manager": {"name": "ComfyUI-Manager", "version": "1.0.0"}
                    }
                }
            }
        }
        new_config = {"tool": {"comfygit": {"nodes": {}}}}
        result = compare_node_configs(old_config, new_config)
        assert len(result["nodes_removed"]) == 1
        assert result["nodes_removed"][0]["name"] == "ComfyUI-Manager"
        assert result["nodes_added"] == []

    def test_dev_nodes_flagged(self):
        """Development nodes have is_development=True."""
        old_config = {"tool": {"comfygit": {"nodes": {}}}}
        new_config = {
            "tool": {
                "comfygit": {
                    "nodes": {
                        "my-dev-node": {"name": "My Dev Node", "version": "dev"}
                    }
                }
            }
        }
        result = compare_node_configs(old_config, new_config)
        assert result["nodes_added"][0]["is_development"] is True

    def test_unchanged_nodes_not_reported(self):
        """Nodes present in both configs are not reported."""
        config = {
            "tool": {
                "comfygit": {
                    "nodes": {
                        "comfyui-manager": {"name": "ComfyUI-Manager", "version": "1.0.0"}
                    }
                }
            }
        }
        result = compare_node_configs(config, config)
        assert result["nodes_added"] == []
        assert result["nodes_removed"] == []


class TestCompareConstraintConfigs:
    """Test comparing UV constraint dependencies between configs."""

    def test_empty_both(self):
        """Both empty returns no changes."""
        result = compare_constraint_configs({}, {})
        assert result["constraints_added"] == []
        assert result["constraints_removed"] == []

    def test_constraints_added(self):
        """Detects newly added constraints."""
        old_config = {"tool": {"uv": {"constraint-dependencies": []}}}
        new_config = {
            "tool": {
                "uv": {"constraint-dependencies": ["numpy<2.0", "torch>=2.0,<3.0"]}
            }
        }
        result = compare_constraint_configs(old_config, new_config)
        assert len(result["constraints_added"]) == 2
        assert "numpy<2.0" in result["constraints_added"]
        assert "torch>=2.0,<3.0" in result["constraints_added"]
        assert result["constraints_removed"] == []

    def test_constraints_removed(self):
        """Detects removed constraints."""
        old_config = {"tool": {"uv": {"constraint-dependencies": ["numpy<2.0"]}}}
        new_config = {"tool": {"uv": {"constraint-dependencies": []}}}
        result = compare_constraint_configs(old_config, new_config)
        assert result["constraints_removed"] == ["numpy<2.0"]
        assert result["constraints_added"] == []

    def test_unchanged_constraints_not_reported(self):
        """Constraints in both are not reported."""
        config = {"tool": {"uv": {"constraint-dependencies": ["numpy<2.0"]}}}
        result = compare_constraint_configs(config, config)
        assert result["constraints_added"] == []
        assert result["constraints_removed"] == []

    def test_missing_sections_handled(self):
        """Missing nested sections don't cause errors."""
        old_config = {}
        new_config = {"tool": {"uv": {"constraint-dependencies": ["numpy<2.0"]}}}
        result = compare_constraint_configs(old_config, new_config)
        assert result["constraints_added"] == ["numpy<2.0"]
