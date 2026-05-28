"""Tests for overlay CLI commands."""

import argparse
from unittest.mock import MagicMock, patch

import pytest
from comfygit_cli.cli import create_parser
from comfygit_core.models import (
    OverlayActivationResult,
    OverlayInfo,
    OverlayTemplateResult,
)


def test_overlay_parser_subcommands_exist():
    parser = create_parser()

    args = parser.parse_args(["overlay", "list"])
    assert args.command == "overlay"
    assert args.overlay_command == "list"

    args = parser.parse_args(["overlay", "show", "alpha"])
    assert args.overlay_command == "show"
    assert args.name == "alpha"

    args = parser.parse_args(["overlay", "enable", "alpha"])
    assert args.overlay_command == "enable"
    assert args.name == "alpha"

    args = parser.parse_args(["overlay", "disable", "alpha"])
    assert args.overlay_command == "disable"
    assert args.name == "alpha"

    args = parser.parse_args(["overlay", "create", "alpha"])
    assert args.overlay_command == "create"
    assert args.name == "alpha"


def test_overlay_list_shows_scope_and_activation(capsys):
    from comfygit_cli.env_commands import EnvironmentCommands

    env_cmds = EnvironmentCommands()
    mock_env = MagicMock()
    mock_env.list_overlays.return_value = [
        OverlayInfo(
            name=".local",
            description="local overrides",
            is_local=True,
            is_active=True,
            requires=[],
        ),
        OverlayInfo(
            name="sageattention",
            description="GPU acceleration",
            is_local=False,
            is_active=False,
            requires=["cuda"],
        ),
    ]

    with patch.object(env_cmds, "_get_env", return_value=mock_env):
        env_cmds.overlay_list(argparse.Namespace(target_env="test"))

    output = capsys.readouterr().out
    assert ".local (local, active)" in output
    assert "sageattention (shared, inactive, requires: cuda)" in output


def test_overlay_list_marks_stock_overlays(capsys):
    from comfygit_cli.env_commands import EnvironmentCommands

    env_cmds = EnvironmentCommands()
    mock_env = MagicMock()
    mock_env.list_overlays.return_value = [
        OverlayInfo(
            name="triton",
            description="Bundled triton",
            is_local=False,
            is_active=True,
            requires=["cuda"],
            is_stock=True,
        ),
    ]

    with patch.object(env_cmds, "_get_env", return_value=mock_env):
        env_cmds.overlay_list(argparse.Namespace(target_env="test"))

    output = capsys.readouterr().out
    assert "triton (stock, active, requires: cuda)" in output


def test_overlay_enable_updates_active_names(capsys):
    from comfygit_cli.env_commands import EnvironmentCommands

    env_cmds = EnvironmentCommands()
    mock_env = MagicMock()
    mock_env.enable_overlay.return_value = OverlayActivationResult(
        name="sageattention",
        changed=True,
        is_compatible=True,
    )

    with patch.object(env_cmds, "_get_env", return_value=mock_env):
        env_cmds.overlay_enable(argparse.Namespace(target_env="test", name="sageattention"))

    mock_env.enable_overlay.assert_called_once_with("sageattention")
    output = capsys.readouterr().out
    assert "Enabled overlay: sageattention" in output


def test_overlay_create_writes_template(tmp_path, capsys):
    from comfygit_cli.env_commands import EnvironmentCommands

    env_cmds = EnvironmentCommands()
    mock_env = MagicMock()
    created = tmp_path / ".cec" / "overlays" / "alpha.toml"
    mock_env.create_overlay_template.return_value = OverlayTemplateResult(
        name="alpha",
        path=created,
        scope="shared",
        created=True,
    )

    with patch.object(env_cmds, "_get_env", return_value=mock_env):
        env_cmds.overlay_create(argparse.Namespace(target_env="test", name="alpha"))

    mock_env.create_overlay_template.assert_called_once_with("alpha", local=False)
    assert "Created shared overlay: alpha" in capsys.readouterr().out


def test_overlay_create_rejects_invalid_name(capsys):
    from comfygit_cli.env_commands import EnvironmentCommands

    env_cmds = EnvironmentCommands()
    mock_env = MagicMock()
    mock_env.create_overlay_template.side_effect = ValueError(
        "Overlay name must be flat (no subdirectories): bad/name"
    )

    with patch.object(env_cmds, "_get_env", return_value=mock_env):
        with pytest.raises(SystemExit):
            env_cmds.overlay_create(argparse.Namespace(target_env="test", name="bad/name"))

    assert "flat" in capsys.readouterr().out
