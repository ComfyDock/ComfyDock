"""Tests for --no-manager flag plumbing through CLI handlers."""

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_create_passes_no_manager_to_workspace():
    from comfygit_cli.env_commands import EnvironmentCommands

    env_cmds = EnvironmentCommands()
    mock_workspace = MagicMock()

    args = argparse.Namespace(
        name="headless-env",
        comfyui=None,
        python="3.12",
        template=None,
        torch_backend="auto",
        no_manager=True,
        use=False,
        yes=True,
    )

    with patch.object(env_cmds, "_get_or_create_workspace", return_value=mock_workspace):
        env_cmds.create(args)

    mock_workspace.create_environment.assert_called_once_with(
        name="headless-env",
        comfyui_version=None,
        python_version="3.12",
        template_path=None,
        torch_backend="auto",
        no_manager=True,
    )


def test_import_passes_no_manager_to_workspace(tmp_path: Path):
    from comfygit_cli.global_commands import GlobalCommands

    global_cmds = GlobalCommands()
    mock_workspace = MagicMock()
    mock_workspace.import_environment.return_value = MagicMock(name="imported", spec=["name"])
    mock_workspace.import_environment.return_value.name = "imported"

    tarball = tmp_path / "bundle.tar.gz"
    tarball.write_bytes(b"dummy")

    args = argparse.Namespace(
        path=str(tarball),
        name="imported",
        branch=None,
        torch_backend="auto",
        use=False,
        models="skip",
        yes=True,
        no_manager=True,
    )

    with patch.object(global_cmds, "_get_or_create_workspace", return_value=mock_workspace):
        with patch("comfygit_cli.global_commands._is_git_url", return_value=False):
            with pytest.raises(SystemExit) as exc:
                global_cmds.import_env(args)

    assert exc.value.code == 0
    mock_workspace.import_environment.assert_called_once()

    _, kwargs = mock_workspace.import_environment.call_args
    assert kwargs["tarball_path"] == tarball
    assert kwargs["name"] == "imported"
    assert kwargs["model_strategy"] == "skip"
    assert kwargs["torch_backend"] == "auto"
    assert kwargs["no_manager"] is True
    assert kwargs["callbacks"] is not None
