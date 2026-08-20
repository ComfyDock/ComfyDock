"""Integration tests for logging directory structure."""

import os

import pytest


@pytest.fixture
def mock_workspace(tmp_path):
    """Create a minimal workspace structure for logging tests."""
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    # Create basic structure
    (workspace_path / ".metadata").mkdir()
    (workspace_path / "environments").mkdir()

    return workspace_path


class TestEnvironmentLogStructure:
    """Test that environment logs always use directory structure."""

    def test_environment_logs_use_directory_structure(self, mock_workspace):
        """Environment logs should be in logs/{env_name}/full.log, not logs/{env_name}.log."""
        from comfygit_cli.logging.environment_logger import EnvironmentLogger

        EnvironmentLogger.set_workspace_path(mock_workspace)

        # Create handler for test environment
        with EnvironmentLogger.log_command("test-env", "test command"):
            pass

        # Should create directory structure, not flat file
        expected_dir = mock_workspace / "logs" / "test-env"
        expected_log = expected_dir / "full.log"
        flat_file = mock_workspace / "logs" / "test-env.log"

        assert expected_dir.exists(), f"Expected directory {expected_dir} to exist"
        assert expected_log.exists(), f"Expected {expected_log} to exist"
        assert not flat_file.exists(), f"Flat file {flat_file} should not exist (legacy format)"

    def test_environment_logs_without_compression(self, mock_workspace):
        """Without env var, should create only full.log in directory."""
        from comfygit_cli.logging.environment_logger import EnvironmentLogger

        # Ensure compression is disabled
        os.environ.pop('COMFYGIT_DEV_COMPRESS_LOGS', None)

        EnvironmentLogger.set_workspace_path(mock_workspace)

        with EnvironmentLogger.log_command("test-env", "test command"):
            pass

        log_dir = mock_workspace / "logs" / "test-env"
        full_log = log_dir / "full.log"
        compressed_log = log_dir / "compressed.log"

        assert log_dir.exists()
        assert full_log.exists()
        assert not compressed_log.exists(), "compressed.log should not exist without env var"
        if os.name != "nt":
            assert full_log.stat().st_mode & 0o777 == 0o600

    def test_environment_log_context_redacts_secret_fields(self, mock_workspace):
        """Structured command context must never write provider credentials."""
        from comfygit_cli.logging.environment_logger import EnvironmentLogger

        EnvironmentLogger.set_workspace_path(mock_workspace)
        with EnvironmentLogger.log_command(
            "test-env",
            "auth set",
            arg_huggingface_token="hf_secret_value",
            arg_name="safe-value",
        ):
            pass

        contents = (mock_workspace / "logs" / "test-env" / "full.log").read_text()
        assert "hf_secret_value" not in contents
        assert "arg_huggingface_token: <redacted>" in contents
        assert "arg_name: safe-value" in contents

    def test_environment_logs_with_compression(self, mock_workspace):
        """With env var, should create both full.log and compressed.log in directory."""
        from comfygit_cli.logging.environment_logger import EnvironmentLogger

        # Enable compression
        os.environ['COMFYGIT_DEV_COMPRESS_LOGS'] = 'true'

        try:
            EnvironmentLogger.set_workspace_path(mock_workspace)

            with EnvironmentLogger.log_command("test-env", "test command"):
                pass

            log_dir = mock_workspace / "logs" / "test-env"
            full_log = log_dir / "full.log"
            compressed_log = log_dir / "compressed.log"

            assert log_dir.exists()
            assert full_log.exists()
            assert compressed_log.exists(), "compressed.log should exist with env var"
        finally:
            os.environ.pop('COMFYGIT_DEV_COMPRESS_LOGS', None)


class TestWorkspaceLogStructure:
    """Test that workspace logs match environment log structure."""

    def test_workspace_logs_use_full_log_name(self, mock_workspace):
        """Workspace logs should use logs/workspace/full.log, not logs/workspace/workspace.log."""
        from comfygit_cli.logging.environment_logger import WorkspaceLogger

        WorkspaceLogger.set_workspace_path(mock_workspace)

        with WorkspaceLogger.log_command("test command"):
            pass

        log_dir = mock_workspace / "logs" / "workspace"
        expected_log = log_dir / "full.log"
        old_log = log_dir / "workspace.log"

        assert log_dir.exists()
        assert expected_log.exists(), f"Expected {expected_log} to exist"
        assert not old_log.exists(), f"Old format {old_log} should not exist"

    def test_workspace_logs_without_compression(self, mock_workspace):
        """Without env var, workspace should create only full.log."""
        from comfygit_cli.logging.environment_logger import WorkspaceLogger

        os.environ.pop('COMFYGIT_DEV_COMPRESS_LOGS', None)

        WorkspaceLogger.set_workspace_path(mock_workspace)

        with WorkspaceLogger.log_command("test command"):
            pass

        log_dir = mock_workspace / "logs" / "workspace"
        full_log = log_dir / "full.log"
        compressed_log = log_dir / "compressed.log"

        assert log_dir.exists()
        assert full_log.exists()
        assert not compressed_log.exists(), "compressed.log should not exist without env var"
        if os.name != "nt":
            assert full_log.stat().st_mode & 0o777 == 0o600

    def test_workspace_logs_with_compression(self, mock_workspace):
        """With env var, workspace should create both full.log and compressed.log."""
        from comfygit_cli.logging.environment_logger import WorkspaceLogger

        os.environ['COMFYGIT_DEV_COMPRESS_LOGS'] = 'true'

        try:
            WorkspaceLogger.set_workspace_path(mock_workspace)

            with WorkspaceLogger.log_command("test command"):
                pass

            log_dir = mock_workspace / "logs" / "workspace"
            full_log = log_dir / "full.log"
            compressed_log = log_dir / "compressed.log"

            assert log_dir.exists()
            assert full_log.exists()
            assert compressed_log.exists(), "compressed.log should exist with env var"
        finally:
            os.environ.pop('COMFYGIT_DEV_COMPRESS_LOGS', None)


class TestCompressedLogRotation:
    """Test that compressed logs rotate along with full logs."""

    def test_compressed_log_rotates_with_full_log(self, mock_workspace, monkeypatch):
        """When full.log rotates, compressed.log should also rotate."""
        import logging

        from comfygit_cli.logging.compressed_handler import CompressedDualHandler

        os.environ['COMFYGIT_DEV_COMPRESS_LOGS'] = 'true'

        try:
            log_dir = mock_workspace / "logs" / "test-rotation"
            log_dir.mkdir(parents=True)

            # Create handler with small maxBytes to trigger rotation
            handler = CompressedDualHandler(
                log_dir=log_dir,
                env_name="test-rotation",
                compression_level='medium',
                maxBytes=500,  # Very small for testing
                backupCount=3,
                encoding='utf-8'
            )

            # Write enough to trigger rotation
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="X" * 200,  # Large message
                args=(),
                exc_info=None
            )

            # Write multiple times to exceed maxBytes
            for _ in range(5):
                handler.emit(record)

            handler.close()

            # Both files should have rotated backups
            full_log_backup = log_dir / "full.log.1"
            compressed_log_backup = log_dir / "compressed.log.1"

            assert full_log_backup.exists(), "full.log.1 should exist after rotation"
            assert compressed_log_backup.exists(), "compressed.log.1 should exist after rotation"

        finally:
            os.environ.pop('COMFYGIT_DEV_COMPRESS_LOGS', None)


def test_non_rotating_private_log_handler_uses_owner_only_permissions(tmp_path):
    from comfygit_cli.logging.security import PrivateFileHandler

    log_path = tmp_path / "private.log"
    handler = PrivateFileHandler(log_path, encoding="utf-8")
    handler.close()

    if os.name != "nt":
        assert log_path.stat().st_mode & 0o777 == 0o600
