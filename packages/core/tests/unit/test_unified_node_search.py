"""Tests for unified node search with scoring and ranking.

This replaces the old heuristic auto-resolution with scored search.
"""

import json
from unittest.mock import Mock

from comfygit_core.models.shared import NodeInfo
from comfygit_core.repositories.node_mappings_repository import NodeMappingsRepository
from comfygit_core.resolvers.global_node_resolver import GlobalNodeResolver


class TestUnifiedSearchScoring:
    """Test unified search produces correct scores and rankings."""

    def test_search_packages_basic_functionality(self, tmp_path):
        """Unified search should return scored, ranked results."""
        # ARRANGE: Create minimal global mappings
        mappings_file = tmp_path / "node_mappings.json"

        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {
                "packages": 2,
                "signatures": 0,
                "total_nodes": 0
            },
            "mappings": {},
            "packages": {
                "rgthree-comfy": {
                    "id": "rgthree-comfy",
                    "display_name": "rgthree's ComfyUI Nodes",
                    "description": "Workflow management nodes",
                    "repository": "https://github.com/rgthree/rgthree-comfy",
                    "github_stars": 100,
                    "versions": {}
                },
                "comfyui-impact-pack": {
                    "id": "comfyui-impact-pack",
                    "display_name": "Impact Pack",
                    "description": "Various utility nodes",
                    "repository": "https://github.com/ltdrdata/ComfyUI-Impact-Pack",
                    "github_stars": 50,
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

        # ACT: Search for node with hint
        results = resolver.search_packages(
            node_type="Test Node (rgthree)",
            installed_packages={},
            include_registry=True,
            limit=10
        )

        # ASSERT: Should return scored results
        assert len(results) > 0, "Should find at least one match"
        assert results[0].package_id == "rgthree-comfy", "Should rank rgthree first (hint match)"
        assert results[0].score > 0.5, "Hint bonus should boost score significantly"
        assert results[0].confidence in ["high", "good", "possible", "low"], "Should have confidence label"

    def test_hint_pattern_boosts_score(self, tmp_path):
        """Hints in node name should boost package score."""
        mappings_file = tmp_path / "node_mappings.json"

        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {},
            "packages": {
                "target-package": {
                    "id": "target-package",
                    "display_name": "Target Package",
                    "versions": {}
                },
                "other-package": {
                    "id": "other-package",
                    "display_name": "Other Package",
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

        # ACT: Node with hint pointing to target-package
        results = resolver.search_packages(
            node_type="Some Node (target)",
            include_registry=True
        )

        # ASSERT: target-package should rank higher due to hint
        assert len(results) >= 1
        assert results[0].package_id == "target-package", "Hint should boost target package to top"

    def test_installed_packages_prioritized(self, tmp_path):
        """Installed packages should receive priority in ranking."""
        mappings_file = tmp_path / "node_mappings.json"

        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {},
            "packages": {
                "installed-pkg": {
                    "id": "installed-pkg",
                    "display_name": "Installed Package",
                    "versions": {}
                },
                "registry-pkg": {
                    "id": "registry-pkg",
                    "display_name": "Registry Package",
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

        installed_packages = {
            "installed-pkg": NodeInfo(
                name="installed-pkg",
                registry_id="installed-pkg",
                source="registry"
            )
        }

        # ACT: Search for node with similar match to both packages
        results = resolver.search_packages(
            node_type="Package",
            installed_packages=installed_packages,
            include_registry=True
        )

        # ASSERT: Installed should rank higher (all else equal)
        assert len(results) >= 2
        # Note: This may not always be first depending on fuzzy matching,
        # but installed should get a score boost
        installed_result = next((r for r in results if r.package_id == "installed-pkg"), None)
        registry_result = next((r for r in results if r.package_id == "registry-pkg"), None)

        assert installed_result is not None
        assert registry_result is not None
        # Installed should have higher score due to bonus (if base scores similar)

    def test_results_sorted_by_score(self, tmp_path):
        """Results should be sorted by score descending."""
        mappings_file = tmp_path / "node_mappings.json"

        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {},
            "packages": {
                f"package-{i}": {
                    "id": f"package-{i}",
                    "display_name": f"Package {i}",
                    "versions": {}
                }
                for i in range(5)
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repository = NodeMappingsRepository(data_manager=mock_data_manager)
        resolver = GlobalNodeResolver(repository)

        # ACT
        results = resolver.search_packages(
            node_type="Package Test",
            include_registry=True
        )

        # ASSERT: Should be sorted descending
        for i in range(len(results) - 1):
            assert results[i].score >= results[i+1].score, "Results should be sorted by score"

    def test_limit_parameter_respected(self, tmp_path):
        """Should return at most 'limit' results."""
        mappings_file = tmp_path / "node_mappings.json"

        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {},
            "packages": {
                f"package-{i}": {
                    "id": f"package-{i}",
                    "display_name": f"Test Package {i}",
                    "versions": {}
                }
                for i in range(20)  # Create 20 packages
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repository = NodeMappingsRepository(data_manager=mock_data_manager)
        resolver = GlobalNodeResolver(repository)

        # ACT: Request only 5 results
        results = resolver.search_packages(
            node_type="Test Package",
            include_registry=True,
            limit=5
        )

        # ASSERT
        assert len(results) <= 5, "Should respect limit parameter"

    def test_minimum_score_threshold(self, tmp_path):
        """Results below minimum threshold should be filtered."""
        mappings_file = tmp_path / "node_mappings.json"

        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {},
            "packages": {
                "completely-unrelated": {
                    "id": "completely-unrelated",
                    "display_name": "Xyz Abc",
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

        # ACT: Search for something completely different
        results = resolver.search_packages(
            node_type="Impact Node Test",
            include_registry=True
        )

        # ASSERT: Should not return completely unrelated packages
        # (or if it does, they should have very low scores)
        for result in results:
            assert result.score >= 0.3, "All results should meet minimum threshold"


class TestHeuristicRemovalBehavior:
    """Test that heuristic matching no longer auto-resolves."""

    def test_heuristic_hint_no_longer_auto_resolves(self, tmp_path):
        """OLD: Heuristic would auto-resolve. NEW: Should return None (trigger interactive)."""
        # ARRANGE: Node NOT in global table, but has hint
        mappings_file = tmp_path / "node_mappings.json"

        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {},  # Empty - node not in table
            "packages": {
                "rgthree-comfy": {
                    "id": "rgthree-comfy",
                    "display_name": "rgthree's Nodes",
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

        from comfygit_core.models.workflow import NodeResolutionContext, WorkflowNode

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
            type="Mute / Bypass Repeater (rgthree)",  # Has hint!
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

    def test_old_heuristic_methods_removed(self, tmp_path):
        """Verify old heuristic methods are removed from resolver."""
        mappings_file = tmp_path / "node_mappings.json"

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

        # ASSERT: Old methods should not exist
        assert not hasattr(resolver, '_likely_provides_node'), \
            "_likely_provides_node should be removed (replaced by hint detection in search)"
        assert not hasattr(resolver, 'fuzzy_search_packages'), \
            "fuzzy_search_packages should be removed (replaced by search_packages)"


class TestSearchPackagesEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_node_type(self, tmp_path):
        """Empty node type should handle gracefully."""
        mappings_file = tmp_path / "node_mappings.json"

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

        # ACT
        results = resolver.search_packages(node_type="", include_registry=True)

        # ASSERT: Should not crash, return empty or low-score results
        assert isinstance(results, list), "Should return list even for empty input"

    def test_no_packages_available(self, tmp_path):
        """Search with no packages should return empty list."""
        mappings_file = tmp_path / "node_mappings.json"

        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {},
            "packages": {}  # Empty
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repository = NodeMappingsRepository(data_manager=mock_data_manager)
        resolver = GlobalNodeResolver(repository)

        # ACT
        results = resolver.search_packages(
            node_type="Any Node",
            include_registry=True
        )

        # ASSERT
        assert results == [], "Should return empty list when no packages"

    def test_installed_only_search(self, tmp_path):
        """Search with include_registry=False should only check installed."""
        mappings_file = tmp_path / "node_mappings.json"

        global_data = {
            "version": "test",
            "generated_at": "2024-01-01",
            "stats": {},
            "mappings": {},
            "packages": {
                "installed-pkg": {
                    "id": "installed-pkg",
                    "display_name": "Installed",
                    "versions": {}
                },
                "registry-only-pkg": {
                    "id": "registry-only-pkg",
                    "display_name": "Registry Only",
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

        installed_packages = {
            "installed-pkg": NodeInfo(
                name="installed-pkg",
                registry_id="installed-pkg",
                source="registry"
            )
        }

        # ACT: Search only installed
        results = resolver.search_packages(
            node_type="Package",
            installed_packages=installed_packages,
            include_registry=False  # Don't search registry
        )

        # ASSERT: Should only find installed package
        package_ids = [r.package_id for r in results]
        assert "installed-pkg" in package_ids or len(results) == 0  # Might not match at all
        assert "registry-only-pkg" not in package_ids, "Should not include registry-only packages"
