"""Unit tests for environment cleanup utilities."""
import tempfile
from pathlib import Path

import pytest
from comfygit_core.utils.environment_cleanup import (
    COMPLETION_MARKER,
    DELETED_ENVIRONMENT_PREFIX,
    is_environment_complete,
    mark_environment_complete,
    remove_environment_directory,
)


class TestCompletionMarker:
    """Test completion marker creation and detection."""

    def test_mark_environment_complete_creates_marker_file(self):
        """mark_environment_complete() should create .complete file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cec_path = Path(temp_dir) / ".cec"
            cec_path.mkdir()

            # Should not exist initially
            marker_file = cec_path / COMPLETION_MARKER
            assert not marker_file.exists()
            assert not is_environment_complete(cec_path)

            # Mark as complete
            mark_environment_complete(cec_path)

            # Should exist now
            assert marker_file.exists()
            assert is_environment_complete(cec_path)

    def test_is_environment_complete_returns_false_when_missing(self):
        """is_environment_complete() should return False when marker doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cec_path = Path(temp_dir) / ".cec"
            cec_path.mkdir()

            assert not is_environment_complete(cec_path)

    def test_is_environment_complete_returns_true_when_present(self):
        """is_environment_complete() should return True when marker exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cec_path = Path(temp_dir) / ".cec"
            cec_path.mkdir()

            # Create marker file
            marker_file = cec_path / COMPLETION_MARKER
            marker_file.touch()

            assert is_environment_complete(cec_path)

    def test_marking_complete_multiple_times_is_idempotent(self):
        """Calling mark_environment_complete() multiple times should be safe."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cec_path = Path(temp_dir) / ".cec"
            cec_path.mkdir()

            # Mark multiple times
            mark_environment_complete(cec_path)
            mark_environment_complete(cec_path)
            mark_environment_complete(cec_path)

            # Should still be complete
            assert is_environment_complete(cec_path)


def test_remove_environment_directory_quarantines_when_directory_remains(monkeypatch, tmp_path):
    env_path = tmp_path / "leftover-env"
    env_path.mkdir()

    monkeypatch.setattr(
        "comfygit_core.utils.environment_cleanup.rmtree",
        lambda path: None,
    )

    remove_environment_directory(env_path)

    assert not env_path.exists()
    quarantined = [
        path for path in tmp_path.iterdir()
        if path.name.startswith(DELETED_ENVIRONMENT_PREFIX)
    ]
    assert len(quarantined) == 1


def test_remove_environment_directory_raises_when_delete_and_quarantine_fail(
    monkeypatch,
    tmp_path,
):
    env_path = tmp_path / "leftover-env"
    env_path.mkdir()

    monkeypatch.setattr(
        "comfygit_core.utils.environment_cleanup.rmtree",
        lambda path, **kwargs: (_ for _ in ()).throw(PermissionError("locked")),
    )
    monkeypatch.setattr(
        "comfygit_core.utils.environment_cleanup._quarantine_environment_directory",
        lambda path: (_ for _ in ()).throw(PermissionError("rename denied")),
    )

    with pytest.raises(PermissionError, match="files may be in use"):
        remove_environment_directory(env_path)
