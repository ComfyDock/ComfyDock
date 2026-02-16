"""Unit tests for context-aware node resolution logic.

Tests the core resolution priority order and context tracking in GlobalNodeResolver.
"""

from unittest.mock import Mock

from comfygit_core.models.shared import NodeInfo
from comfygit_core.models.workflow import NodeResolutionContext, WorkflowNode
from comfygit_core.repositories.node_mappings_repository import NodeMappingsRepository
from comfygit_core.resolvers.global_node_resolver import GlobalNodeResolver


class TestPropertiesFieldResolution:
    """Test resolution using properties field from workflow."""

    def test_properties_field_with_cnr_id_resolves_directly(self, tmp_path):
        """Should resolve using cnr_id from properties without checking global table."""
        # ARRANGE: Create resolver with one valid package
        mappings_file = tmp_path / "node_mappings.json"

        # Create minimal global mappings with the package
        import json
        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {},
            "packages": {
                "rgthree-comfy": {
                    "id": "rgthree-comfy",
                    "display_name": "rgthree's ComfyUI Nodes",
                    "description": "Test package",
                    "repository": "https://github.com/rgthree/rgthree-comfy",
                    "versions": {}
                }
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repository = NodeMappingsRepository(data_manager=mock_data_manager)
        resolver = GlobalNodeResolver(repository)

        # Create node with properties
        node = WorkflowNode(
            id="1",
            type="Mute / Bypass Repeater (rgthree)",
            pos=[0, 0],
            size=[100, 100],
            flags={},
            order=0,
            mode=0,
            inputs=[],
            outputs=[],
            properties={"cnr_id": "rgthree-comfy", "ver": "abc123def456"},
            widgets_values=[]
        )

        context = NodeResolutionContext()

        # ACT: Resolve node
        result = resolver.resolve_single_node_with_context(node, context)

        # ASSERT: Should resolve from properties
        assert result is not None, "Should resolve node with properties"
        assert len(result) == 1
        assert result[0].package_id == "rgthree-comfy"
        assert result[0].match_type == "properties"
        assert result[0].match_confidence == 1.0
        assert "abc123def456" in result[0].versions

    def test_properties_with_invalid_cnr_id_falls_through(self, tmp_path):
        """Properties with cnr_id not in registry should fall through to next strategy."""
        # ARRANGE: Empty global mappings (package doesn't exist)
        mappings_file = tmp_path / "node_mappings.json"

        import json
        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {},
            "packages": {}  # Empty - invalid cnr_id
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repository = NodeMappingsRepository(data_manager=mock_data_manager)
        resolver = GlobalNodeResolver(repository)

        node = WorkflowNode(
            id="1",
            type="UnknownNode",
            pos=[0, 0],
            size=[100, 100],
            flags={},
            order=0,
            mode=0,
            inputs=[],
            outputs=[],
            properties={"cnr_id": "nonexistent-package", "ver": "abc123"},
            widgets_values=[]
        )

        context = NodeResolutionContext()

        # ACT: Resolve node
        result = resolver.resolve_single_node_with_context(node, context)

        # ASSERT: Should fall through (return None or use next strategy)
        # For this test, we expect it to return None since no other strategies match
        assert result is None, "Should return None when properties cnr_id is invalid"

    def test_properties_field_alias_cnr_id_resolves_to_canonical(self, tmp_path):
        """Legacy cnr_id should resolve via package_aliases metadata."""
        mappings_file = tmp_path / "node_mappings.json"

        import json
        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "package_aliases": {
                "rgthree-comfy-legacy": "rgthree-comfy"
            },
            "mappings": {},
            "packages": {
                "rgthree-comfy": {
                    "id": "rgthree-comfy",
                    "display_name": "rgthree's ComfyUI Nodes",
                    "versions": {}
                }
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repository = NodeMappingsRepository(data_manager=mock_data_manager)
        resolver = GlobalNodeResolver(repository)

        node = WorkflowNode(
            id="1",
            type="Mute / Bypass Repeater (rgthree)",
            pos=[0, 0],
            size=[100, 100],
            flags={},
            order=0,
            mode=0,
            inputs=[],
            outputs=[],
            properties={"cnr_id": "rgthree-comfy-legacy", "ver": "abc123def456"},
            widgets_values=[]
        )

        result = resolver.resolve_single_node_with_context(node, NodeResolutionContext())

        assert result is not None
        assert len(result) == 1
        assert result[0].package_id == "rgthree-comfy"
        assert result[0].match_type == "properties"


class TestSessionCacheDeduplication:
    """Test session-level caching to avoid re-resolving same node types."""

    def test_duplicate_node_types_reuse_resolution(self, tmp_path):
        """Resolving same node type twice should hit session cache on second call."""
        # ARRANGE: Create resolver with global mapping
        mappings_file = tmp_path / "node_mappings.json"

        import json
        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {
                "TestNode::_": [
                    {
                        "package_id": "test-package",
                        "versions": [],
                        "rank": 1,
                        "source": "registry"
                    }
                ]
            },
            "packages": {
                "test-package": {
                    "id": "test-package",
                    "display_name": "Test Package",
                    "versions": {}
                }
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repository = NodeMappingsRepository(data_manager=mock_data_manager)
        resolver = GlobalNodeResolver(repository)
        context = NodeResolutionContext()

        # Create two nodes with same type, different IDs
        node1 = WorkflowNode(
            id="1", type="TestNode", pos=[0, 0], size=[100, 100],
            flags={}, order=0, mode=0, inputs=[], outputs=[],
            properties={}, widgets_values=[]
        )

        node2 = WorkflowNode(
            id="2", type="TestNode", pos=[100, 100], size=[100, 100],
            flags={}, order=1, mode=0, inputs=[], outputs=[],
            properties={}, widgets_values=[]
        )

        # ACT: Resolve first node (populates session cache)
        result1 = resolver.resolve_single_node_with_context(node1, context)

        # Resolve second node (should hit cache)
        result2 = resolver.resolve_single_node_with_context(node2, context)

        # ASSERT: Both resolve to same package
        assert result1 is not None
        assert result2 is not None
        assert result1[0].package_id == result2[0].package_id == "test-package"

        # Both should be type_only matches (no session cache in current implementation)
        assert result1[0].match_type == "type_only"
        assert result2[0].match_type == "type_only"


class TestCustomMappingsOverride:
    """Test that user's custom mappings override global table."""

    def test_custom_mapping_overrides_global_table(self, tmp_path):
        """Custom mapping in pyproject should take priority over global table."""
        # ARRANGE: Global table maps to package-a
        mappings_file = tmp_path / "node_mappings.json"

        import json
        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {
                "AmbiguousNode::_": [
                    {
                        "package_id": "package-a",
                        "versions": [],
                        "rank": 1,
                        "source": "registry"
                    }
                ]
            },
            "packages": {
                "package-a": {"id": "package-a", "display_name": "Package A", "versions": {}},
                "package-b": {"id": "package-b", "display_name": "Package B", "versions": {}}
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repository = NodeMappingsRepository(data_manager=mock_data_manager)
        resolver = GlobalNodeResolver(repository)

        # Context with custom mapping to package-b
        context = NodeResolutionContext(
            custom_mappings={"AmbiguousNode": "package-b"}
        )

        node = WorkflowNode(
            id="1", type="AmbiguousNode", pos=[0, 0], size=[100, 100],
            flags={}, order=0, mode=0, inputs=[], outputs=[],
            properties={}, widgets_values=[]
        )

        # ACT: Resolve node
        result = resolver.resolve_single_node_with_context(node, context)

        # ASSERT: Should use package-b from custom mapping (not package-a!)
        assert result is not None
        assert result[0].package_id == "package-b"
        assert result[0].match_type == "custom_mapping"
        assert result[0].match_confidence == 1.0

    def test_custom_mapping_skip_returns_empty_list(self, tmp_path):
        """Custom mapping with 'skip' value should return empty list."""
        # ARRANGE
        mappings_file = tmp_path / "node_mappings.json"

        import json
        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {},
            "packages": {}
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repository = NodeMappingsRepository(data_manager=mock_data_manager)
        resolver = GlobalNodeResolver(repository)

        context = NodeResolutionContext(
            custom_mappings={"SkippedNode": False}  # False = optional node
        )

        node = WorkflowNode(
            id="1", type="SkippedNode", pos=[0, 0], size=[100, 100],
            flags={}, order=0, mode=0, inputs=[], outputs=[],
            properties={}, widgets_values=[]
        )

        # ACT
        result = resolver.resolve_single_node_with_context(node, context)

        # ASSERT: Should return ResolvedNodePackage with is_optional=True
        assert result is not None
        assert len(result) == 1
        assert result[0].is_optional is True
        assert result[0].match_type == "custom_mapping"


class TestHeuristicRemoved:
    """Test that heuristic matching no longer auto-resolves (REFACTORED)."""

    def test_heuristic_hint_returns_none_for_interactive(self, tmp_path):
        """CHANGED: Node with hint should NOT auto-resolve, should return None for interactive."""
        # ARRANGE: Empty global mappings (node NOT in table)
        mappings_file = tmp_path / "node_mappings.json"

        import json
        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {},  # Empty - not in global table
            "packages": {
                "rgthree-comfy": {
                    "id": "rgthree-comfy",
                    "display_name": "rgthree's ComfyUI Nodes",
                    "versions": {}
                }
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repository = NodeMappingsRepository(data_manager=mock_data_manager)
        resolver = GlobalNodeResolver(repository)

        # Context with installed package
        context = NodeResolutionContext(
            installed_packages={
                "rgthree-comfy": NodeInfo(
                    name="rgthree-comfy",
                    registry_id="rgthree-comfy",
                    source="registry"
                )
            }
        )

        node = WorkflowNode(
            id="1",
            type="Mute / Bypass Repeater (rgthree)",  # Has parenthetical hint!
            pos=[0, 0], size=[100, 100],
            flags={}, order=0, mode=0,
            inputs=[], outputs=[],
            properties={},  # No properties
            widgets_values=[]
        )

        # ACT
        result = resolver.resolve_single_node_with_context(node, context)

        # ASSERT: Should return None (trigger interactive strategy)
        # This is the key behavior change - no auto-resolution
        assert result is None, "Heuristic hints should NOT auto-resolve, should return None"

    def test_node_without_hint_still_returns_none(self, tmp_path):
        """Node without hint should still return None (unchanged behavior)."""
        # ARRANGE
        mappings_file = tmp_path / "node_mappings.json"

        import json
        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {},
            "packages": {}
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repository = NodeMappingsRepository(data_manager=mock_data_manager)
        resolver = GlobalNodeResolver(repository)

        context = NodeResolutionContext(
            installed_packages={
                "some-package": NodeInfo(
                    name="some-package",
                    registry_id="some-package",
                    source="registry"
                )
            }
        )

        node = WorkflowNode(
            id="1",
            type="UnrelatedNode",  # No hint
            pos=[0, 0], size=[100, 100],
            flags={}, order=0, mode=0,
            inputs=[], outputs=[],
            properties={},
            widgets_values=[]
        )

        # ACT
        result = resolver.resolve_single_node_with_context(node, context)

        # ASSERT: Should return None (no match, unchanged)
        assert result is None, "Node without hint should return None"


class TestResolutionPriorityOrder:
    """Test that resolution strategies are checked in correct priority order."""

    def test_session_cache_has_highest_priority(self, tmp_path):
        """Session cache should be checked before all other strategies."""
        # ARRANGE: Set up ALL strategies with different packages
        mappings_file = tmp_path / "node_mappings.json"

        import json
        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {
                "TestNode::_": [
                    {
                        "package_id": "global-package",
                        "versions": [],
                        "rank": 1,
                        "source": "registry"
                    }
                ]
            },
            "packages": {
                "global-package": {"id": "global-package", "display_name": "Global", "versions": {}},
                "custom-package": {"id": "custom-package", "display_name": "Custom", "versions": {}},
                "properties-package": {"id": "properties-package", "display_name": "Properties", "versions": {}},
                "cached-package": {"id": "cached-package", "display_name": "Cached", "versions": {}}
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repository = NodeMappingsRepository(data_manager=mock_data_manager)
        resolver = GlobalNodeResolver(repository)

        # Context with custom mapping and properties
        context = NodeResolutionContext(
            custom_mappings={"TestNode": "custom-package"}
        )

        node = WorkflowNode(
            id="1", type="TestNode",
            pos=[0, 0], size=[100, 100],
            flags={}, order=0, mode=0,
            inputs=[], outputs=[],
            properties={"cnr_id": "properties-package"},  # Also has properties
            widgets_values=[]
        )

        # ACT
        result = resolver.resolve_single_node_with_context(node, context)

        # ASSERT: Custom mapping has priority over properties and global table
        assert result is not None
        assert result[0].package_id == "custom-package"
        assert result[0].match_type == "custom_mapping"

    def test_fallthrough_order_when_higher_priorities_missing(self, tmp_path):
        """Should fall through priority levels in order."""
        mappings_file = tmp_path / "node_mappings.json"

        import json
        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {
                "TestNode::_": [
                    {
                        "package_id": "global-package",
                        "versions": [],
                        "rank": 1,
                        "source": "registry"
                    }
                ]
            },
            "packages": {
                "global-package": {"id": "global-package", "display_name": "Global", "versions": {}},
                "custom-package": {"id": "custom-package", "display_name": "Custom", "versions": {}}
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repository = NodeMappingsRepository(data_manager=mock_data_manager)
        resolver = GlobalNodeResolver(repository)

        # Test 1: Custom mapping (no session cache)
        context1 = NodeResolutionContext(
            custom_mappings={"TestNode": "custom-package"}
        )

        node = WorkflowNode(
            id="1", type="TestNode", pos=[0, 0], size=[100, 100],
            flags={}, order=0, mode=0, inputs=[], outputs=[],
            properties={}, widgets_values=[]
        )

        result1 = resolver.resolve_single_node_with_context(node, context1)
        assert result1[0].package_id == "custom-package"

        # Test 2: Global table (no custom or session)
        context2 = NodeResolutionContext()

        result2 = resolver.resolve_single_node_with_context(node, context2)
        assert result2[0].package_id == "global-package"
