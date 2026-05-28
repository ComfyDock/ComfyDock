from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch


def test_environment_run_passes_cpu_flag_for_cpu_backend(test_env):
    (test_env.cec_path / ".pytorch-backend").write_text("cpu\n", encoding="utf-8")

    with (
        patch("comfygit_core.core.environment.run_command") as mock_run,
        patch.object(type(test_env.uv_manager), "python_executable", new_callable=PropertyMock) as mock_python,
    ):
        mock_python.return_value = Path("/tmp/python")
        mock_run.return_value = MagicMock(returncode=0)

        test_env.run([])

    cmd = mock_run.call_args.args[0]
    assert cmd == ["/tmp/python", "main.py", "--cpu"]


def test_environment_run_does_not_duplicate_cpu_flag(test_env):
    (test_env.cec_path / ".pytorch-backend").write_text("cpu\n", encoding="utf-8")

    with (
        patch("comfygit_core.core.environment.run_command") as mock_run,
        patch.object(type(test_env.uv_manager), "python_executable", new_callable=PropertyMock) as mock_python,
    ):
        mock_python.return_value = Path("/tmp/python")
        mock_run.return_value = MagicMock(returncode=0)

        test_env.run(["--cpu", "--port", "8199"])

    cmd = mock_run.call_args.args[0]
    assert cmd == ["/tmp/python", "main.py", "--cpu", "--port", "8199"]
