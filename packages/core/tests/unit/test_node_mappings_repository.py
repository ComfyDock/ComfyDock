"""Unit tests for NodeMappingsRepository - data access layer for node mappings.

Tests the repository pattern extraction from GlobalNodeResolver.
"""

import json
from unittest.mock import Mock

import pytest
from comfygit_core.repositories.node_mappings_repository import NodeMappingsRepository


class TestNodeMappingsRepositoryLoading:
    """Test repository loads and caches mappings data."""

    def test_loads_mappings_from_json_file(self, tmp_path):
        """Repository should load global mappings from JSON file."""
        # ARRANGE
        mappings_file = tmp_path / "node_mappings.json"
        global_data = {
            "version": "2025.01.01",
            "generated_at": "2025-01-01T00:00:00",
            "stats": {
                "packages": 2,
                "signatures": 10,
                "total_nodes": 50
            },
            "mappings": {
                "TestNode::_": [
                    {
                        "package_id": "test-package",
                        "versions": ["1.0.0"],
                        "rank": 1,
                        "source": "registry"
                    }
                ]
            },
            "packages": {
                "test-package": {
                    "id": "test-package",
                    "display_name": "Test Package",
                    "repository": "https://github.com/test/package",
                    "versions": {}
                }
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        # ACT
        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repo = NodeMappingsRepository(data_manager=mock_data_manager)

        # ASSERT
        assert repo.global_mappings is not None
        assert repo.global_mappings.version == "2025.01.01"
        assert "TestNode::_" in repo.global_mappings.mappings
        assert "test-package" in repo.global_mappings.packages

    def test_raises_error_if_file_not_found(self, tmp_path):
        """Should raise CDRegistryDataError if mappings file doesn't exist."""
        from comfygit_core.models.exceptions import CDRegistryDataError

        # ARRANGE
        non_existent_file = tmp_path / "does_not_exist.json"
        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = non_existent_file

        # ACT & ASSERT
        with pytest.raises(CDRegistryDataError) as exc_info:
            NodeMappingsRepository(data_manager=mock_data_manager)

        # Verify exception has proper context
        error = exc_info.value
        assert error.cache_path == str(non_existent_file.parent)
        assert error.can_retry is True

    def test_caches_loaded_mappings(self, tmp_path):
        """Should cache mappings to avoid reloading."""
        # ARRANGE
        mappings_file = tmp_path / "node_mappings.json"
        global_data = {
            "version": "test",
            "generated_at": "2025-01-01",
            "stats": {},
            "mappings": {},
            "packages": {}
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repo = NodeMappingsRepository(data_manager=mock_data_manager)

        # ACT: Access mappings multiple times
        mappings1 = repo.global_mappings
        mappings2 = repo.global_mappings

        # ASSERT: Should return same cached object
        assert mappings1 is mappings2, "Should cache and reuse loaded mappings"


class TestNodeMappingsRepositoryGitHubUrl:
    """Test GitHub URL resolution and normalization."""

    def test_builds_github_to_registry_map(self, tmp_path):
        """Should build reverse mapping from GitHub URLs to packages."""
        # ARRANGE
        mappings_file = tmp_path / "node_mappings.json"
        global_data = {
            "version": "test",
            "generated_at": "2025-01-01",
            "stats": {},
            "mappings": {},
            "packages": {
                "package-a": {
                    "id": "package-a",
                    "repository": "https://github.com/owner/repo-a",
                    "versions": {}
                },
                "package-b": {
                    "id": "package-b",
                    "repository": "https://github.com/owner/repo-b.git",  # With .git
                    "versions": {}
                }
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        # ACT
        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repo = NodeMappingsRepository(data_manager=mock_data_manager)

        # ASSERT
        package_a = repo.resolve_github_url("https://github.com/owner/repo-a")
        assert package_a is not None
        assert package_a.id == "package-a"

    def test_normalizes_github_urls_for_lookup(self, tmp_path):
        """Should normalize GitHub URLs (remove .git, handle SSH)."""
        # ARRANGE
        mappings_file = tmp_path / "node_mappings.json"
        global_data = {
            "version": "test",
            "generated_at": "2025-01-01",
            "stats": {},
            "mappings": {},
            "packages": {
                "test-pkg": {
                    "id": "test-pkg",
                    "repository": "https://github.com/owner/repo",
                    "versions": {}
                }
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repo = NodeMappingsRepository(data_manager=mock_data_manager)

        # ACT: Try different URL formats
        result1 = repo.resolve_github_url("https://github.com/owner/repo.git")
        result2 = repo.resolve_github_url("git@github.com:owner/repo.git")
        result3 = repo.resolve_github_url("https://github.com/owner/repo")

        # ASSERT: All should resolve to same package
        assert result1 is not None and result1.id == "test-pkg"
        assert result2 is not None and result2.id == "test-pkg"
        assert result3 is not None and result3.id == "test-pkg"

    def test_get_github_url_for_package(self, tmp_path):
        """Should retrieve GitHub URL for a package ID."""
        # ARRANGE
        mappings_file = tmp_path / "node_mappings.json"
        global_data = {
            "version": "test",
            "generated_at": "2025-01-01",
            "stats": {},
            "mappings": {},
            "packages": {
                "my-package": {
                    "id": "my-package",
                    "repository": "https://github.com/user/my-package",
                    "versions": {}
                }
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repo = NodeMappingsRepository(data_manager=mock_data_manager)

        # ACT
        url = repo.get_github_url_for_package("my-package")

        # ASSERT
        assert url == "https://github.com/user/my-package"


class TestNodeMappingsRepositoryQueries:
    """Test simple query methods for accessing mappings data."""

    def test_get_package_by_id(self, tmp_path):
        """Should retrieve package by ID."""
        # ARRANGE
        mappings_file = tmp_path / "node_mappings.json"
        global_data = {
            "version": "test",
            "generated_at": "2025-01-01",
            "stats": {},
            "mappings": {},
            "packages": {
                "target-pkg": {
                    "id": "target-pkg",
                    "display_name": "Target Package",
                    "description": "Test package",
                    "versions": {}
                }
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repo = NodeMappingsRepository(data_manager=mock_data_manager)

        # ACT
        package = repo.get_package("target-pkg")

        # ASSERT
        assert package is not None
        assert package.id == "target-pkg"
        assert package.display_name == "Target Package"

    def test_get_package_returns_none_if_not_found(self, tmp_path):
        """Should return None if package doesn't exist."""
        # ARRANGE
        mappings_file = tmp_path / "node_mappings.json"
        global_data = {
            "version": "test",
            "generated_at": "2025-01-01",
            "stats": {},
            "mappings": {},
            "packages": {}
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repo = NodeMappingsRepository(data_manager=mock_data_manager)

        # ACT
        package = repo.get_package("non-existent")

        # ASSERT
        assert package is None

    def test_get_mapping_by_key(self, tmp_path):
        """Should retrieve mapping by node key."""
        # ARRANGE
        mappings_file = tmp_path / "node_mappings.json"
        global_data = {
            "version": "test",
            "generated_at": "2025-01-01",
            "stats": {},
            "mappings": {
                "CustomNode::abc": [
                    {
                        "package_id": "pkg-1",
                        "versions": ["1.0"],
                        "rank": 1
                    }
                ]
            },
            "packages": {}
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repo = NodeMappingsRepository(data_manager=mock_data_manager)

        # ACT
        mapping = repo.get_mapping("CustomNode::abc")

        # ASSERT
        assert mapping is not None
        assert len(mapping.packages) == 1
        assert mapping.packages[0].package_id == "pkg-1"

    def test_get_all_packages(self, tmp_path):
        """Should return all packages as dict."""
        # ARRANGE
        mappings_file = tmp_path / "node_mappings.json"
        global_data = {
            "version": "test",
            "generated_at": "2025-01-01",
            "stats": {},
            "mappings": {},
            "packages": {
                "pkg-a": {"id": "pkg-a", "versions": {}},
                "pkg-b": {"id": "pkg-b", "versions": {}},
                "pkg-c": {"id": "pkg-c", "versions": {}}
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repo = NodeMappingsRepository(data_manager=mock_data_manager)

        # ACT
        all_packages = repo.get_all_packages()

        # ASSERT
        assert len(all_packages) == 3
        assert "pkg-a" in all_packages
        assert "pkg-b" in all_packages
        assert "pkg-c" in all_packages


class TestNodeMappingsRepositoryEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_package_without_repository(self, tmp_path):
        """Should handle packages without repository field."""
        # ARRANGE
        mappings_file = tmp_path / "node_mappings.json"
        global_data = {
            "version": "test",
            "generated_at": "2025-01-01",
            "stats": {},
            "mappings": {},
            "packages": {
                "no-repo-pkg": {
                    "id": "no-repo-pkg",
                    "display_name": "No Repo",
                    "versions": {}
                    # No repository field
                }
            }
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        # ACT & ASSERT: Should not crash
        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repo = NodeMappingsRepository(data_manager=mock_data_manager)
        package = repo.get_package("no-repo-pkg")
        assert package is not None
        assert package.repository is None

    def test_handles_empty_mappings_file(self, tmp_path):
        """Should handle file with minimal data."""
        # ARRANGE
        mappings_file = tmp_path / "node_mappings.json"
        global_data = {
            "version": "test",
            "generated_at": "2025-01-01",
            "stats": {},
            "mappings": {},
            "packages": {}
        }

        with open(mappings_file, 'w') as f:
            json.dump(global_data, f)

        # ACT & ASSERT: Should not crash
        mock_data_manager = Mock()
        mock_data_manager.get_mappings_path.return_value = mappings_file
        repo = NodeMappingsRepository(data_manager=mock_data_manager)
        assert repo.get_all_packages() == {}
        assert repo.get_package("anything") is None
