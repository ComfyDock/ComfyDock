"""Tests for GlobalNodeResolver with v2.0 schema (multi-package mappings with ranking).

These tests are written to FAIL with the current v1.0 implementation and PASS
after implementing the v2.0 schema changes.

Key v2.0 Changes:
- Mappings now contain LISTS of packages with ranking
- PackageMapping dataclass with rank field
- Auto-select behavior based on installed nodes + rank
- Configurable ambiguous match handling
"""

import json
import tempfile
from pathlib import Path

from comfygit_core.models.shared import NodeInfo
from comfygit_core.models.workflow import NodeResolutionContext, WorkflowNode
from comfygit_core.repositories.node_mappings_repository import NodeMappingsRepository
from comfygit_core.resolvers.global_node_resolver import GlobalNodeResolver


class TestSchemaV2Loading:
    """Test that resolver loads v2.0 schema correctly."""

    def test_load_single_package_mapping(self):
        """Single package mapping (backward compatible case)."""
        mappings_data = {
            "version": "2025.10.10",
            "generated_at": "2025-10-10T00:00:00Z",
            "stats": {
                "packages": 1,
                "signatures": 1,
                "manager_packages": 0  # RENAMED from synthetic_packages
            },
            "mappings": {
                "TestNode::abc123": [  # Now an ARRAY!
                    {
                        "package_id": "test-package",
                        "versions": ["1.0.0"],
                        "rank": 1
                        # No source field = Registry (default)
                    }
                ]
            },
            "packages": {
                "test-package": {
                    "id": "test-package",
                    "display_name": "Test Package",
                    "author": "test",
                    "description": "Test",
                    "repository": "https://github.com/test/test",
                    "downloads": 100,
                    "github_stars": 10,
                    "rating": 5,
                    "license": "MIT",
                    "category": "test",
                    "icon": "https://example.com/icon.png",  # NEW field
                    "tags": [],
                    "status": "active",
                    "created_at": "2025-01-01T00:00:00Z",
                    "versions": {}
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            with open(mappings_path, 'w') as f:
                json.dump(mappings_data, f)

            # Create mock data manager
            from unittest.mock import Mock
            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repository = NodeMappingsRepository(data_manager=mock_data_manager)
            resolver = GlobalNodeResolver(repository)

            # Should load without error
            assert resolver.global_mappings is not None
            assert "TestNode::abc123" in resolver.global_mappings.mappings

            # Check structure
            mapping = resolver.global_mappings.mappings["TestNode::abc123"]
            assert mapping.id == "TestNode::abc123"
            assert len(mapping.packages) == 1
            assert mapping.packages[0].package_id == "test-package"
            assert mapping.packages[0].rank == 1
            assert mapping.packages[0].source is None  # Registry default

    def test_load_multi_package_mapping_with_ranking(self):
        """Multiple packages for same node (NEW v2.0 feature)."""
        mappings_data = {
            "version": "2025.10.10",
            "generated_at": "2025-10-10T00:00:00Z",
            "stats": {
                "packages": 3,
                "signatures": 1,
                "manager_packages": 1
            },
            "mappings": {
                "ReActorFaceSwapOpt::079f3587": [  # Multiple packages!
                    {
                        "package_id": "comfyui-reactor",
                        "versions": ["0.6.1", "0.6.0"],
                        "rank": 1  # Most popular
                    },
                    {
                        "package_id": "comfyui-reactor-node",
                        "versions": ["0.5.2"],
                        "rank": 2
                    },
                    {
                        "package_id": "manager_user_custom-reactor",
                        "versions": [],
                        "rank": 3,
                        "source": "manager"  # Manager package
                    }
                ]
            },
            "packages": {
                "comfyui-reactor": {
                    "id": "comfyui-reactor",
                    "display_name": "ReActor",
                    "repository": "https://github.com/Gourieff/comfyui-reactor-node",
                    "downloads": 5000,
                    "github_stars": 200,
                    "versions": {}
                },
                "comfyui-reactor-node": {
                    "id": "comfyui-reactor-node",
                    "display_name": "ReActor Node",
                    "repository": "https://github.com/other/reactor",
                    "downloads": 1000,
                    "github_stars": 50,
                    "versions": {}
                },
                "manager_user_custom-reactor": {
                    "id": "manager_user_custom-reactor",
                    "display_name": "Custom ReActor",
                    "repository": "https://github.com/user/custom-reactor",
                    "downloads": 0,
                    "github_stars": 0,
                    "source": "manager",  # Manager-only package
                    "versions": {}
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            with open(mappings_path, 'w') as f:
                json.dump(mappings_data, f)

            # Create mock data manager
            from unittest.mock import Mock
            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repository = NodeMappingsRepository(data_manager=mock_data_manager)
            resolver = GlobalNodeResolver(repository)

            mapping = resolver.global_mappings.mappings["ReActorFaceSwapOpt::079f3587"]
            assert len(mapping.packages) == 3

            # Check ranking
            assert mapping.packages[0].rank == 1
            assert mapping.packages[0].package_id == "comfyui-reactor"
            assert mapping.packages[1].rank == 2
            assert mapping.packages[2].rank == 3
            assert mapping.packages[2].source == "manager"


class TestResolutionWithRanking:
    """Test node resolution returns ranked packages."""

    def test_resolve_exact_match_returns_all_ranked_packages(self):
        """When exact match found, return ALL packages sorted by rank."""
        mappings_data = {
            "version": "2025.10.10",
            "mappings": {
                "TestNode::_": [  # Use type-only matching for simplicity
                    {"package_id": "pkg-popular", "versions": ["1.0"], "rank": 1},
                    {"package_id": "pkg-less-popular", "versions": ["1.0"], "rank": 2}
                ]
            },
            "packages": {
                "pkg-popular": {
                    "id": "pkg-popular",
                    "display_name": "Popular Package",
                    "repository": "https://github.com/test/popular",
                    "downloads": 1000,
                    "versions": {}
                },
                "pkg-less-popular": {
                    "id": "pkg-less-popular",
                    "display_name": "Less Popular",
                    "repository": "https://github.com/test/less",
                    "downloads": 100,
                    "versions": {}
                }
            },
            "stats": {}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            with open(mappings_path, 'w') as f:
                json.dump(mappings_data, f)

            # Create mock data manager
            from unittest.mock import Mock
            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repository = NodeMappingsRepository(data_manager=mock_data_manager)
            resolver = GlobalNodeResolver(repository)

            node = WorkflowNode(
                id="1",
                type="TestNode"
                # No inputs = will match type-only key
            )

            # Resolve should return ALL packages
            result = resolver.resolve_single_node_from_mapping(node)

            assert result is not None
            assert len(result) == 2

            # Should be sorted by rank
            assert result[0].package_id == "pkg-popular"
            assert result[0].rank == 1
            assert result[1].package_id == "pkg-less-popular"
            assert result[1].rank == 2

    def test_resolve_type_only_match_returns_ranked_packages(self):
        """Type-only match also returns all ranked packages."""
        mappings_data = {
            "version": "2025.10.10",
            "mappings": {
                "TestNode::_": [  # Type-only signature
                    {"package_id": "pkg-a", "versions": [], "rank": 1},
                    {"package_id": "pkg-b", "versions": [], "rank": 2}
                ]
            },
            "packages": {
                "pkg-a": {"id": "pkg-a", "display_name": "A", "versions": {}},
                "pkg-b": {"id": "pkg-b", "display_name": "B", "versions": {}}
            },
            "stats": {}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            with open(mappings_path, 'w') as f:
                json.dump(mappings_data, f)

            # Create mock data manager
            from unittest.mock import Mock
            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repository = NodeMappingsRepository(data_manager=mock_data_manager)
            resolver = GlobalNodeResolver(repository)
            node = WorkflowNode(id="1", type="TestNode")

            result = resolver.resolve_single_node_from_mapping(node)

            assert result is not None
            assert len(result) == 2
            assert result[0].package_id == "pkg-a"


class TestAutoSelectionLogic:
    """Test auto-selection behavior based on installed nodes + ranking."""

    def test_auto_select_installed_over_higher_rank(self):
        """If rank 2 is installed but rank 1 isn't, auto-select rank 2."""
        mappings_data = {
            "version": "2025.10.10",
            "mappings": {
                "TestNode::_": [  # Use type-only matching
                    {"package_id": "pkg-rank1", "versions": [], "rank": 1},
                    {"package_id": "pkg-rank2", "versions": [], "rank": 2},
                    {"package_id": "pkg-rank3", "versions": [], "rank": 3}
                ]
            },
            "packages": {
                "pkg-rank1": {"id": "pkg-rank1", "display_name": "Rank 1", "versions": {}},
                "pkg-rank2": {"id": "pkg-rank2", "display_name": "Rank 2", "versions": {}},
                "pkg-rank3": {"id": "pkg-rank3", "display_name": "Rank 3", "versions": {}}
            },
            "stats": {}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            with open(mappings_path, 'w') as f:
                json.dump(mappings_data, f)

            # Create mock data manager
            from unittest.mock import Mock
            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repository = NodeMappingsRepository(data_manager=mock_data_manager)
            resolver = GlobalNodeResolver(repository)

            # Simulate rank 2 is installed
            installed_packages = {
                "pkg-rank2": NodeInfo(name="pkg-rank2", source="registry")
            }

            context = NodeResolutionContext(
                installed_packages=installed_packages,
                workflow_name="test"
            )

            node = WorkflowNode(id="1", type="TestNode")  # No inputs = type-only match
            result = resolver.resolve_single_node_with_context(node, context)

            # Should auto-select installed package (rank 2), not rank 1
            assert len(result) == 1
            assert result[0].package_id == "pkg-rank2"

    def test_auto_select_rank_1_when_none_installed(self):
        """If no packages installed, auto-select rank 1."""
        mappings_data = {
            "version": "2025.10.10",
            "mappings": {
                "TestNode::_": [  # Use type-only matching
                    {"package_id": "pkg-rank1", "versions": [], "rank": 1},
                    {"package_id": "pkg-rank2", "versions": [], "rank": 2}
                ]
            },
            "packages": {
                "pkg-rank1": {"id": "pkg-rank1", "versions": {}},
                "pkg-rank2": {"id": "pkg-rank2", "versions": {}}
            },
            "stats": {}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            with open(mappings_path, 'w') as f:
                json.dump(mappings_data, f)

            # Create mock data manager
            from unittest.mock import Mock
            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repository = NodeMappingsRepository(data_manager=mock_data_manager)
            resolver = GlobalNodeResolver(repository)

            # No installed packages
            context = NodeResolutionContext(
                installed_packages={},
                workflow_name="test"
            )

            node = WorkflowNode(id="1", type="TestNode")  # No inputs = type-only match
            result = resolver.resolve_single_node_with_context(node, context)

            # Should auto-select rank 1
            assert len(result) == 1
            assert result[0].package_id == "pkg-rank1"

    def test_return_all_when_auto_select_disabled(self):
        """When auto_select=False, return all ranked packages as ambiguous."""
        # This will be implemented as a context parameter
        mappings_data = {
            "version": "2025.10.10",
            "mappings": {
                "TestNode::_": [  # Use type-only matching
                    {"package_id": "pkg-1", "versions": [], "rank": 1},
                    {"package_id": "pkg-2", "versions": [], "rank": 2}
                ]
            },
            "packages": {
                "pkg-1": {"id": "pkg-1", "versions": {}},
                "pkg-2": {"id": "pkg-2", "versions": {}}
            },
            "stats": {}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            with open(mappings_path, 'w') as f:
                json.dump(mappings_data, f)

            # Create mock data manager
            from unittest.mock import Mock
            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repository = NodeMappingsRepository(data_manager=mock_data_manager)
            resolver = GlobalNodeResolver(repository)

            # Context with auto_select disabled
            context = NodeResolutionContext(
                installed_packages={},
                workflow_name="test",
                auto_select_ambiguous=False  # NEW parameter
            )

            node = WorkflowNode(id="1", type="TestNode")  # No inputs = type-only match
            result = resolver.resolve_single_node_with_context(node, context)

            # Should return ALL packages (treat as ambiguous)
            assert len(result) == 2
            assert result[0].package_id == "pkg-1"
            assert result[1].package_id == "pkg-2"


class TestWorkflowManagerDisambiguation:
    """Test workflow_manager correctly distinguishes registry vs fuzzy search ambiguity."""

    def test_registry_multi_package_auto_resolves(self):
        """Registry mapping with multiple packages should auto-resolve to best match.

        When auto_select_ambiguous=True (default), the resolver should automatically
        pick the highest-ranked package instead of returning all candidates.
        """
        mappings_data = {
            "version": "2025.10.10",
            "mappings": {
                "TestNode::_": [
                    {"package_id": "pkg-1", "versions": ["1.0"], "rank": 1},
                    {"package_id": "pkg-2", "versions": ["1.0"], "rank": 2}
                ]
            },
            "packages": {
                "pkg-1": {
                    "id": "pkg-1",
                    "display_name": "Package 1",
                    "repository": "https://github.com/test/pkg1",
                    "versions": {}
                },
                "pkg-2": {
                    "id": "pkg-2",
                    "display_name": "Package 2",
                    "repository": "https://github.com/test/pkg2",
                    "versions": {}
                }
            },
            "stats": {}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            with open(mappings_path, 'w') as f:
                json.dump(mappings_data, f)

            from unittest.mock import Mock
            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repository = NodeMappingsRepository(data_manager=mock_data_manager)
            resolver = GlobalNodeResolver(repository)

            # Context with auto_select_ambiguous=True (should auto-pick best)
            context = NodeResolutionContext(
                installed_packages={},
                workflow_name="test",
                auto_select_ambiguous=True
            )

            node = WorkflowNode(id="1", type="TestNode")
            result = resolver.resolve_single_node_with_context(node, context)

            # Should auto-select single best package (rank 1)
            assert result is not None
            assert len(result) == 1
            assert result[0].package_id == "pkg-1"
            assert result[0].rank == 1

    def test_fuzzy_search_creates_ambiguous_list(self, test_env, monkeypatch):
        """When resolver returns multiple packages, workflow_manager puts them in ambiguous list.

        This tests the workflow_manager.resolve_workflow() logic: when the resolver
        returns multiple packages (e.g., from fuzzy search with no clear ranking),
        they should be placed in nodes_ambiguous rather than nodes_resolved.
        """
        from comfygit_core.models.workflow import (
            ResolvedNodePackage,
            WorkflowDependencies,
        )

        # Create minimal workflow dependencies with one unknown node
        unknown_node = WorkflowNode(id="1", type="UnknownCustomNode")
        deps = WorkflowDependencies(
            workflow_name="test-workflow",
            builtin_nodes=[],
            non_builtin_nodes=[unknown_node],
            found_models=[]
        )

        # Mock the resolver to return 2 packages with rank=None (simulates fuzzy search)
        # The key is that returning multiple packages should trigger ambiguity handling
        def mock_resolve(node, _ctx):
            if node.type == "UnknownCustomNode":
                return [
                    ResolvedNodePackage(
                        node_type="UnknownCustomNode",
                        package_id="fuzzy-match-1",
                        match_type="fuzzy",
                        match_confidence=0.7,
                        rank=None  # No registry rank (fuzzy search result)
                    ),
                    ResolvedNodePackage(
                        node_type="UnknownCustomNode",
                        package_id="fuzzy-match-2",
                        match_type="fuzzy",
                        match_confidence=0.65,
                        rank=None  # No registry rank (fuzzy search result)
                    )
                ]
            return None

        # Patch the resolver on the workflow_manager
        monkeypatch.setattr(
            test_env.workflow_manager.global_node_resolver,
            "resolve_single_node_with_context",
            mock_resolve
        )

        # Run resolution
        result = test_env.workflow_manager.resolve_workflow(deps)

        # Multiple packages should go to nodes_ambiguous, not nodes_resolved
        assert len(result.nodes_resolved) == 0, "Should not have resolved nodes"
        assert len(result.nodes_ambiguous) == 1, "Should have one ambiguous node group"
        assert len(result.nodes_ambiguous[0]) == 2, "Ambiguous group should have 2 packages"
        assert result.nodes_ambiguous[0][0].package_id == "fuzzy-match-1"
        assert result.nodes_ambiguous[0][1].package_id == "fuzzy-match-2"


class TestRankFieldPersistence:
    """Test that rank information is preserved through resolution."""

    def test_resolved_package_includes_rank(self):
        """ResolvedNodePackage should include rank field."""
        mappings_data = {
            "version": "2025.10.10",
            "mappings": {
                "TestNode::_": [  # Use type-only matching
                    {"package_id": "pkg-1", "versions": [], "rank": 1}
                ]
            },
            "packages": {
                "pkg-1": {"id": "pkg-1", "versions": {}}
            },
            "stats": {}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            with open(mappings_path, 'w') as f:
                json.dump(mappings_data, f)

            # Create mock data manager
            from unittest.mock import Mock
            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repository = NodeMappingsRepository(data_manager=mock_data_manager)
            resolver = GlobalNodeResolver(repository)
            node = WorkflowNode(id="1", type="TestNode")  # No inputs = type-only match

            result = resolver.resolve_single_node_from_mapping(node)

            assert result[0].rank == 1


class TestManagerSourceHandling:
    """Test handling of Manager-only packages (source='manager')."""

    def test_manager_package_loaded_correctly(self):
        """Manager packages should have source='manager' and empty versions."""
        mappings_data = {
            "version": "2025.10.10",
            "mappings": {
                "TestNode::_": [
                    {
                        "package_id": "manager_user_repo",
                        "versions": [],  # Manager has no versions
                        "rank": 1,
                        "source": "manager"
                    }
                ]
            },
            "packages": {
                "manager_user_repo": {
                    "id": "manager_user_repo",
                    "display_name": "Manager Package",
                    "repository": "https://github.com/user/repo",
                    "downloads": 0,
                    "github_stars": 0,
                    "source": "manager",  # Package-level source
                    "versions": {}
                }
            },
            "stats": {"manager_packages": 1}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            with open(mappings_path, 'w') as f:
                json.dump(mappings_data, f)

            # Create mock data manager
            from unittest.mock import Mock
            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repository = NodeMappingsRepository(data_manager=mock_data_manager)
            resolver = GlobalNodeResolver(repository)

            mapping = resolver.global_mappings.mappings["TestNode::_"]
            assert mapping.packages[0].source == "manager"

            package = resolver.global_mappings.packages["manager_user_repo"]
            assert package.source == "manager"

    def test_registry_package_has_no_source_field(self):
        """Registry packages should NOT have source field (or None)."""
        mappings_data = {
            "version": "2025.10.10",
            "mappings": {
                "TestNode::_": [
                    {
                        "package_id": "registry-pkg",
                        "versions": ["1.0"],
                        "rank": 1
                        # No source field = Registry
                    }
                ]
            },
            "packages": {
                "registry-pkg": {
                    "id": "registry-pkg",
                    "display_name": "Registry Package",
                    "downloads": 100,
                    # No source field = Registry
                    "versions": {}
                }
            },
            "stats": {}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            with open(mappings_path, 'w') as f:
                json.dump(mappings_data, f)

            # Create mock data manager
            from unittest.mock import Mock
            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repository = NodeMappingsRepository(data_manager=mock_data_manager)
            resolver = GlobalNodeResolver(repository)

            mapping = resolver.global_mappings.mappings["TestNode::_"]
            assert mapping.packages[0].source is None

            package = resolver.global_mappings.packages["registry-pkg"]
            assert package.source is None


class TestBackwardCompatibility:
    """Test edge cases and backward compatibility scenarios."""

    def test_single_package_behaves_like_v1(self):
        """Single package mapping should behave same as v1.0 (clean resolution)."""
        mappings_data = {
            "version": "2025.10.10",
            "mappings": {
                "TestNode::_": [  # Use type-only matching
                    {"package_id": "only-package", "versions": [], "rank": 1}
                ]
            },
            "packages": {
                "only-package": {"id": "only-package", "versions": {}}
            },
            "stats": {}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            with open(mappings_path, 'w') as f:
                json.dump(mappings_data, f)

            # Create mock data manager
            from unittest.mock import Mock
            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repository = NodeMappingsRepository(data_manager=mock_data_manager)
            resolver = GlobalNodeResolver(repository)

            context = NodeResolutionContext(
                installed_packages={},
                workflow_name="test"
            )

            node = WorkflowNode(id="1", type="TestNode")  # No inputs = type-only match
            result = resolver.resolve_single_node_with_context(node, context)

            # Should cleanly resolve to single package
            assert len(result) == 1
            assert result[0].package_id == "only-package"

    def test_empty_packages_list_returns_none(self):
        """Empty packages list should return None (not found)."""
        mappings_data = {
            "version": "2025.10.10",
            "mappings": {
                "TestNode::abc": []  # Empty list
            },
            "packages": {},
            "stats": {}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            with open(mappings_path, 'w') as f:
                json.dump(mappings_data, f)

            # Create mock data manager
            from unittest.mock import Mock
            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repository = NodeMappingsRepository(data_manager=mock_data_manager)
            resolver = GlobalNodeResolver(repository)
            node = WorkflowNode(id="1", type="TestNode", inputs=[])

            result = resolver.resolve_single_node_from_mapping(node)

            # Empty list should be treated as "not found"
            assert result is None
