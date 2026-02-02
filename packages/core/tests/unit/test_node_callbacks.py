"""Unit tests for node installation callbacks."""
from unittest.mock import Mock

from comfygit_core.models.workflow import NodeInstallCallbacks


def test_node_install_callbacks_dataclass():
    """Test that NodeInstallCallbacks can be instantiated with functions."""

    def on_batch_start(total):
        pass

    def on_node_start(node_id, idx, total):
        pass

    def on_node_complete(node_id, success, error):
        pass

    def on_batch_complete(success_count, total):
        pass

    callbacks = NodeInstallCallbacks(
        on_batch_start=on_batch_start,
        on_node_start=on_node_start,
        on_node_complete=on_node_complete,
        on_batch_complete=on_batch_complete
    )

    assert callbacks.on_batch_start is on_batch_start
    assert callbacks.on_node_start is on_node_start
    assert callbacks.on_node_complete is on_node_complete
    assert callbacks.on_batch_complete is on_batch_complete


def test_node_install_callbacks_optional():
    """Test that all callback fields are optional."""
    callbacks = NodeInstallCallbacks()

    assert callbacks.on_batch_start is None
    assert callbacks.on_node_start is None
    assert callbacks.on_node_complete is None
    assert callbacks.on_batch_complete is None


def test_node_install_callbacks_can_be_called():
    """Test that callbacks can actually be invoked."""
    mock_batch_start = Mock()
    mock_node_start = Mock()
    mock_node_complete = Mock()
    mock_batch_complete = Mock()

    callbacks = NodeInstallCallbacks(
        on_batch_start=mock_batch_start,
        on_node_start=mock_node_start,
        on_node_complete=mock_node_complete,
        on_batch_complete=mock_batch_complete
    )

    # Simulate callback invocations
    if callbacks.on_batch_start:
        callbacks.on_batch_start(3)

    if callbacks.on_node_start:
        callbacks.on_node_start("test-node-1", 1, 3)
        callbacks.on_node_start("test-node-2", 2, 3)
        callbacks.on_node_start("test-node-3", 3, 3)

    if callbacks.on_node_complete:
        callbacks.on_node_complete("test-node-1", True, None)
        callbacks.on_node_complete("test-node-2", True, None)
        callbacks.on_node_complete("test-node-3", False, "Error")

    if callbacks.on_batch_complete:
        callbacks.on_batch_complete(2, 3)

    # Verify invocations
    mock_batch_start.assert_called_once_with(3)
    assert mock_node_start.call_count == 3
    assert mock_node_complete.call_count == 3
    mock_batch_complete.assert_called_once_with(2, 3)
