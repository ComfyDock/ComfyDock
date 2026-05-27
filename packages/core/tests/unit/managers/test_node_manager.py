"""Tests for NodeManager utilities."""

from pathlib import Path
from unittest.mock import Mock

import pytest
import tomlkit
from comfygit_core.managers.node_manager import NodeManager
from comfygit_core.managers.pyproject_manager import PyprojectManager
from comfygit_core.models.exceptions import (
    CDDependencyConflictError,
    CDEnvironmentError,
    CDNodeConflictError,
)
from comfygit_core.models.shared import NodeInfo
from comfygit_core.utils.dependency_probe import ProbeResult
from comfygit_core.utils.git import is_github_url


class TestNodeManager:
    """Test NodeManager utility methods."""

    def test_is_github_url_https(self):
        """Test GitHub URL detection for HTTPS URLs."""
        assert is_github_url("https://github.com/owner/repo")
        assert is_github_url("https://github.com/owner/repo.git")

    def test_is_github_url_ssh(self):
        """Test GitHub URL detection for SSH URLs."""
        assert is_github_url("git@github.com:owner/repo.git")
        assert is_github_url("ssh://git@github.com/owner/repo")

    def test_is_github_url_non_github(self):
        """Test GitHub URL detection for non-GitHub URLs."""
        assert not is_github_url("https://gitlab.com/owner/repo")
        assert not is_github_url("registry-package-id")
        assert not is_github_url("local-path")
        assert not is_github_url("")

    def test_get_existing_node_by_registry_id_found(self):
        """Test getting existing node by registry ID when found."""
        mock_pyproject = Mock()
        mock_node_info = Mock()
        mock_node_info.registry_id = "test-package"
        mock_node_info.name = "Test Node"
        mock_node_info.version = "1.0.0"
        mock_node_info.repository = "https://github.com/owner/repo"
        mock_node_info.source = "git"

        mock_pyproject.nodes.get_existing.return_value = {
            "node1": mock_node_info
        }

        node_manager = NodeManager(
            mock_pyproject, Mock(), Mock(), Mock(), Mock(), Mock()
        )

        result = node_manager._get_existing_node_by_registry_id("test-package")
        expected = {
            'name': "Test Node",
            'registry_id': "test-package",
            'version': "1.0.0",
            'repository': "https://github.com/owner/repo",
            'source': "git"
        }

        assert result == expected

    def test_get_existing_node_by_registry_id_not_found(self):
        """Test getting existing node by registry ID when not found."""
        mock_pyproject = Mock()
        mock_node_info = Mock()
        mock_node_info.registry_id = "other-package"

        mock_pyproject.nodes.get_existing.return_value = {
            "node1": mock_node_info
        }

        node_manager = NodeManager(
            mock_pyproject, Mock(), Mock(), Mock(), Mock(), Mock()
        )

        result = node_manager._get_existing_node_by_registry_id("test-package")
        assert result == {}

    def test_add_node_cleans_up_disabled_version(self, tmp_path):
        """Test that add_node removes .disabled version before adding."""
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        # Create a .disabled directory
        disabled_dir = custom_nodes_dir / "test-node.disabled"
        disabled_dir.mkdir()
        (disabled_dir / "old_file.py").write_text("old content")

        # Create a cache directory for the node
        cache_dir = tmp_path / "cache" / "test-node"
        cache_dir.mkdir(parents=True)
        (cache_dir / "node.py").write_text("node content")

        mock_pyproject = Mock()
        mock_node_lookup = Mock()

        # Mock node info
        mock_node_info = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry"
        )

        mock_node_lookup.get_node.return_value = mock_node_info
        mock_node_lookup.download_to_cache.return_value = cache_dir
        mock_node_lookup.scan_requirements.return_value = []

        # Mock get_existing to return empty dict (no existing nodes)
        mock_pyproject.nodes.get_existing.return_value = {}
        mock_pyproject.dependencies.get_groups.return_value = {}

        node_manager = NodeManager(
            mock_pyproject, Mock(), mock_node_lookup, Mock(), custom_nodes_dir, Mock()
        )

        # Mock add_node_package to avoid full flow
        node_manager.add_node_package = Mock()

        # Call add_node
        node_manager.add_node("test-node", no_test=True)

        # Verify .disabled was removed
        assert not disabled_dir.exists()
        assert not (custom_nodes_dir / "test-node.disabled").exists()


class TestNodeManagerDevLink:
    """Tests for CGCORE-SYNC-03C dev-link conversion behavior."""

    def _create_node_manager(self, tmp_path):
        pyproject_path = tmp_path / "pyproject.toml"
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

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
                        "registry-node": {
                            "name": "RegistryNode",
                            "registry_id": "registry-node",
                            "repository": "https://github.com/example/registry-node",
                            "version": "1.2.3",
                            "download_url": "https://example.invalid/node.zip",
                            "source": "registry",
                            "criticality": "required",
                        }
                    },
                    "workflows": {
                        "workflow": {
                            "path": "workflows/workflow.json",
                            "nodes": ["registry-node", "other-node"],
                        }
                    },
                }
            },
        }

        with open(pyproject_path, "w") as f:
            tomlkit.dump(initial_config, f)

        pyproject = PyprojectManager(pyproject_path)
        mock_uv = Mock()
        mock_node_lookup = Mock()
        mock_node_lookup.scan_requirements.return_value = []

        manager = NodeManager(
            pyproject=pyproject,
            uv=mock_uv,
            node_lookup=mock_node_lookup,
            resolution_tester=Mock(),
            custom_nodes_path=custom_nodes_dir,
            node_repository=Mock(),
        )

        return manager, pyproject, pyproject_path, custom_nodes_dir, mock_uv

    def test_dev_link_converts_registry_node_preserving_workflow_identifier(self, tmp_path):
        manager, pyproject, _, custom_nodes_dir, mock_uv = self._create_node_manager(tmp_path)

        installed = custom_nodes_dir / "RegistryNode"
        installed.mkdir()
        (installed / "old.py").write_text("# old")

        dev_repo = tmp_path / "dev-registry-node"
        dev_repo.mkdir()
        (dev_repo / "nodes.py").write_text("# dev")

        result = manager.link_development_node(
            "registry-node",
            dev_repo,
            replace_existing=True,
        )

        assert result.identifier == "registry-node"
        assert result.name == "RegistryNode"
        assert result.backup_path is not None
        assert custom_nodes_dir not in (Path(result.backup_path), *Path(result.backup_path).parents)

        linked = custom_nodes_dir / "RegistryNode"
        assert linked.is_symlink()
        assert linked.resolve() == dev_repo
        assert (Path(result.backup_path) / "old.py").read_text() == "# old"

        nodes = pyproject.nodes.get_existing()
        assert set(nodes) == {"registry-node"}
        node = nodes["registry-node"]
        assert node.name == "RegistryNode"
        assert node.version == "dev"
        assert node.source == "development"
        assert node.registry_id is None
        assert node.download_url is None

        workflow = pyproject.workflows.get_workflow("workflow")
        assert workflow["nodes"] == ["registry-node", "other-node"]
        mock_uv.sync_project.assert_not_called()

    def test_dev_link_is_idempotent_when_already_linked(self, tmp_path):
        manager, _, pyproject_path, custom_nodes_dir, _ = self._create_node_manager(tmp_path)

        installed = custom_nodes_dir / "RegistryNode"
        installed.mkdir()

        dev_repo = tmp_path / "dev-registry-node"
        dev_repo.mkdir()
        (dev_repo / "nodes.py").write_text("# dev")

        first = manager.link_development_node(
            "registry-node",
            dev_repo,
            replace_existing=True,
        )
        before = pyproject_path.read_bytes()
        backup_count = len(list((pyproject_path.parent / "backups" / "custom_nodes").iterdir()))

        second = manager.link_development_node("registry-node", dev_repo)

        assert second.already_linked is True
        assert second.needs_restart is False
        assert second.backup_path is None
        assert pyproject_path.read_bytes() == before
        assert len(list((pyproject_path.parent / "backups" / "custom_nodes").iterdir())) == backup_count
        assert first.backup_path is not None

    def test_dev_link_syncs_with_local_overlays_when_requirements_change(self, tmp_path):
        manager, _, _, custom_nodes_dir, mock_uv = self._create_node_manager(tmp_path)
        manager.node_lookup.scan_requirements.return_value = ["comfygit-studio==0.4.2"]

        installed = custom_nodes_dir / "RegistryNode"
        installed.mkdir()

        dev_repo = tmp_path / "dev-registry-node"
        dev_repo.mkdir()
        (dev_repo / "nodes.py").write_text("# dev")

        manager.link_development_node(
            "registry-node",
            dev_repo,
            replace_existing=True,
        )

        mock_uv.add_requirements_with_sources.assert_called_once()
        assert mock_uv.add_requirements_with_sources.call_args.kwargs["frozen"] is True
        assert "no_sync" not in mock_uv.add_requirements_with_sources.call_args.kwargs
        mock_uv.sync_project.assert_called_once()
        assert mock_uv.sync_project.call_args.kwargs["skip_optional_overlays"] is False


class TestNodeManagerProbeMode:
    """Tests for permissive dependency probe behavior."""

    def _make_probe_manager(self, tmp_path):
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        cache_dir = tmp_path / "cache" / "test-node"
        cache_dir.mkdir(parents=True)
        (cache_dir / "node.py").write_text("node content")

        cec_dir = tmp_path / ".cec"
        cec_dir.mkdir()
        pyproject_path = cec_dir / "pyproject.toml"
        pyproject_path.write_text('[project]\nname = "test-env"\n')

        mock_pyproject = Mock()
        mock_pyproject.path = pyproject_path
        mock_pyproject.snapshot.return_value = {"snapshot": "data"}
        mock_pyproject.restore = Mock()
        mock_pyproject.nodes.get_existing.return_value = {}
        mock_pyproject.dependencies.get_groups.return_value = {}

        mock_node_lookup = Mock()
        mock_node_lookup.get_node.return_value = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
        )
        mock_node_lookup.download_to_cache.return_value = cache_dir
        mock_node_lookup.scan_requirements.return_value = ["numpy", "requests>=2.0"]

        mock_resolution_tester = Mock()
        mock_resolution_tester.workspace_path = tmp_path / "workspace"

        package_config = object()
        node_manager = NodeManager(
            mock_pyproject,
            Mock(),
            mock_node_lookup,
            mock_resolution_tester,
            custom_nodes_dir,
            Mock(),
            package_config=package_config,
        )
        node_manager.add_node_package = Mock()
        return node_manager, package_config

    def test_add_node_passes_package_config_and_logs_skips(self, tmp_path, monkeypatch, caplog):
        """Probe should receive package_config and node manager should log skips."""
        node_manager, package_config = self._make_probe_manager(tmp_path)
        captured: dict = {}

        class FakeProbe:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def run(self, requirements):
                return ProbeResult(
                    success=True,
                    skipped_requirements=["numpy"],
                )

        monkeypatch.setattr("comfygit_core.utils.dependency_probe.DependencyProbe", FakeProbe)

        with caplog.at_level("INFO"):
            node_manager.add_node("test-node", no_test=False, strict=False)

        assert captured["package_config"] is package_config
        assert "skipped protected requirements" in caplog.text
        assert node_manager.add_node_package.call_count == 1

    def test_add_node_warns_instead_of_failing_on_protected_changes(self, tmp_path, monkeypatch, caplog):
        """protected_changes should log a warning and continue installation."""
        node_manager, _ = self._make_probe_manager(tmp_path)

        class FakeProbe:
            def __init__(self, **kwargs):
                pass

            def run(self, requirements):
                return ProbeResult(
                    success=True,
                    protected_changes=["torch"],
                )

        monkeypatch.setattr("comfygit_core.utils.dependency_probe.DependencyProbe", FakeProbe)

        with caplog.at_level("WARNING"):
            node_manager.add_node("test-node", no_test=False, strict=False)

        assert "detected protected package changes" in caplog.text
        assert node_manager.add_node_package.call_count == 1

    def test_add_node_still_fails_on_probe_install_failures(self, tmp_path, monkeypatch):
        """Install failures should still raise dependency conflict."""
        node_manager, _ = self._make_probe_manager(tmp_path)

        class FakeProbe:
            def __init__(self, **kwargs):
                pass

            def run(self, requirements):
                return ProbeResult(
                    success=False,
                    install_failures=["requests>=2.0"],
                )

        monkeypatch.setattr("comfygit_core.utils.dependency_probe.DependencyProbe", FakeProbe)

        with pytest.raises(CDDependencyConflictError):
            node_manager.add_node("test-node", no_test=False, strict=False)


class TestNodeManagerSystemDependencyGroup:
    def test_sync_uv_adds_system_group_when_missing(self):
        mock_pyproject = Mock()
        mock_pyproject.dependencies.get_groups.return_value = {}

        mock_uv = Mock()
        nm = NodeManager(mock_pyproject, mock_uv, Mock(), Mock(), Mock(), Mock())

        nm._sync_uv(quiet=True, all_groups=True)

        mock_pyproject.ensure_system_uv_dependency.assert_called_once_with(
            dependency="uv>=0.11.8",
            group="comfygit-system",
        )
        mock_uv.sync_project.assert_called_once()


class TestNodeManagerDependencyProvisioning:
    def test_provision_missing_node_dependencies_stages_group_and_sources(self, tmp_path):
        custom_nodes_dir = tmp_path / "custom_nodes"
        node_path = custom_nodes_dir / "test-node"
        node_path.mkdir(parents=True)

        node_info = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
        )

        mock_pyproject = Mock()
        mock_pyproject.nodes.get_existing.return_value = {"test-node": node_info}
        mock_pyproject.nodes.generate_group_name.return_value = "test-node-abcd1234"
        mock_pyproject.dependencies.get_groups.return_value = {}
        mock_pyproject.uv_config.get_source_names.side_effect = [set(), {"extra-index"}]

        mock_uv = Mock()
        mock_node_lookup = Mock()
        mock_node_lookup.scan_requirements.return_value = [
            "opencv-contrib-python-headless",
            "onnxruntime>=1.20",
        ]

        package_config = object()
        node_manager = NodeManager(
            mock_pyproject,
            mock_uv,
            mock_node_lookup,
            Mock(),
            custom_nodes_dir,
            Mock(),
            package_config=package_config,
        )

        staged = node_manager.provision_missing_node_dependencies()

        assert staged == ["test-node-abcd1234"]
        mock_node_lookup.scan_requirements.assert_called_once_with(
            node_path,
            package_config=package_config,
        )
        mock_uv.add_requirements_with_sources.assert_called_once_with(
            ["opencv-contrib-python-headless", "onnxruntime>=1.20"],
            group="test-node-abcd1234",
            no_sync=True,
            raw=True,
        )
        stored_node = mock_pyproject.nodes.add.call_args.args[0]
        assert stored_node.dependency_sources == ["extra-index"]
        assert mock_pyproject.nodes.add.call_args.args[1] == "test-node"

    def test_provision_missing_node_dependencies_skips_existing_group(self, tmp_path):
        custom_nodes_dir = tmp_path / "custom_nodes"
        node_path = custom_nodes_dir / "test-node"
        node_path.mkdir(parents=True)

        node_info = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
        )

        mock_pyproject = Mock()
        mock_pyproject.nodes.get_existing.return_value = {"test-node": node_info}
        mock_pyproject.nodes.generate_group_name.return_value = "test-node-abcd1234"
        mock_pyproject.dependencies.get_groups.return_value = {
            "test-node-abcd1234": ["onnxruntime>=1.20"],
        }

        node_manager = NodeManager(
            mock_pyproject,
            Mock(),
            Mock(),
            Mock(),
            custom_nodes_dir,
            Mock(),
        )

        staged = node_manager.provision_missing_node_dependencies()

        assert staged == []
        node_manager.node_lookup.scan_requirements.assert_not_called()
        node_manager.uv.add_requirements_with_sources.assert_not_called()

    def test_provision_missing_node_dependencies_records_empty_group(self, tmp_path):
        custom_nodes_dir = tmp_path / "custom_nodes"
        node_path = custom_nodes_dir / "test-node"
        node_path.mkdir(parents=True)

        node_info = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
        )

        mock_pyproject = Mock()
        mock_pyproject.nodes.get_existing.return_value = {"test-node": node_info}
        mock_pyproject.nodes.generate_group_name.return_value = "test-node-abcd1234"
        mock_pyproject.dependencies.get_groups.return_value = {}
        mock_pyproject.uv_config.get_source_names.side_effect = [set(), set()]

        mock_node_lookup = Mock()
        mock_node_lookup.scan_requirements.return_value = []

        node_manager = NodeManager(
            mock_pyproject,
            Mock(),
            mock_node_lookup,
            Mock(),
            custom_nodes_dir,
            Mock(),
        )

        staged = node_manager.provision_missing_node_dependencies()

        assert staged == ["test-node-abcd1234"]
        mock_pyproject.dependencies.add_to_group.assert_called_once_with(
            "test-node-abcd1234",
            [],
        )
        node_manager.uv.add_requirements_with_sources.assert_not_called()

    def test_sync_uv_does_not_duplicate_system_group(self):
        mock_pyproject = Mock()
        mock_pyproject.dependencies.get_groups.return_value = {"comfygit-system": ["uv>=0.11.8"]}

        mock_uv = Mock()
        nm = NodeManager(mock_pyproject, mock_uv, Mock(), Mock(), Mock(), Mock())

        nm._sync_uv(quiet=True, all_groups=True)

        mock_pyproject.dependencies.add_to_group.assert_not_called()
        mock_uv.sync_project.assert_called_once()


class TestUpdateDevelopmentNode:
    """Tests for _update_development_node version tracking."""

    def test_update_dev_node_picks_up_new_version(self, tmp_path):
        """Dev node update should detect version change from node's pyproject.toml."""
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        # Create the node directory with a pyproject.toml containing new version
        node_dir = custom_nodes_dir / "test-node"
        node_dir.mkdir()
        (node_dir / "pyproject.toml").write_text(
            '[project]\nname = "test-node"\nversion = "0.0.18"\n'
        )

        mock_pyproject = Mock()
        mock_pyproject.nodes.generate_group_name.return_value = "test-node-abc123"
        mock_pyproject.dependencies.get_groups.return_value = {}

        node_info = NodeInfo(
            name="test-node",
            registry_id="test-node",
            version="0.0.16",
            source="development",
        )

        mock_node_lookup = Mock()
        mock_node_lookup.scan_requirements.return_value = []

        nm = NodeManager(
            mock_pyproject, Mock(), mock_node_lookup, Mock(), custom_nodes_dir, Mock()
        )

        result = nm._update_development_node("test-node", node_info, no_test=True)

        assert result.changed is True
        assert "version" in result.message
        assert node_info.version == "0.0.18"

    def test_update_dev_node_no_change_when_version_matches(self, tmp_path):
        """Dev node update should not report change when version is the same."""
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        node_dir = custom_nodes_dir / "test-node"
        node_dir.mkdir()
        (node_dir / "pyproject.toml").write_text(
            '[project]\nname = "test-node"\nversion = "1.0.0"\n'
        )

        mock_pyproject = Mock()
        mock_pyproject.nodes.generate_group_name.return_value = "test-node-abc123"
        mock_pyproject.dependencies.get_groups.return_value = {}

        node_info = NodeInfo(
            name="test-node",
            registry_id="test-node",
            version="1.0.0",
            source="development",
        )

        mock_node_lookup = Mock()
        mock_node_lookup.scan_requirements.return_value = []

        nm = NodeManager(
            mock_pyproject, Mock(), mock_node_lookup, Mock(), custom_nodes_dir, Mock()
        )

        result = nm._update_development_node("test-node", node_info, no_test=True)

        assert result.changed is False
        assert node_info.version == "1.0.0"


class TestInstallTransactionSafety:
    """Tests for install rollback and transaction safety (cg-ckh.1)."""

    def _make_node_manager(self, tmp_path):
        """Create a NodeManager with mocked dependencies for transaction tests."""
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        cache_dir = tmp_path / "cache" / "test-node"
        cache_dir.mkdir(parents=True)
        (cache_dir / "node.py").write_text("new node content")

        mock_pyproject = Mock()
        mock_pyproject.snapshot.return_value = {"snapshot": "data"}
        mock_pyproject.restore = Mock()
        mock_pyproject.nodes.get_existing.return_value = {}
        mock_pyproject.dependencies.get_groups.return_value = {}

        mock_uv = Mock()
        mock_node_lookup = Mock()
        mock_node_lookup.download_to_cache.return_value = cache_dir
        mock_node_lookup.scan_requirements.return_value = []

        node_manager = NodeManager(
            mock_pyproject, mock_uv, mock_node_lookup, Mock(), custom_nodes_dir, Mock()
        )
        node_manager.add_node_package = Mock()

        return node_manager, mock_pyproject, mock_uv, custom_nodes_dir, cache_dir

    def test_install_rollback_preserves_disabled_directory(self, tmp_path):
        """Bug 1: _install_node_from_info rollback must preserve .disabled backup.

        When .disabled exists and install fails, rollback should NOT have
        already deleted .disabled — it should still be available for recovery.
        """
        nm, mock_pyproject, mock_uv, custom_nodes_dir, _ = self._make_node_manager(tmp_path)

        # Create a pre-existing .disabled directory (from a previous update)
        disabled_dir = custom_nodes_dir / "test-node.disabled"
        disabled_dir.mkdir()
        (disabled_dir / "old_code.py").write_text("old version code")

        # Make uv sync fail to trigger rollback
        mock_uv.sync_project.side_effect = Exception("sync failed")

        node_info = NodeInfo(name="test-node", registry_id="test-node", source="registry")

        with pytest.raises((CDEnvironmentError, CDNodeConflictError)):
            nm._install_node_from_info(node_info, no_test=True)

        # .disabled MUST still exist after rollback
        assert disabled_dir.exists(), (
            ".disabled directory was deleted before install completed — "
            "rollback cannot restore old version"
        )
        assert (disabled_dir / "old_code.py").read_text() == "old version code"

    def test_install_rollback_resyncs_venv(self, tmp_path):
        """Bug 2: Install rollback must re-sync venv after restoring pyproject.

        After restoring pyproject.toml, the venv is out of sync. Rollback
        should attempt a best-effort re-sync.
        """
        nm, mock_pyproject, mock_uv, custom_nodes_dir, _ = self._make_node_manager(tmp_path)

        # Make sync fail on the FIRST call (during install), succeed on second (rollback re-sync)
        call_count = 0
        def sync_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("sync failed during install")

        mock_uv.sync_project.side_effect = sync_side_effect

        node_info = NodeInfo(name="test-node", registry_id="test-node", source="registry")

        with pytest.raises((CDEnvironmentError, CDNodeConflictError)):
            nm._install_node_from_info(node_info, no_test=True)

        # sync_project should have been called TWICE:
        # 1st: during install (fails) → triggers rollback
        # 2nd: during rollback re-sync (best-effort)
        assert mock_uv.sync_project.call_count >= 2, (
            f"Expected at least 2 sync_project calls (install + rollback re-sync), "
            f"got {mock_uv.sync_project.call_count}"
        )

    def test_add_node_replacement_restores_old_node_on_failure(self, tmp_path):
        """Bug 3: add_node version replacement must restore old node if install fails.

        When replacing an existing node with a different version, the old node
        should be moved to .disabled (not deleted) so it can be restored on failure.
        """
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        cache_dir = tmp_path / "cache" / "test-node"
        cache_dir.mkdir(parents=True)
        (cache_dir / "node.py").write_text("new version code")

        # Create the existing node directory
        old_node_dir = custom_nodes_dir / "TestNode"
        old_node_dir.mkdir()
        (old_node_dir / "node.py").write_text("old version code")

        mock_pyproject = Mock()
        mock_pyproject.snapshot.return_value = {"snapshot": "data"}
        mock_pyproject.restore = Mock()

        # Set up existing node in tracking
        existing_node = NodeInfo(
            name="TestNode", registry_id="test-node", version="1.0.0", source="registry"
        )
        mock_pyproject.nodes.get_existing.return_value = {"test-node": existing_node}

        mock_uv = Mock()
        mock_node_lookup = Mock()

        new_node_info = NodeInfo(
            name="TestNode", registry_id="test-node", version="2.0.0", source="registry"
        )
        mock_node_lookup.get_node.return_value = new_node_info
        mock_node_lookup.download_to_cache.return_value = cache_dir
        mock_node_lookup.scan_requirements.return_value = []

        mock_node_repo = Mock()
        mock_node_repo.resolve_github_url.return_value = None

        nm = NodeManager(
            mock_pyproject, mock_uv, mock_node_lookup, Mock(), custom_nodes_dir, mock_node_repo
        )
        nm.add_node_package = Mock()

        # Replacement now syncs once after swapping the node and pyproject state.
        # Fail that final sync to exercise rollback of the old filesystem entry.
        mock_uv.sync_project.side_effect = Exception("sync failed on new version")

        with pytest.raises((CDEnvironmentError, CDNodeConflictError)):
            nm.add_node("test-node@2.0.0", no_test=True)

        # Old node directory MUST be restored after failed replacement
        assert old_node_dir.exists(), (
            "Old node directory was permanently deleted during failed replacement — "
            "should have been restored from .disabled backup"
        )
        assert (old_node_dir / "node.py").read_text() == "old version code"

        # Pyproject must be restored to pre-replacement state (old node still tracked)
        mock_pyproject.restore.assert_called_once_with({"snapshot": "data"})
