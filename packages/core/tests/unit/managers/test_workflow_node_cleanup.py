"""Tests for workflow node reference cleanup when nodes are removed.

When a node is removed via NodeManager.remove_node(), workflow nodes lists
in pyproject.toml should be updated to remove orphaned references.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pytest
import tomlkit
from comfygit_core.managers.node_manager import NodeManager
from comfygit_core.managers.pyproject_manager import PyprojectManager
from comfygit_core.models.exceptions import CDNodeNotFoundError


@pytest.fixture
def temp_pyproject():
    """Create a temporary pyproject.toml for testing."""
    with TemporaryDirectory() as tmpdir:
        pyproject_path = Path(tmpdir) / "pyproject.toml"

        initial_config = {
            "project": {
                "name": "test-project",
                "version": "0.1.0",
                "requires-python": ">=3.11",
                "dependencies": [],
            },
            "tool": {
                "comfygit": {
                    "comfyui_version": "v0.3.60",
                    "python_version": "3.11",
                }
            }
        }

        with open(pyproject_path, 'w') as f:
            tomlkit.dump(initial_config, f)

        yield pyproject_path


class TestCleanupNodeReferences:
    """Test WorkflowHandler.cleanup_node_references method."""

    def test_cleanup_removes_node_from_single_workflow(self, temp_pyproject):
        """Removing a node should update workflows that reference it."""
        manager = PyprojectManager(temp_pyproject)

        # Set up workflow with nodes list
        manager.workflows.set_node_packs("test_workflow", {"shared-node", "other-node"})

        # Clean up references to shared-node
        count = manager.workflows.cleanup_node_references("shared-node")

        # Should have updated 1 workflow
        assert count == 1

        # Workflow should no longer contain the removed node
        workflow_data = manager.workflows.get_workflow("test_workflow")
        nodes_list = workflow_data.get("nodes", [])
        assert "shared-node" not in nodes_list
        assert "other-node" in nodes_list

    def test_cleanup_updates_multiple_workflows(self, temp_pyproject):
        """cleanup_node_references should update ALL workflows referencing the node."""
        manager = PyprojectManager(temp_pyproject)

        # Set up multiple workflows with shared node
        manager.workflows.set_node_packs("workflow1", {"shared-node", "other-node"})
        manager.workflows.set_node_packs("workflow2", {"shared-node"})
        manager.workflows.set_node_packs("workflow3", {"different-node"})

        # Clean up references to shared-node
        count = manager.workflows.cleanup_node_references("shared-node")

        # Should have updated 2 workflows
        assert count == 2

        # Check workflow1 - should have only other-node
        wf1 = manager.workflows.get_workflow("workflow1")
        assert "shared-node" not in wf1.get("nodes", [])
        assert "other-node" in wf1.get("nodes", [])

        # Check workflow2 - nodes key should be removed (empty after cleanup)
        wf2 = manager.workflows.get_workflow("workflow2")
        # Workflow might be None if completely empty, or have no nodes key
        assert wf2 is None or wf2.get("nodes") is None or len(wf2.get("nodes", [])) == 0

        # Check workflow3 - should be unchanged
        wf3 = manager.workflows.get_workflow("workflow3")
        assert "different-node" in wf3.get("nodes", [])

    def test_cleanup_case_insensitive_matching(self, temp_pyproject):
        """Node identifier matching should be case-insensitive."""
        manager = PyprojectManager(temp_pyproject)

        # Set up workflow with mixed-case node name
        manager.workflows.set_node_packs("test_workflow", {"ComfyUI-Test-Node", "other-node"})

        # Clean up with different casing
        count = manager.workflows.cleanup_node_references("comfyui-test-node")

        # Should still find and remove it
        assert count == 1
        workflow_data = manager.workflows.get_workflow("test_workflow")
        nodes_list = workflow_data.get("nodes", [])
        assert len([n for n in nodes_list if n.lower() == "comfyui-test-node"]) == 0
        assert "other-node" in nodes_list

    def test_cleanup_with_alternate_name(self, temp_pyproject):
        """Should remove references using both identifier and alternate name."""
        manager = PyprojectManager(temp_pyproject)

        # Workflow references directory name, not registry ID
        manager.workflows.set_node_packs("test_workflow", {"ComfyUI-Foo", "other-node"})

        # Clean up using registry ID and directory name
        count = manager.workflows.cleanup_node_references("comfyui-foo-registry", "ComfyUI-Foo")

        # Should find the node using the alternate name
        assert count == 1
        workflow_data = manager.workflows.get_workflow("test_workflow")
        nodes_list = workflow_data.get("nodes", [])
        assert "ComfyUI-Foo" not in nodes_list

    def test_cleanup_returns_zero_when_no_workflows(self, temp_pyproject):
        """Should return 0 when no workflows exist."""
        manager = PyprojectManager(temp_pyproject)

        count = manager.workflows.cleanup_node_references("nonexistent-node")

        assert count == 0

    def test_cleanup_returns_zero_when_node_not_in_any_workflow(self, temp_pyproject):
        """Should return 0 when node isn't in any workflow."""
        manager = PyprojectManager(temp_pyproject)

        # Set up workflow without the node we'll remove
        manager.workflows.set_node_packs("test_workflow", {"other-node"})

        count = manager.workflows.cleanup_node_references("nonexistent-node")

        assert count == 0
        # Workflow should be unchanged
        workflow_data = manager.workflows.get_workflow("test_workflow")
        assert "other-node" in workflow_data.get("nodes", [])

    def test_cleanup_removes_nodes_key_when_last_node_removed(self, temp_pyproject):
        """When last node is removed, nodes key should be deleted entirely."""
        manager = PyprojectManager(temp_pyproject)

        # Set up workflow with only one node
        manager.workflows.set_node_packs("test_workflow", {"only-node"})

        # Remove that node
        count = manager.workflows.cleanup_node_references("only-node")

        assert count == 1
        workflow_data = manager.workflows.get_workflow("test_workflow")
        # nodes key should not exist (not just be empty)
        # workflow_data might be None if the workflow section became empty
        assert workflow_data is None or "nodes" not in workflow_data or workflow_data.get("nodes") is None


class TestNodeManagerWorkflowCleanup:
    """Test NodeManager.remove_node() integration with workflow cleanup."""

    @pytest.fixture
    def node_manager_setup(self, tmp_path):
        """Create a NodeManager with mocked dependencies."""
        pyproject_path = tmp_path / "pyproject.toml"
        custom_nodes_path = tmp_path / "custom_nodes"
        custom_nodes_path.mkdir()

        # Create initial pyproject with a tracked node and workflow
        initial_config = {
            "project": {
                "name": "test-project",
                "version": "0.1.0",
                "requires-python": ">=3.11",
                "dependencies": [],
            },
            "tool": {
                "comfygit": {
                    "comfyui_version": "v0.3.60",
                    "python_version": "3.11",
                    "nodes": {
                        "test-node": {
                            "name": "test-node",
                            "version": "1.0.0",
                            "source": "registry",
                        }
                    },
                    "workflows": {
                        "my_workflow": {
                            "path": "workflows/my_workflow.json",
                            "nodes": ["test-node", "other-node"]
                        }
                    }
                }
            }
        }

        with open(pyproject_path, 'w') as f:
            tomlkit.dump(initial_config, f)

        # Create node directory
        (custom_nodes_path / "test-node").mkdir()

        # Create mocked pyproject manager
        pyproject = PyprojectManager(pyproject_path)

        # Create mocked uv manager
        mock_uv = Mock()
        mock_uv.sync_project = Mock()

        # Create mocked node lookup
        mock_node_lookup = Mock()

        # Create mocked resolution tester
        mock_resolution_tester = Mock()

        # Create mocked node repository
        mock_node_repository = Mock()

        node_manager = NodeManager(
            pyproject=pyproject,
            uv=mock_uv,
            node_lookup=mock_node_lookup,
            resolution_tester=mock_resolution_tester,
            custom_nodes_path=custom_nodes_path,
            node_repository=mock_node_repository,
        )

        return {
            "node_manager": node_manager,
            "pyproject": pyproject,
            "uv": mock_uv,
            "custom_nodes_path": custom_nodes_path,
            "pyproject_path": pyproject_path,
        }

    def test_remove_node_cleans_workflow_references(self, node_manager_setup):
        """When a tracked node is removed, workflow nodes lists should be updated."""
        nm = node_manager_setup["node_manager"]
        pyproject = node_manager_setup["pyproject"]

        # Remove the node
        result = nm.remove_node("test-node")

        # Node should be removed
        assert result.identifier == "test-node"

        # Workflow should no longer reference the removed node
        workflow_data = pyproject.workflows.get_workflow("my_workflow")
        nodes_list = workflow_data.get("nodes", [])
        assert "test-node" not in nodes_list
        assert "other-node" in nodes_list
        node_manager_setup["uv"].sync_project.assert_called_once()
        assert node_manager_setup["uv"].sync_project.call_args.kwargs["skip_optional_overlays"] is True

    def test_remove_node_can_sync_with_optional_overlays(self, node_manager_setup):
        """Manager-driven removals can resolve with active local/optional overlays."""
        nm = node_manager_setup["node_manager"]

        result = nm.remove_node("test-node", skip_optional_overlays=False)

        assert result.identifier == "test-node"
        node_manager_setup["uv"].sync_project.assert_called_once()
        assert node_manager_setup["uv"].sync_project.call_args.kwargs["skip_optional_overlays"] is False

    def test_remove_node_returns_partial_result_when_sync_fails(self, node_manager_setup):
        """A post-removal sync error should not mask that the node was removed."""
        nm = node_manager_setup["node_manager"]
        pyproject = node_manager_setup["pyproject"]
        node_manager_setup["uv"].sync_project.side_effect = RuntimeError("sync failed")

        result = nm.remove_node("test-node")

        assert result.identifier == "test-node"
        assert result.sync_succeeded is False
        assert result.sync_error == "sync failed"
        assert result.needs_sync is True
        assert "test-node" not in pyproject.nodes.get_existing()


class TestRemoveUntrackedNode:
    """Test removing untracked nodes (filesystem only)."""

    @pytest.fixture
    def node_manager_with_untracked(self, tmp_path):
        """Create a NodeManager with an untracked node on filesystem."""
        pyproject_path = tmp_path / "pyproject.toml"
        custom_nodes_path = tmp_path / "custom_nodes"
        custom_nodes_path.mkdir()

        # Create pyproject WITHOUT the node tracked
        initial_config = {
            "project": {
                "name": "test-project",
                "version": "0.1.0",
                "requires-python": ">=3.11",
                "dependencies": [],
            },
            "tool": {
                "comfygit": {
                    "comfyui_version": "v0.3.60",
                    "python_version": "3.11",
                }
            }
        }

        with open(pyproject_path, 'w') as f:
            tomlkit.dump(initial_config, f)

        # Create untracked node directory
        (custom_nodes_path / "orphaned-node").mkdir()
        (custom_nodes_path / "orphaned-node" / "__init__.py").write_text("# test")

        pyproject = PyprojectManager(pyproject_path)

        mock_uv = Mock()
        mock_uv.sync_project = Mock()

        node_manager = NodeManager(
            pyproject=pyproject,
            uv=mock_uv,
            node_lookup=Mock(),
            resolution_tester=Mock(),
            custom_nodes_path=custom_nodes_path,
            node_repository=Mock(),
        )

        return {
            "node_manager": node_manager,
            "pyproject": pyproject,
            "custom_nodes_path": custom_nodes_path,
        }

    def test_remove_untracked_node(self, node_manager_with_untracked):
        """Untracked nodes (filesystem only) should be removable."""
        nm = node_manager_with_untracked["node_manager"]
        custom_nodes_path = node_manager_with_untracked["custom_nodes_path"]

        # Remove untracked node
        result = nm.remove_node("orphaned-node")

        # Directory should be removed
        assert not (custom_nodes_path / "orphaned-node").exists()
        assert result.source == "untracked"
        assert result.filesystem_action == "deleted"

    def test_remove_disabled_node(self, node_manager_with_untracked):
        """Disabled nodes (.disabled suffix) should be removable."""
        nm = node_manager_with_untracked["node_manager"]
        custom_nodes_path = node_manager_with_untracked["custom_nodes_path"]

        # Create .disabled node directory
        (custom_nodes_path / "my-node.disabled").mkdir()

        # Remove by base name (without .disabled)
        result = nm.remove_node("my-node")

        # .disabled directory should be removed
        assert not (custom_nodes_path / "my-node.disabled").exists()
        assert result.filesystem_action == "deleted"

    def test_remove_nonexistent_node_raises_error(self, node_manager_with_untracked):
        """Removing a node that doesn't exist should raise an error."""
        nm = node_manager_with_untracked["node_manager"]

        with pytest.raises(CDNodeNotFoundError):
            nm.remove_node("nonexistent-node")
