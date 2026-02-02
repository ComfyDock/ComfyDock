"""Tests for worker and custom CLI command handlers.

TDD: Tests written first - should FAIL until implementation exists.
"""

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from comfygit_deploy.commands import custom as custom_commands
from comfygit_deploy.commands import worker as worker_commands
from comfygit_deploy.config import DeployConfig


class TestWorkspaceValidation:
    """Tests for workspace validation helper."""

    def test_get_workspace_from_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_validated_workspace returns workspace from config."""
        config_path = tmp_path / "config" / "worker.json"
        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir(parents=True)

        import json
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({
            "workspace_path": str(workspace_path),
        }))

        monkeypatch.delenv("COMFYGIT_HOME", raising=False)
        with patch(
            "comfygit_deploy.commands.worker.WORKER_CONFIG_PATH", config_path
        ):
            result = worker_commands.get_validated_workspace()

        assert result == workspace_path

    def test_get_workspace_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_validated_workspace returns workspace from COMFYGIT_HOME env."""
        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir(parents=True)
        monkeypatch.setenv("COMFYGIT_HOME", str(workspace_path))

        # No config file exists
        with patch(
            "comfygit_deploy.commands.worker.WORKER_CONFIG_PATH",
            tmp_path / "nonexistent" / "worker.json"
        ):
            result = worker_commands.get_validated_workspace()

        assert result == workspace_path

    def test_get_workspace_returns_none_if_not_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_validated_workspace returns None if no config or env."""
        monkeypatch.delenv("COMFYGIT_HOME", raising=False)

        with patch(
            "comfygit_deploy.commands.worker.WORKER_CONFIG_PATH",
            tmp_path / "nonexistent" / "worker.json"
        ):
            result = worker_commands.get_validated_workspace()

        assert result is None

    def test_get_workspace_prefers_env_over_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """COMFYGIT_HOME takes precedence over config file."""
        config_path = tmp_path / "config" / "worker.json"
        config_workspace = tmp_path / "config-workspace"
        env_workspace = tmp_path / "env-workspace"
        config_workspace.mkdir(parents=True)
        env_workspace.mkdir(parents=True)

        import json
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({
            "workspace_path": str(config_workspace),
        }))

        monkeypatch.setenv("COMFYGIT_HOME", str(env_workspace))

        with patch(
            "comfygit_deploy.commands.worker.WORKER_CONFIG_PATH", config_path
        ):
            result = worker_commands.get_validated_workspace()

        assert result == env_workspace


class TestWorkerCommands:
    """Tests for worker command handlers."""

    def test_handle_up_uses_env_workspace_over_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """handle_up should use COMFYGIT_HOME over config workspace_path.

        This is the key test: when COMFYGIT_HOME is set, the worker server
        should use that workspace, not the one saved in worker.json.
        """
        config_path = tmp_path / "worker.json"
        config_workspace = tmp_path / "config-workspace"
        env_workspace = tmp_path / "env-workspace"
        config_workspace.mkdir(parents=True)
        env_workspace.mkdir(parents=True)

        # Create config with one workspace
        import json
        config_path.write_text(json.dumps({
            "version": "1",
            "api_key": "cg_wk_test123",
            "workspace_path": str(config_workspace),
            "default_mode": "native",
        }))

        # Set env to different workspace
        monkeypatch.setenv("COMFYGIT_HOME", str(env_workspace))

        args = argparse.Namespace(
            host="127.0.0.1",
            port=9999,
            mode="native",
            broadcast=False,
            port_range="8200:8210",
            dev=False,
            dev_core=None,
            dev_manager=None,
        )

        # Track what workspace_path is passed to create_worker_app
        captured_workspace = None

        def mock_create_app(**kwargs):
            nonlocal captured_workspace
            captured_workspace = kwargs.get("workspace_path")
            # Return a mock app that we can "run"
            return MagicMock()

        with patch("comfygit_deploy.commands.worker.WORKER_CONFIG_PATH", config_path):
            with patch("comfygit_deploy.worker.server.create_worker_app", mock_create_app):
                with patch("aiohttp.web.run_app"):  # Don't actually start server
                    worker_commands.handle_up(args)

        # The workspace passed to create_worker_app should be from env, not config
        assert captured_workspace == env_workspace

    def test_handle_setup_creates_config(self, tmp_path: Path) -> None:
        """worker setup should create worker config."""
        config_path = tmp_path / "worker.json"

        args = argparse.Namespace(
            api_key=None,  # Should generate one
            workspace=str(tmp_path / "workspace"),
        )

        with patch(
            "comfygit_deploy.commands.worker.WORKER_CONFIG_PATH", config_path
        ):
            result = worker_commands.handle_setup(args)

        assert result == 0
        assert config_path.exists()

    def test_handle_setup_generates_api_key(self, tmp_path: Path) -> None:
        """worker setup should generate API key if not provided."""
        config_path = tmp_path / "worker.json"

        args = argparse.Namespace(api_key=None, workspace=str(tmp_path))

        with patch(
            "comfygit_deploy.commands.worker.WORKER_CONFIG_PATH", config_path
        ):
            worker_commands.handle_setup(args)

        import json
        config = json.loads(config_path.read_text())
        assert config["api_key"].startswith("cg_wk_")
        assert len(config["api_key"]) > 20

    def test_handle_setup_uses_provided_key(self, tmp_path: Path) -> None:
        """worker setup should use provided API key."""
        config_path = tmp_path / "worker.json"

        args = argparse.Namespace(
            api_key="cg_wk_mykey123",
            workspace=str(tmp_path),
        )

        with patch(
            "comfygit_deploy.commands.worker.WORKER_CONFIG_PATH", config_path
        ):
            worker_commands.handle_setup(args)

        import json
        config = json.loads(config_path.read_text())
        assert config["api_key"] == "cg_wk_mykey123"

    def test_handle_status_shows_not_running(self, tmp_path: Path) -> None:
        """worker status should show not running when worker is down."""
        args = argparse.Namespace()

        with patch(
            "comfygit_deploy.commands.worker.is_worker_running", return_value=False
        ):
            result = worker_commands.handle_status(args)

        assert result == 0  # Command succeeds, just shows status

    def test_handle_regenerate_key(self, tmp_path: Path) -> None:
        """worker regenerate-key should create new API key."""
        config_path = tmp_path / "worker.json"

        # Setup existing config
        import json
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({
            "version": "1",
            "api_key": "cg_wk_oldkey",
            "workspace_path": str(tmp_path),
        }))

        args = argparse.Namespace()

        with patch(
            "comfygit_deploy.commands.worker.WORKER_CONFIG_PATH", config_path
        ):
            worker_commands.handle_regenerate_key(args)

        config = json.loads(config_path.read_text())
        assert config["api_key"] != "cg_wk_oldkey"
        assert config["api_key"].startswith("cg_wk_")


class TestCustomCommands:
    """Tests for custom worker command handlers."""

    def test_handle_add_adds_worker_to_config(self, tmp_path: Path) -> None:
        """custom add should add worker to config."""
        config_path = tmp_path / "config.json"
        config = DeployConfig(config_path)
        config.save()

        args = argparse.Namespace(
            name="my-worker",
            host="192.168.1.50",
            port=9090,
            api_key="cg_wk_abc123",
            discovered=False,
        )

        with patch("comfygit_deploy.commands.custom.DeployConfig") as MockConfig:
            mock_config = MagicMock()
            MockConfig.return_value = mock_config

            result = custom_commands.handle_add(args)

        assert result == 0
        mock_config.add_worker.assert_called_once_with(
            "my-worker", "192.168.1.50", 9090, "cg_wk_abc123", mode="docker"
        )
        mock_config.save.assert_called_once()

    def test_handle_add_requires_host_or_discovered(self, tmp_path: Path) -> None:
        """custom add should fail without host unless --discovered."""
        args = argparse.Namespace(
            name="worker",
            host=None,
            port=9090,
            api_key="key",
            discovered=False,
        )

        result = custom_commands.handle_add(args)
        assert result == 1  # Error

    def test_handle_remove_removes_worker(self, tmp_path: Path) -> None:
        """custom remove should remove worker from config."""
        args = argparse.Namespace(name="my-worker")

        with patch("comfygit_deploy.commands.custom.DeployConfig") as MockConfig:
            mock_config = MagicMock()
            mock_config.remove_worker.return_value = True
            MockConfig.return_value = mock_config

            result = custom_commands.handle_remove(args)

        assert result == 0
        mock_config.remove_worker.assert_called_once_with("my-worker")

    def test_handle_remove_warns_if_not_found(self, tmp_path: Path) -> None:
        """custom remove should warn if worker not found."""
        args = argparse.Namespace(name="nonexistent")

        with patch("comfygit_deploy.commands.custom.DeployConfig") as MockConfig:
            mock_config = MagicMock()
            mock_config.remove_worker.return_value = False
            MockConfig.return_value = mock_config

            result = custom_commands.handle_remove(args)

        assert result == 1  # Error - not found

    def test_handle_list_shows_workers(self, tmp_path: Path) -> None:
        """custom list should display registered workers."""
        args = argparse.Namespace()

        with patch("comfygit_deploy.commands.custom.DeployConfig") as MockConfig:
            mock_config = MagicMock()
            mock_config.workers = {
                "worker1": {"host": "192.168.1.50", "port": 9090},
                "worker2": {"host": "192.168.1.51", "port": 9091},
            }
            MockConfig.return_value = mock_config

            result = custom_commands.handle_list(args)

        assert result == 0

    def test_handle_list_shows_empty_message(self, tmp_path: Path) -> None:
        """custom list should show message when no workers."""
        args = argparse.Namespace()

        with patch("comfygit_deploy.commands.custom.DeployConfig") as MockConfig:
            mock_config = MagicMock()
            mock_config.workers = {}
            MockConfig.return_value = mock_config

            result = custom_commands.handle_list(args)

        assert result == 0

    def test_handle_test_tests_connection(self, tmp_path: Path) -> None:
        """custom test should test worker connection."""
        args = argparse.Namespace(name="my-worker")

        with patch("comfygit_deploy.commands.custom.DeployConfig") as MockConfig:
            mock_config = MagicMock()
            mock_config.get_worker.return_value = {
                "host": "192.168.1.50",
                "port": 9090,
                "api_key": "cg_wk_abc",
            }
            MockConfig.return_value = mock_config

            with patch(
                "comfygit_deploy.commands.custom.test_worker_connection"
            ) as mock_test:
                mock_test.return_value = {"success": True, "worker_version": "0.1.0"}

                result = custom_commands.handle_test(args)

        assert result == 0

    def test_handle_deploy_deploys_to_worker(self, tmp_path: Path) -> None:
        """custom deploy should deploy to specified worker."""
        args = argparse.Namespace(
            worker_name="my-worker",
            import_source="https://github.com/user/env.git",
            branch=None,
            mode="docker",
            name="test-deploy",
        )

        with patch("comfygit_deploy.commands.custom.DeployConfig") as MockConfig:
            mock_config = MagicMock()
            mock_config.get_worker.return_value = {
                "host": "192.168.1.50",
                "port": 9090,
                "api_key": "cg_wk_abc",
            }
            MockConfig.return_value = mock_config

            with patch(
                "comfygit_deploy.commands.custom.deploy_to_worker"
            ) as mock_deploy:
                mock_deploy.return_value = {
                    "id": "inst_abc",
                    "status": "deploying",
                    "assigned_port": 8188,
                }

                result = custom_commands.handle_deploy(args)

        assert result == 0
        mock_deploy.assert_called_once()

    def test_handle_deploy_fails_if_worker_not_found(self) -> None:
        """custom deploy should fail if worker not found."""
        args = argparse.Namespace(
            worker_name="nonexistent",
            import_source="https://github.com/x/y.git",
            branch=None,
            mode="docker",
            name=None,
        )

        with patch("comfygit_deploy.commands.custom.DeployConfig") as MockConfig:
            mock_config = MagicMock()
            mock_config.get_worker.return_value = None
            MockConfig.return_value = mock_config

            result = custom_commands.handle_deploy(args)

        assert result == 1
