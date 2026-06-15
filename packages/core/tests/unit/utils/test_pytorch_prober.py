"""Tests for PyTorch version prober utilities."""

import io
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def clear_pytorch_probe_cache():
    from comfygit_core.utils.pytorch_prober import clear_pytorch_probe_cache

    clear_pytorch_probe_cache()
    yield
    clear_pytorch_probe_cache()


def _contains_command_parts(cmd, *parts: str) -> bool:
    return all(part in [str(item) for item in cmd] for part in parts)


class TestFindUvBinary:
    """Tests for _find_uv_binary preferring bundled uv."""

    def test_prefers_bundled_uv(self, monkeypatch):
        """Should use bundled uv package when available."""
        from comfygit_core.utils.pytorch_prober import _find_uv_binary

        monkeypatch.setattr(
            "comfygit_core.utils.pytorch_prober.shutil.which",
            lambda _: "/usr/local/bin/uv",
        )
        # Bundled uv is available in dev environment
        binary = _find_uv_binary()
        assert "uv" in binary
        # Should NOT be the system fallback
        assert binary != "/usr/local/bin/uv"

    def test_falls_back_to_system_uv(self, monkeypatch):
        """Should fall back to system uv when bundled not available."""
        from comfygit_core.utils.pytorch_prober import _find_uv_binary

        # Make the bundled uv import fail inside the function
        real_import = __import__

        def mock_import(name, *args, **kwargs):
            if name == "uv":
                raise ImportError("no uv package")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)
        monkeypatch.setattr("comfygit_core.utils.pytorch_prober.shutil.which", lambda _: "/usr/local/bin/uv")

        binary = _find_uv_binary()
        assert binary == "/usr/local/bin/uv"


class TestGetExactPythonVersion:
    """Tests for get_exact_python_version function."""

    def test_parses_uv_python_find_output(self):
        """Should parse exact Python version from uv python find output."""
        from comfygit_core.utils.pytorch_prober import get_exact_python_version

        mock_result = MagicMock()
        mock_result.returncode = 0
        # Real uv python find output looks like this path
        mock_result.stdout = "/home/user/.local/share/uv/python/cpython-3.12.11-linux-x86_64-gnu/bin/python3.12"

        with patch("comfygit_core.utils.pytorch_prober.run_command", return_value=mock_result):
            version = get_exact_python_version("3.12")
            assert version == "3.12.11"

    def test_handles_3_part_version_request(self):
        """Should work when given exact 3-part version."""
        from comfygit_core.utils.pytorch_prober import get_exact_python_version

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "/home/user/.local/share/uv/python/cpython-3.11.9-linux-x86_64-gnu/bin/python3.11"

        with patch("comfygit_core.utils.pytorch_prober.run_command", return_value=mock_result):
            version = get_exact_python_version("3.11.9")
            assert version == "3.11.9"

    def test_parses_windows_uv_minor_version_output(self):
        """Should parse uv's Windows cpython-X.Y selector output."""
        from comfygit_core.utils.pytorch_prober import get_exact_python_version

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = r"C:\Users\Alex\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe"

        with patch("comfygit_core.utils.pytorch_prober.run_command", return_value=mock_result):
            version = get_exact_python_version("3.11")
            assert version == "3.11"

    def test_raises_on_invalid_output(self):
        """Should raise error when can't parse version."""
        from comfygit_core.utils.pytorch_prober import PyTorchProbeError, get_exact_python_version

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "/usr/bin/python3"  # No version in path

        with patch("comfygit_core.utils.pytorch_prober.run_command", return_value=mock_result):
            with pytest.raises(PyTorchProbeError):
                get_exact_python_version("3.12")


def test_uv_command_env_removes_parent_uv_run_context(monkeypatch):
    from comfygit_core.utils.pytorch_prober import _uv_command_env

    monkeypatch.setenv("VIRTUAL_ENV", "/repo/.venv")
    monkeypatch.setenv("UV_RUN_RECURSION_DEPTH", "1")
    monkeypatch.setenv("UV", "/usr/bin/uv")

    env = _uv_command_env()

    assert "VIRTUAL_ENV" not in env
    assert "UV_RUN_RECURSION_DEPTH" not in env
    assert env["UV"] == "/usr/bin/uv"


def test_run_command_streams_output_callback() -> None:
    from comfygit_core.utils.common import run_command

    lines: list[str] = []

    result = run_command(
        [
            __import__("sys").executable,
            "-c",
            "print('first'); print('second')",
        ],
        output_callback=lines.append,
    )

    assert result.returncode == 0
    assert lines == ["first", "second"]
    assert "first" in result.stdout


def test_run_command_streaming_handles_narrow_stdout_encoding(monkeypatch) -> None:
    from comfygit_core.utils.common import run_command

    narrow_stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", narrow_stdout)

    lines: list[str] = []
    result = run_command(
        [
            sys.executable,
            "-c",
            "print('package \\u2192 dependency')",
        ],
        capture_output=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        output_callback=lines.append,
    )

    assert result.returncode == 0
    assert lines == ["package → dependency"]
    assert "package → dependency" in result.stdout


class TestParseDryRunOutput:
    """Tests for _parse_dry_run_output function."""

    def test_parses_cuda_backend(self):
        """Should parse dry-run output and extract CUDA backend."""
        from comfygit_core.utils.pytorch_prober import _parse_dry_run_output

        output = """Resolved 30 packages in 523ms
Would download 14 packages
Would install 30 packages
 + filelock==3.20.1
 + torch==2.9.1+cu128
 + torchaudio==2.9.1+cu128
 + torchvision==0.24.1+cu128
 + triton==3.5.1
"""
        versions, backend = _parse_dry_run_output(output)

        assert versions["torch"] == "2.9.1+cu128"
        assert versions["torchvision"] == "0.24.1+cu128"
        assert versions["torchaudio"] == "2.9.1+cu128"
        assert backend == "cu128"

    def test_parses_cpu_backend(self):
        """Should detect CPU backend when no suffix present."""
        from comfygit_core.utils.pytorch_prober import _parse_dry_run_output

        output = """Resolved 15 packages in 300ms
Would install 15 packages
 + torch==2.9.1
 + torchvision==0.24.1
 + torchaudio==2.9.1
"""
        versions, backend = _parse_dry_run_output(output)

        assert versions["torch"] == "2.9.1"
        assert backend == "cpu"

    def test_parses_rocm_backend(self):
        """Should parse ROCm backend suffix."""
        from comfygit_core.utils.pytorch_prober import _parse_dry_run_output

        output = """ + torch==2.9.1+rocm6.2
 + torchvision==0.24.1+rocm6.2
"""
        versions, backend = _parse_dry_run_output(output)

        assert versions["torch"] == "2.9.1+rocm6.2"
        assert backend == "rocm6.2"


class TestProbePyTorchVersions:
    """Tests for probe_pytorch_versions function.

    These tests mock run_command (not subprocess.run) since that's what the
    production code uses. Also mocks tempfile.mkdtemp and shutil.rmtree for
    deterministic temp dir handling.
    """

    @pytest.mark.skipif(
        "COMFYGIT_INTEGRATION" in __import__("os").environ,
        reason="Probe tests use mocking that conflicts with integration environment"
    )
    def test_probe_returns_versions_and_backend(self, monkeypatch, tmp_path):
        """Should return tuple of (versions_dict, resolved_backend)."""
        from comfygit_core.utils import pytorch_prober
        from comfygit_core.utils.pytorch_prober import probe_pytorch_versions

        def mock_run_command(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if _contains_command_parts(cmd, "python", "find"):
                result.stdout = "/path/to/cpython-3.12.11/bin/python"
            elif _contains_command_parts(cmd, "venv"):
                result.stdout = "Using CPython 3.12.11\nCreated venv"
            elif _contains_command_parts(cmd, "pip", "install"):
                result.stdout = """Resolved 30 packages in 500ms
Would install 30 packages
 + torch==2.9.1+cu128
 + torchvision==0.24.1+cu128
 + torchaudio==2.9.1+cu128
"""
            else:
                result.stdout = ""
            return result

        probe_dir = tmp_path / "probe"
        probe_dir.mkdir()

        monkeypatch.setattr(pytorch_prober, "run_command", mock_run_command)
        monkeypatch.setattr("comfygit_core.utils.pytorch_prober.tempfile.mkdtemp", lambda **_: str(probe_dir))
        monkeypatch.setattr("comfygit_core.utils.pytorch_prober.shutil.rmtree", lambda *a, **k: None)

        versions, backend = probe_pytorch_versions("3.12.11", "cu128")

        assert "torch" in versions
        assert versions["torch"] == "2.9.1+cu128"
        assert versions["torchvision"] == "0.24.1+cu128"
        assert versions["torchaudio"] == "2.9.1+cu128"
        assert backend == "cu128"

    @pytest.mark.skipif(
        "COMFYGIT_INTEGRATION" in __import__("os").environ,
        reason="Probe tests use mocking that conflicts with integration environment"
    )
    def test_probe_caches_by_python_version_and_backend(self, monkeypatch, tmp_path):
        """Repeated status checks should not re-run identical PyTorch probes."""
        from comfygit_core.utils import pytorch_prober
        from comfygit_core.utils.pytorch_prober import probe_pytorch_versions

        commands: list[list[str]] = []

        def mock_run_command(cmd, *args, **kwargs):
            commands.append([str(part) for part in cmd])
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if _contains_command_parts(cmd, "python", "find"):
                result.stdout = "/path/to/cpython-3.12.11/bin/python"
            elif _contains_command_parts(cmd, "venv"):
                result.stdout = "Created venv"
            elif _contains_command_parts(cmd, "pip", "install"):
                result.stdout = """ + torch==2.9.1+cu128
 + torchvision==0.24.1+cu128
 + torchaudio==2.9.1+cu128
"""
            else:
                result.stdout = ""
            return result

        probe_dir = tmp_path / "probe"
        probe_dir.mkdir()

        monkeypatch.setattr(pytorch_prober, "run_command", mock_run_command)
        monkeypatch.setattr("comfygit_core.utils.pytorch_prober.tempfile.mkdtemp", lambda **_: str(probe_dir))
        monkeypatch.setattr("comfygit_core.utils.pytorch_prober.shutil.rmtree", lambda *a, **k: None)

        first_versions, first_backend = probe_pytorch_versions("3.12", "cu128")
        first_versions["torch"] = "mutated"
        second_versions, second_backend = probe_pytorch_versions("3.12", "cu128")

        assert first_backend == "cu128"
        assert second_backend == "cu128"
        assert second_versions["torch"] == "2.9.1+cu128"
        assert len([cmd for cmd in commands if _contains_command_parts(cmd, "pip", "install")]) == 1

    @pytest.mark.skipif(
        "COMFYGIT_INTEGRATION" in __import__("os").environ,
        reason="Probe tests use mocking that conflicts with integration environment"
    )
    def test_probe_with_auto_detects_backend(self, monkeypatch, tmp_path):
        """Probe with 'auto' should detect and return resolved backend."""
        from comfygit_core.utils import pytorch_prober
        from comfygit_core.utils.pytorch_prober import probe_pytorch_versions

        def mock_run_command(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if _contains_command_parts(cmd, "python", "find"):
                result.stdout = "/path/to/cpython-3.12.11/bin/python"
            elif _contains_command_parts(cmd, "venv"):
                result.stdout = "Created venv"
            elif _contains_command_parts(cmd, "pip", "install"):
                result.stdout = """ + torch==2.9.1+cu128
 + torchvision==0.24.1+cu128
 + torchaudio==2.9.1+cu128
"""
            else:
                result.stdout = ""
            return result

        probe_dir = tmp_path / "probe"
        probe_dir.mkdir()

        monkeypatch.setattr(pytorch_prober, "run_command", mock_run_command)
        monkeypatch.setattr("comfygit_core.utils.pytorch_prober.tempfile.mkdtemp", lambda **_: str(probe_dir))
        monkeypatch.setattr("comfygit_core.utils.pytorch_prober.shutil.rmtree", lambda *a, **k: None)

        versions, backend = probe_pytorch_versions("3.12", "auto")

        assert backend == "cu128"  # Auto-detected from version suffix
        assert versions["torch"] == "2.9.1+cu128"

    @pytest.mark.skipif(
        "COMFYGIT_INTEGRATION" in __import__("os").environ,
        reason="Probe tests use mocking that conflicts with integration environment"
    )
    def test_auto_probe_falls_back_to_cpu_when_auto_backend_fails(self, monkeypatch, tmp_path):
        """Auto probing should fall back to CPU if uv's auto backend cannot resolve."""
        from comfygit_core.utils import pytorch_prober
        from comfygit_core.utils.pytorch_prober import probe_pytorch_versions

        dry_run_backends: list[str] = []

        def mock_run_command(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            result.stdout = ""
            if _contains_command_parts(cmd, "python", "find"):
                result.stdout = "/path/to/cpython-3.12.11/bin/python"
            elif _contains_command_parts(cmd, "venv"):
                result.stdout = "Created venv"
            elif _contains_command_parts(cmd, "pip", "install"):
                backend_arg = next(arg for arg in cmd if str(arg).startswith("--torch-backend="))
                backend = backend_arg.split("=", 1)[1]
                dry_run_backends.append(backend)
                if backend == "auto":
                    result.returncode = 1
                    result.stderr = "Failed to fetch: https://download.pytorch.org/whl/cu112/triton/"
                else:
                    result.stdout = """ + torch==2.9.1
 + torchvision==0.24.1
 + torchaudio==2.9.1
"""
            return result

        probe_dir = tmp_path / "probe"
        probe_dir.mkdir()

        monkeypatch.setattr(pytorch_prober, "run_command", mock_run_command)
        monkeypatch.setattr("comfygit_core.utils.pytorch_prober.tempfile.mkdtemp", lambda **_: str(probe_dir))
        monkeypatch.setattr("comfygit_core.utils.pytorch_prober.shutil.rmtree", lambda *a, **k: None)

        versions, backend = probe_pytorch_versions("3.12", "auto")

        assert dry_run_backends == ["auto", "cpu"]
        assert backend == "cpu"
        assert versions["torch"] == "2.9.1"

    @pytest.mark.skipif(
        "COMFYGIT_INTEGRATION" in __import__("os").environ,
        reason="Probe tests use mocking that conflicts with integration environment"
    )
    def test_probe_cleans_up_temp_dir(self, monkeypatch, tmp_path):
        """Probe should clean up temporary venv directory."""
        from comfygit_core.utils import pytorch_prober
        from comfygit_core.utils.pytorch_prober import probe_pytorch_versions

        cleanup_called = []

        def mock_run_command(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if _contains_command_parts(cmd, "python", "find"):
                result.stdout = "/path/to/cpython-3.12.11/bin/python"
            elif _contains_command_parts(cmd, "venv"):
                result.stdout = "Created venv"
            elif _contains_command_parts(cmd, "pip", "install"):
                result.stdout = " + torch==2.9.1+cu128"
            else:
                result.stdout = ""
            return result

        def mock_rmtree(path, *args, **kwargs):
            cleanup_called.append(path)

        probe_dir = tmp_path / "probe"
        probe_dir.mkdir()

        monkeypatch.setattr(pytorch_prober, "run_command", mock_run_command)
        monkeypatch.setattr("comfygit_core.utils.pytorch_prober.tempfile.mkdtemp", lambda **_: str(probe_dir))
        monkeypatch.setattr("comfygit_core.utils.pytorch_prober.shutil.rmtree", mock_rmtree)

        probe_pytorch_versions("3.12", "cu128")

        assert len(cleanup_called) > 0
