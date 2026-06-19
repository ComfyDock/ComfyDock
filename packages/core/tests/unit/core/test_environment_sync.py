from unittest.mock import MagicMock, patch

from comfygit_core.constants import ACTIVE_TORCH_BACKEND_OVERRIDE_ENV


def test_environment_sync_uses_active_runtime_backend_override(test_env, monkeypatch):
    monkeypatch.setenv(ACTIVE_TORCH_BACKEND_OVERRIDE_ENV, "cu126")

    with patch(
        "comfygit_core.services.environment_sync_coordinator.EnvironmentSyncCoordinator.sync",
        return_value=MagicMock(success=True),
    ) as mock_sync:
        test_env.sync()

    assert mock_sync.call_args.kwargs["backend_override"] == "cu126"


def test_environment_sync_explicit_backend_override_wins(test_env, monkeypatch):
    monkeypatch.setenv(ACTIVE_TORCH_BACKEND_OVERRIDE_ENV, "cu126")

    with patch(
        "comfygit_core.services.environment_sync_coordinator.EnvironmentSyncCoordinator.sync",
        return_value=MagicMock(success=True),
    ) as mock_sync:
        test_env.sync(backend_override="cpu")

    assert mock_sync.call_args.kwargs["backend_override"] == "cpu"
