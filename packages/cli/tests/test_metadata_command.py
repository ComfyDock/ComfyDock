"""Tests for environment metadata CLI commands."""
import argparse
from unittest.mock import MagicMock, patch

from comfygit_cli.cli import create_parser
from comfygit_cli.env_commands import EnvironmentCommands


def test_metadata_refresh_parser_exists():
    parser = create_parser()

    args = parser.parse_args(["metadata", "refresh"])

    assert args.command == "metadata"
    assert args.metadata_command == "refresh"


def test_metadata_refresh_prints_model_loader_result(capsys):
    env_cmds = EnvironmentCommands()

    mock_env = MagicMock()
    mock_env.name = "test-env"
    mock_env.refresh_metadata.return_value = {
        "builtins_refreshed": True,
        "folder_paths_refreshed": True,
        "model_loaders_refreshed": True,
        "builtins_count": 217,
        "folder_mappings_count": 44,
        "model_loaders_count": 29,
    }

    with patch.object(env_cmds, "_get_env", return_value=mock_env):
        args = argparse.Namespace(target_env="test-env")
        env_cmds.metadata_refresh(args)

    output = capsys.readouterr().out
    assert "comfyui_builtins.json (217 nodes)" in output
    assert "comfyui_folder_paths.json (44 folder types)" in output
    assert "comfyui_model_loaders.json (29 model loaders)" in output
    assert "Metadata refreshed successfully" in output
