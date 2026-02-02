"""Unit tests for StatusScanner disabled node handling."""
from pathlib import Path
from unittest.mock import MagicMock

from comfygit_core.analyzers.status_scanner import StatusScanner
from comfygit_core.models.shared import NodeInfo


class TestDisabledNodeScanning:
    """Test that disabled nodes are correctly handled in status scanning."""

    def _create_scanner(self, tmp_path: Path) -> StatusScanner:
        """Create a StatusScanner with mocked dependencies."""
        mock_uv = MagicMock()
        mock_pyproject = MagicMock()
        venv_path = tmp_path / ".venv"
        comfyui_path = tmp_path / "ComfyUI"

        return StatusScanner(
            uv=mock_uv,
            pyproject=mock_pyproject,
            venv_path=venv_path,
            comfyui_path=comfyui_path,
        )

    def test_disabled_node_not_reported_as_missing(self, tmp_path: Path):
        """
        A disabled node (.disabled suffix) should not be reported as missing.

        When a user disables a node by renaming it to NodeName.disabled,
        the status should NOT report "1 node in pyproject.toml not installed".
        """
        # ARRANGE: Create scanner
        scanner = self._create_scanner(tmp_path)

        # Create custom_nodes directory with disabled node
        custom_nodes = tmp_path / "ComfyUI" / "custom_nodes"
        custom_nodes.mkdir(parents=True)

        # Node exists as disabled
        disabled_node = custom_nodes / "MyNode.disabled"
        disabled_node.mkdir()

        # Mock pyproject to return the node as expected
        scanner._pyproject.nodes.get_existing.return_value = {
            'my-node': NodeInfo(
                name='MyNode',
                version='1.0.0',
                source='registry',
                registry_id='my-node'
            )
        }

        # ACT: Get full comparison
        comparison = scanner.get_full_comparison()

        # ASSERT: Node should NOT be reported as missing
        assert 'MyNode' not in comparison.missing_nodes, \
            f"Disabled node 'MyNode' should not be in missing_nodes, got: {comparison.missing_nodes}"

    def test_enabled_node_with_disabled_version_prioritizes_enabled(self, tmp_path: Path):
        """
        When both enabled and disabled versions exist, enabled takes precedence.
        """
        # ARRANGE
        scanner = self._create_scanner(tmp_path)

        custom_nodes = tmp_path / "ComfyUI" / "custom_nodes"
        custom_nodes.mkdir(parents=True)

        # Both versions exist (maybe from failed update)
        enabled_node = custom_nodes / "MyNode"
        enabled_node.mkdir()
        disabled_node = custom_nodes / "MyNode.disabled"
        disabled_node.mkdir()

        scanner._pyproject.nodes.get_existing.return_value = {
            'my-node': NodeInfo(
                name='MyNode',
                version='1.0.0',
                source='registry'
            )
        }

        # ACT
        comparison = scanner.get_full_comparison()

        # ASSERT: Should not be missing (enabled version exists)
        assert 'MyNode' not in comparison.missing_nodes

    def test_disabled_node_included_in_scan_with_disabled_flag(self, tmp_path: Path):
        """
        Disabled nodes should be scanned and marked with disabled=True.
        """
        # ARRANGE
        scanner = self._create_scanner(tmp_path)

        custom_nodes = tmp_path / "ComfyUI" / "custom_nodes"
        custom_nodes.mkdir(parents=True)

        disabled_node = custom_nodes / "MyNode.disabled"
        disabled_node.mkdir()

        # ACT: Scan environment
        state = scanner.scan_environment()

        # ASSERT: Disabled node should be in state with base name and disabled=True
        assert 'MyNode' in state.custom_nodes, \
            f"Disabled node should be scanned under base name 'MyNode', got: {list(state.custom_nodes.keys())}"
        assert state.custom_nodes['MyNode'].disabled is True, \
            "Disabled node should have disabled=True"

    def test_disabled_node_not_in_extra_nodes_when_in_manifest(self, tmp_path: Path):
        """
        A disabled node that's in the manifest should not be reported as extra.
        """
        # ARRANGE
        scanner = self._create_scanner(tmp_path)

        custom_nodes = tmp_path / "ComfyUI" / "custom_nodes"
        custom_nodes.mkdir(parents=True)

        # Disabled node on disk
        disabled_node = custom_nodes / "MyNode.disabled"
        disabled_node.mkdir()

        # Node is in manifest
        scanner._pyproject.nodes.get_existing.return_value = {
            'my-node': NodeInfo(
                name='MyNode',
                version='1.0.0',
                source='registry'
            )
        }

        # ACT
        comparison = scanner.get_full_comparison()

        # ASSERT: Should not be in extra_nodes
        assert 'MyNode' not in comparison.extra_nodes
        assert 'MyNode.disabled' not in comparison.extra_nodes

    def test_orphaned_disabled_node_reported_as_extra(self, tmp_path: Path):
        """
        A disabled node not in manifest should be reported as extra.

        This happens after git checkout to an older commit that doesn't have the node.
        """
        # ARRANGE
        scanner = self._create_scanner(tmp_path)

        custom_nodes = tmp_path / "ComfyUI" / "custom_nodes"
        custom_nodes.mkdir(parents=True)

        # Disabled node on disk
        disabled_node = custom_nodes / "MyNode.disabled"
        disabled_node.mkdir()

        # Empty manifest (node was removed)
        scanner._pyproject.nodes.get_existing.return_value = {}

        # ACT
        comparison = scanner.get_full_comparison()

        # ASSERT: Should be in extra_nodes (orphaned)
        assert 'MyNode' in comparison.extra_nodes or 'MyNode.disabled' in comparison.extra_nodes, \
            f"Orphaned disabled node should be in extra_nodes, got: {comparison.extra_nodes}"

    def test_timestamped_backup_disabled_nodes_ignored(self, tmp_path: Path):
        """
        Timestamped backup disabled nodes (e.g., MyNode.1700000000.disabled) should be ignored.

        These are internal implementation details from node removal backups.
        """
        # ARRANGE
        scanner = self._create_scanner(tmp_path)

        custom_nodes = tmp_path / "ComfyUI" / "custom_nodes"
        custom_nodes.mkdir(parents=True)

        # Main disabled node
        disabled_node = custom_nodes / "MyNode.disabled"
        disabled_node.mkdir()

        # Timestamped backup (should be ignored)
        backup_node = custom_nodes / "MyNode.1700000000.disabled"
        backup_node.mkdir()

        scanner._pyproject.nodes.get_existing.return_value = {
            'my-node': NodeInfo(
                name='MyNode',
                version='1.0.0',
                source='registry'
            )
        }

        # ACT
        state = scanner.scan_environment()

        # ASSERT: Only one entry for MyNode, not multiple
        mynode_entries = [k for k in state.custom_nodes.keys() if 'MyNode' in k]
        assert len(mynode_entries) == 1, \
            f"Should only have one MyNode entry, got: {mynode_entries}"


class TestEnvironmentComparisonDisabledNodes:
    """Test that EnvironmentComparison handles disabled nodes correctly."""

    def _create_scanner(self, tmp_path: Path) -> StatusScanner:
        """Create a StatusScanner with mocked dependencies."""
        mock_uv = MagicMock()
        mock_pyproject = MagicMock()
        venv_path = tmp_path / ".venv"
        comfyui_path = tmp_path / "ComfyUI"

        return StatusScanner(
            uv=mock_uv,
            pyproject=mock_pyproject,
            venv_path=venv_path,
            comfyui_path=comfyui_path,
        )

    def test_comparison_has_disabled_nodes_attribute(self, tmp_path: Path):
        """
        EnvironmentComparison should have a disabled_nodes attribute.

        This allows CLI to display disabled nodes separately.
        """
        # ARRANGE
        scanner = self._create_scanner(tmp_path)

        custom_nodes = tmp_path / "ComfyUI" / "custom_nodes"
        custom_nodes.mkdir(parents=True)

        disabled_node = custom_nodes / "MyNode.disabled"
        disabled_node.mkdir()

        scanner._pyproject.nodes.get_existing.return_value = {
            'my-node': NodeInfo(
                name='MyNode',
                version='1.0.0',
                source='registry'
            )
        }

        # ACT
        comparison = scanner.get_full_comparison()

        # ASSERT: Should have disabled_nodes attribute
        assert hasattr(comparison, 'disabled_nodes'), \
            "EnvironmentComparison should have 'disabled_nodes' attribute"
        assert 'MyNode' in comparison.disabled_nodes, \
            f"Disabled node should be in disabled_nodes list, got: {comparison.disabled_nodes}"
