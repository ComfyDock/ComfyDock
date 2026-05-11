"""Tests for native process manager."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from comfygit_deploy.worker.native_manager import (
    NativeManager,
)


class _FakeStdout:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


class TestEnvironmentExistsCheck:
    """Test environment existence detection (skip re-import)."""

    def test_environment_exists_when_comfyui_directory_present(self, tmp_path: Path) -> None:
        """Environment exists if ComfyUI subdirectory is present."""
        manager = NativeManager(tmp_path)

        # Create environment with ComfyUI directory
        env_path = tmp_path / "environments" / "test-env" / "ComfyUI"
        env_path.mkdir(parents=True)

        assert manager.environment_exists("test-env") is True

    def test_environment_not_exists_when_no_comfyui_directory(self, tmp_path: Path) -> None:
        """Environment doesn't exist if no ComfyUI directory."""
        manager = NativeManager(tmp_path)

        # Create empty environment directory (incomplete setup)
        env_path = tmp_path / "environments" / "test-env"
        env_path.mkdir(parents=True)

        assert manager.environment_exists("test-env") is False

    def test_environment_not_exists_when_no_directory(self, tmp_path: Path) -> None:
        """Environment doesn't exist if directory is missing."""
        manager = NativeManager(tmp_path)
        assert manager.environment_exists("nonexistent") is False

    @pytest.mark.asyncio
    async def test_deploy_skips_import_when_environment_exists(self, tmp_path: Path) -> None:
        """Deploy skips import and returns skipped status when env exists."""
        manager = NativeManager(tmp_path)

        # Pre-create environment
        env_path = tmp_path / "environments" / "test-env" / "ComfyUI"
        env_path.mkdir(parents=True)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await manager.deploy(
                instance_id="inst_123",
                environment_name="test-env",
                import_source="https://github.com/user/repo.git",
            )

            # Should NOT call import
            mock_exec.assert_not_called()

            # Should return successful with skipped=True
            assert result.success is True
            assert result.skipped is True

    @pytest.mark.asyncio
    async def test_deploy_imports_when_environment_missing(self, tmp_path: Path) -> None:
        """Deploy runs import when environment doesn't exist."""
        manager = NativeManager(tmp_path)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.stdout = _FakeStdout([b"Success\n"])
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            result = await manager.deploy(
                instance_id="inst_123",
                environment_name="test-env",
                import_source="https://github.com/user/repo.git",
            )

            # Should call import
            mock_exec.assert_called_once()
            assert result.success is True
            assert result.skipped is False


class TestReadinessPolling:
    """Test HTTP readiness polling for ComfyUI."""

    @pytest.mark.asyncio
    async def test_wait_for_ready_returns_false_when_no_server(
        self, tmp_path: Path
    ) -> None:
        """wait_for_ready returns False when no server is listening."""
        manager = NativeManager(tmp_path)

        # Use a port that almost certainly has nothing listening
        result = await manager.wait_for_ready(
            port=59999, timeout_seconds=0.5, poll_interval=0.1
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_ready_accepts_timeout_params(
        self, tmp_path: Path
    ) -> None:
        """wait_for_ready accepts custom timeout and poll_interval."""
        manager = NativeManager(tmp_path)

        import time
        start = time.monotonic()
        result = await manager.wait_for_ready(
            port=59998, timeout_seconds=0.3, poll_interval=0.1
        )
        elapsed = time.monotonic() - start

        assert result is False
        # Should have taken roughly the timeout time
        assert 0.2 < elapsed < 1.0


class TestNativeManager:
    """Test native process manager."""

    def test_init_with_workspace_path(self) -> None:
        """Manager initializes with workspace path."""
        workspace = Path("/tmp/test-workspace")
        manager = NativeManager(workspace)
        assert manager.workspace_path == workspace

    @pytest.mark.asyncio
    async def test_deploy_calls_cg_import(self) -> None:
        """Deploy runs cg import command with correct args."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NativeManager(Path(tmpdir))

            # Mock subprocess to avoid actually running command
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.stdout = _FakeStdout([b"Success\n"])
                mock_proc.returncode = 0
                mock_exec.return_value = mock_proc

                result = await manager.deploy(
                    instance_id="inst_123",
                    environment_name="test-env",
                    import_source="https://github.com/user/repo.git",
                    branch="main",
                )

                assert result.success is True
                assert result.skipped is False
                # Verify cg import was called
                call_args = mock_exec.call_args[0]
                assert "cg" in call_args
                assert "import" in call_args
                assert "https://github.com/user/repo.git" in call_args
                assert "--name" in call_args
                assert "test-env" in call_args
                assert "--branch" in call_args
                assert "main" in call_args

    @pytest.mark.asyncio
    async def test_deploy_returns_failure_on_error(self) -> None:
        """Deploy returns failure result when import fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NativeManager(Path(tmpdir))

            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.stdout = _FakeStdout([b"Error\n"])
                mock_proc.returncode = 1
                mock_exec.return_value = mock_proc

                result = await manager.deploy(
                    instance_id="inst_123",
                    environment_name="test-env",
                    import_source="bad-source",
                )

                assert result.success is False
                assert result.error is not None

    def test_start_spawns_process(self) -> None:
        """Start launches cg run subprocess."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NativeManager(Path(tmpdir))

            with patch("subprocess.Popen") as mock_popen:
                mock_proc = MagicMock()
                mock_proc.pid = 12345
                mock_proc.poll.return_value = None  # Process running
                mock_popen.return_value = mock_proc

                result = manager.start(
                    instance_id="inst_123",
                    environment_name="test-env",
                    port=8188,
                )

                assert result is not None
                assert result.pid == 12345
                assert result.port == 8188

                # Verify correct command
                call_args = mock_popen.call_args
                cmd = call_args[0][0]
                assert "cg" in cmd
                assert "-e" in cmd
                assert "test-env" in cmd
                assert "run" in cmd
                assert "--port" in cmd
                assert "8188" in cmd

    def test_start_returns_existing_process_if_running(self) -> None:
        """Start returns existing process info if already running."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NativeManager(Path(tmpdir))

            # First start
            with patch("subprocess.Popen") as mock_popen:
                mock_proc = MagicMock()
                mock_proc.pid = 12345
                mock_proc.poll.return_value = None
                mock_popen.return_value = mock_proc

                manager.start("inst_123", "test-env", 8188)

            # Second start - should return same process
            result = manager.start("inst_123", "test-env", 8188)
            assert result.pid == 12345

    def test_stop_terminates_process(self) -> None:
        """Stop terminates running process."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NativeManager(Path(tmpdir))

            # Create mock process
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.poll.return_value = None  # Running initially

            with patch("subprocess.Popen", return_value=mock_proc):
                manager.start("inst_123", "test-env", 8188)

            # Stop should work - the process is tracked
            # We need to set up poll to indicate process terminated after stop
            def poll_side_effect():
                # Return None first (running), then 0 (stopped)
                if not hasattr(poll_side_effect, "called"):
                    poll_side_effect.called = True
                    return None
                return 0

            mock_proc.poll.side_effect = poll_side_effect

            with patch(
                "comfygit_deploy.worker.native_manager.os.killpg"
            ) as mock_killpg, patch(
                "comfygit_deploy.worker.native_manager.os.getpgid", return_value=12345
            ):
                result = manager.stop("inst_123")

                assert result is True
                mock_killpg.assert_called()

    def test_stop_returns_true_for_unknown_instance(self) -> None:
        """Stop returns True for instance that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NativeManager(Path(tmpdir))
            result = manager.stop("nonexistent")
            assert result is True

    def test_terminate_removes_tracking(self) -> None:
        """Terminate stops process and removes from tracking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NativeManager(Path(tmpdir))

            with patch("subprocess.Popen") as mock_popen:
                mock_proc = MagicMock()
                mock_proc.pid = 12345
                mock_proc.poll.return_value = None
                mock_popen.return_value = mock_proc

                manager.start("inst_123", "test-env", 8188)

            with patch("os.killpg"), patch("os.getpgid") as mock_getpgid:
                mock_getpgid.return_value = 12345
                mock_proc.wait.return_value = 0
                mock_proc.poll.return_value = 0

                manager.terminate("inst_123")

            # Should no longer be tracked
            assert not manager.is_running("inst_123")

    def test_is_running_returns_false_for_unknown(self) -> None:
        """is_running returns False for unknown instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NativeManager(Path(tmpdir))
            assert not manager.is_running("nonexistent")

    def test_get_pid_returns_none_for_unknown(self) -> None:
        """get_pid returns None for unknown instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NativeManager(Path(tmpdir))
            assert manager.get_pid("nonexistent") is None
