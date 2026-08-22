import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from comfygit_cli.cli import create_parser
from comfygit_cli.global_commands import GlobalCommands


def test_materialize_parser_defaults() -> None:
    parser = create_parser()

    args = parser.parse_args(["materialize", "/src/env", "--name", "runtime-env"])

    assert args.command == "materialize"
    assert args.source == "/src/env"
    assert args.name == "runtime-env"
    assert args.models == "skip"
    assert args.torch_backend == "auto"
    assert args.with_manager is False
    assert args.replace is False
    assert callable(args.func)


def test_materialize_passes_runtime_defaults_to_workspace(tmp_path: Path) -> None:
    global_cmds = GlobalCommands()
    mock_workspace = MagicMock()
    mock_workspace.path = tmp_path / "workspace"
    mock_workspace.materialize_environment.return_value = MagicMock(
        environment_name="runtime-env",
        source_type="directory",
        environment_path=tmp_path / "workspace" / "environments" / "runtime-env",
        comfyui_path=tmp_path / "workspace" / "environments" / "runtime-env" / "ComfyUI",
    )

    args = argparse.Namespace(
        source=str(tmp_path / "source"),
        name="runtime-env",
        workspace=tmp_path / "workspace",
        models_dir=tmp_path / "models",
        branch=None,
        torch_backend="auto",
        models="skip",
        with_manager=False,
        use=False,
        replace=False,
    )

    with patch.object(global_cmds, "_get_or_create_workspace_at", return_value=mock_workspace) as get_workspace:
        with pytest.raises(SystemExit) as exc:
            global_cmds.materialize_env(args)

    assert exc.value.code == 0
    get_workspace.assert_called_once_with(args.workspace, args.models_dir)
    mock_workspace.materialize_environment.assert_called_once()
    _, kwargs = mock_workspace.materialize_environment.call_args
    assert kwargs["source"] == args.source
    assert kwargs["name"] == "runtime-env"
    assert kwargs["model_strategy"] == "skip"
    assert kwargs["torch_backend"] == "auto"
    assert kwargs["no_manager"] is True
    assert kwargs["replace"] is False
    assert kwargs["set_active"] is False
    assert kwargs["callbacks"] is not None


def test_materialize_workspace_setup_creates_explicit_models_directory(
    tmp_path: Path,
) -> None:
    global_cmds = GlobalCommands()
    workspace = MagicMock()
    workspace.path = tmp_path / "workspace"
    models_dir = tmp_path / "new" / "models"

    with patch(
        "comfygit_cli.global_commands.Workspace.open",
        return_value=workspace,
    ):
        result = global_cmds._get_or_create_workspace_at(
            workspace.path,
            models_dir,
        )

    assert result is workspace
    assert models_dir.is_dir()
    workspace.set_models_directory.assert_called_once_with(models_dir.resolve())
