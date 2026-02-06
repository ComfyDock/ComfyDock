"""Tests for PyTorch version prober utilities."""

from unittest.mock import MagicMock, patch

import pytest


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
        from comfygit_core.utils import pytorch_prober
        from comfygit_core.utils.pytorch_prober import _find_uv_binary

        # Make the bundled uv import fail inside the function
        real_import = __import__

        def mock_import(name, *args, **kwargs):
            if name == "uv":
                raise ImportError("no uv package")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)
        monkeypatch.setattr(pytorch_prober.shutil, "which", lambda _: "/usr/local/bin/uv")

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

    def test_raises_on_invalid_output(self):
        """Should raise error when can't parse version."""
        from comfygit_core.utils.pytorch_prober import PyTorchProbeError, get_exact_python_version

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "/usr/bin/python3"  # No version in path

        with patch("comfygit_core.utils.pytorch_prober.run_command", return_value=mock_result):
            with pytest.raises(PyTorchProbeError):
                get_exact_python_version("3.12")


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
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

            if "uv python find" in cmd_str:
                result.stdout = "/path/to/cpython-3.12.11/bin/python"
            elif "uv venv" in cmd_str:
                result.stdout = "Using CPython 3.12.11\nCreated venv"
            elif "uv pip install" in cmd_str:
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
        monkeypatch.setattr(pytorch_prober.tempfile, "mkdtemp", lambda **_: str(probe_dir))
        monkeypatch.setattr(pytorch_prober.shutil, "rmtree", lambda *a, **k: None)

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
    def test_probe_with_auto_detects_backend(self, monkeypatch, tmp_path):
        """Probe with 'auto' should detect and return resolved backend."""
        from comfygit_core.utils import pytorch_prober
        from comfygit_core.utils.pytorch_prober import probe_pytorch_versions

        def mock_run_command(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

            if "uv python find" in cmd_str:
                result.stdout = "/path/to/cpython-3.12.11/bin/python"
            elif "uv venv" in cmd_str:
                result.stdout = "Created venv"
            elif "uv pip install" in cmd_str:
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
        monkeypatch.setattr(pytorch_prober.tempfile, "mkdtemp", lambda **_: str(probe_dir))
        monkeypatch.setattr(pytorch_prober.shutil, "rmtree", lambda *a, **k: None)

        versions, backend = probe_pytorch_versions("3.12", "auto")

        assert backend == "cu128"  # Auto-detected from version suffix
        assert versions["torch"] == "2.9.1+cu128"

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
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

            if "uv python find" in cmd_str:
                result.stdout = "/path/to/cpython-3.12.11/bin/python"
            elif "uv venv" in cmd_str:
                result.stdout = "Created venv"
            elif "uv pip install" in cmd_str:
                result.stdout = " + torch==2.9.1+cu128"
            else:
                result.stdout = ""
            return result

        def mock_rmtree(path, *args, **kwargs):
            cleanup_called.append(path)

        probe_dir = tmp_path / "probe"
        probe_dir.mkdir()

        monkeypatch.setattr(pytorch_prober, "run_command", mock_run_command)
        monkeypatch.setattr(pytorch_prober.tempfile, "mkdtemp", lambda **_: str(probe_dir))
        monkeypatch.setattr(pytorch_prober.shutil, "rmtree", mock_rmtree)

        probe_pytorch_versions("3.12", "cu128")

        assert len(cleanup_called) > 0
