"""Unit tests for environment cleanup utilities."""
import tempfile
from pathlib import Path

from comfygit_core.utils.environment_cleanup import (
    COMPLETION_MARKER,
    is_environment_complete,
    mark_environment_complete,
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
