import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_env(tmp_path: Path) -> MagicMock:
    env = MagicMock()
    env.name = "test-env"
    env.path = tmp_path
    env.venv_path = tmp_path / ".venv"
    env.venv_path.mkdir(parents=True, exist_ok=True)
    # Minimal venv python path for get_venv_python() on unix
    (env.venv_path / "bin").mkdir(parents=True, exist_ok=True)
    (env.venv_path / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
    return env


def test_doctor_subcommand_exists_in_parser():
    from comfygit_cli.cli import create_parser

    parser = create_parser()

    # Find top-level choices
    top = None
    for action in parser._subparsers._actions:
        if hasattr(action, "choices") and action.choices is not None:
            top = action.choices
            break

    assert top is not None
    assert "doctor" in top


def test_doctor_noop_when_uv_present(tmp_path, capsys):
    from comfygit_cli.env_commands import EnvironmentCommands

    cmd = EnvironmentCommands()
    env = _make_env(tmp_path)

    args = argparse.Namespace(target_env=None, check_only=False)

    with patch.object(cmd, "_get_env", return_value=env):
        # First uv check succeeds
        with patch("comfygit_cli.env_commands.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="0.7.1\n", stderr="")

            cmd.doctor(args)

    out = capsys.readouterr().out
    assert "uv is installed" in out


def test_doctor_repairs_uv_using_system_uv(tmp_path, capsys):
    from comfygit_cli.env_commands import EnvironmentCommands

    cmd = EnvironmentCommands()
    env = _make_env(tmp_path)

    args = argparse.Namespace(target_env=None, check_only=False)

    # Sequence:
    # 1) check uv -> missing (returncode != 0)
    # 2) install via system uv -> ok
    # 3) re-check uv -> ok
    run_results = [
        MagicMock(returncode=1, stdout="", stderr="No module named uv"),
        MagicMock(returncode=0, stdout="", stderr=""),
        MagicMock(returncode=0, stdout="0.7.2\n", stderr=""),
    ]

    with patch.object(cmd, "_get_env", return_value=env):
        with patch("comfygit_cli.env_commands.shutil.which", return_value="/usr/bin/uv"):
            with patch("comfygit_cli.env_commands.subprocess.run", side_effect=run_results) as mock_run:
                cmd.doctor(args)

    out = capsys.readouterr().out
    assert "Reinstalled uv" in out
    # Ensure we attempted the system uv install path
    install_call = mock_run.call_args_list[1][0][0]
    assert install_call[:3] == ["/usr/bin/uv", "pip", "install"]


def test_doctor_check_only_exits_nonzero_when_missing(tmp_path):
    from comfygit_cli.env_commands import EnvironmentCommands

    cmd = EnvironmentCommands()
    env = _make_env(tmp_path)

    args = argparse.Namespace(target_env=None, check_only=True)

    with patch.object(cmd, "_get_env", return_value=env):
        with patch("comfygit_cli.env_commands.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="No module named uv")
            with pytest.raises(SystemExit) as e:
                cmd.doctor(args)
            assert e.value.code == 1

