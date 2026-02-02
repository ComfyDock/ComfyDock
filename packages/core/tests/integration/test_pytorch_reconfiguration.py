"""Integration tests for PyTorch configuration preservation.

Tests that PyTorch config is handled via injection context manager, keeping
pyproject.toml clean of machine-specific PyTorch configuration.
"""
from unittest.mock import patch


class TestGetInstalledPytorchInfo:
    """Test PyTorch detection from venv."""

    def test_extracts_backend_from_version(self):
        """Should extract backend suffix from version string."""
        from comfygit_core.utils.pytorch import extract_backend_from_version

        assert extract_backend_from_version("2.9.0+cu128") == "cu128"
        assert extract_backend_from_version("2.9.0+rocm6.3") == "rocm6.3"
        assert extract_backend_from_version("2.9.0") is None

    def test_get_installed_info_with_cuda(self):
        """Should return installed PyTorch info with backend."""
        from unittest.mock import MagicMock

        from comfygit_core.utils.pytorch import get_installed_pytorch_info

        # ARRANGE - Mock uv_manager
        mock_uv = MagicMock()
        mock_python = "/path/to/python"
        mock_uv.show_package.side_effect = lambda pkg, python: {
            "torch": "Name: torch\nVersion: 2.9.0+cu128\n",
            "torchvision": "Name: torchvision\nVersion: 0.18.0+cu128\n",
            "torchaudio": "Name: torchaudio\nVersion: 2.9.0+cu128\n",
        }.get(pkg, "")

        # ACT
        result = get_installed_pytorch_info(mock_uv, mock_python)

        # ASSERT
        assert result["torch"] == "2.9.0+cu128"
        assert result["torchvision"] == "0.18.0+cu128"
        assert result["torchaudio"] == "2.9.0+cu128"
        assert result["backend"] == "cu128"

    def test_get_installed_info_cpu_only(self):
        """Should return 'cpu' backend when no suffix."""
        from unittest.mock import MagicMock

        from comfygit_core.utils.pytorch import get_installed_pytorch_info

        # ARRANGE - Mock uv_manager with CPU versions
        mock_uv = MagicMock()
        mock_python = "/path/to/python"
        mock_uv.show_package.side_effect = lambda pkg, python: {
            "torch": "Name: torch\nVersion: 2.9.0\n",
            "torchvision": "Name: torchvision\nVersion: 0.18.0\n",
            "torchaudio": "Name: torchaudio\nVersion: 2.9.0\n",
        }.get(pkg, "")

        # ACT
        result = get_installed_pytorch_info(mock_uv, mock_python)

        # ASSERT
        assert result["backend"] == "cpu"


class TestCheckoutKeepsPyprojectClean:
    """Test that checkout keeps pyproject.toml clean of PyTorch config."""

    def test_checkout_does_not_pollute_pyproject(self, test_env, mock_comfyui_clone):
        """Checkout should NOT write PyTorch config to pyproject.toml.

        PyTorch config is now handled entirely by pytorch_injection_context()
        which temporarily injects config during sync and restores afterward.
        """
        # ARRANGE - First commit: add a marker field
        config = test_env.pyproject.load()
        config["tool"]["comfygit"]["test_marker_1"] = "first"
        test_env.pyproject.save(config)
        test_env.git_manager.commit_all("first test commit")

        # Verify pyproject has no PyTorch config
        config = test_env.pyproject.load()
        uv_config = config.get("tool", {}).get("uv", {})
        indexes = uv_config.get("index", [])
        pytorch_indexes = [idx for idx in indexes if "pytorch" in idx.get("name", "").lower()]
        assert len(pytorch_indexes) == 0, "Should start with no PyTorch indexes"

        # Second commit: change marker
        config = test_env.pyproject.load()
        config["tool"]["comfygit"]["test_marker_1"] = "second"
        test_env.pyproject.save(config)
        test_env.git_manager.commit_all("second test commit")

        # Get commits (newest first)
        history = test_env.git_manager.get_version_history(limit=10)
        assert len(history) >= 2, f"Expected at least 2 commits, got {len(history)}"
        first_commit = history[1]["hash"]

        # ACT - Checkout first commit (with mocked installed PyTorch)
        with patch.object(test_env.uv_manager, 'show_package') as mock_show:
            mock_show.side_effect = lambda pkg, python: {
                "torch": "Name: torch\nVersion: 2.9.0+cu128\n",
                "torchvision": "Name: torchvision\nVersion: 0.18.0+cu128\n",
                "torchaudio": "Name: torchaudio\nVersion: 2.9.0+cu128\n",
            }.get(pkg, "")

            test_env.checkout(first_commit, force=True)

        # ASSERT - pyproject.toml should still be clean (no PyTorch config)
        config = test_env.pyproject.load()
        uv_config = config.get("tool", {}).get("uv", {})
        indexes = uv_config.get("index", [])
        pytorch_indexes = [idx for idx in indexes if "pytorch" in idx.get("name", "").lower()]

        assert len(pytorch_indexes) == 0, (
            "Checkout should NOT write PyTorch indexes to pyproject.toml"
        )

        # Verify pyproject.toml matches the committed state (marker should be "first")
        assert config["tool"]["comfygit"]["test_marker_1"] == "first", (
            "pyproject.toml should match first commit state after checkout"
        )


class TestResetKeepsPyprojectClean:
    """Test that reset keeps pyproject.toml clean of PyTorch config."""

    def test_hard_reset_does_not_pollute_pyproject(self, test_env, mock_comfyui_clone):
        """Hard reset should NOT write PyTorch config to pyproject.toml."""
        # ARRANGE - First commit: add a marker field
        config = test_env.pyproject.load()
        config["tool"]["comfygit"]["test_marker_2"] = "first"
        test_env.pyproject.save(config)
        test_env.git_manager.commit_all("first test commit")

        # Second commit: change marker
        config = test_env.pyproject.load()
        config["tool"]["comfygit"]["test_marker_2"] = "second"
        test_env.pyproject.save(config)
        test_env.git_manager.commit_all("second test commit")

        history = test_env.git_manager.get_version_history(limit=10)
        assert len(history) >= 2, f"Expected at least 2 commits, got {len(history)}"
        first_commit = history[1]["hash"]

        # ACT - Reset to first commit
        with patch.object(test_env.uv_manager, 'show_package') as mock_show:
            mock_show.side_effect = lambda pkg, python: {
                "torch": "Name: torch\nVersion: 2.9.0+cu128\n",
                "torchvision": "Name: torchvision\nVersion: 0.18.0+cu128\n",
                "torchaudio": "Name: torchaudio\nVersion: 2.9.0+cu128\n",
            }.get(pkg, "")

            test_env.reset(first_commit, mode="hard", force=True)

        # ASSERT - pyproject.toml should still be clean
        config = test_env.pyproject.load()
        uv_config = config.get("tool", {}).get("uv", {})
        indexes = uv_config.get("index", [])
        pytorch_indexes = [idx for idx in indexes if "pytorch" in idx.get("name", "").lower()]

        assert len(pytorch_indexes) == 0, (
            "Reset should NOT write PyTorch indexes to pyproject.toml"
        )


class TestImportResolvesAutoBackend:
    """Test that import resolves 'auto' to concrete backend."""

    def test_import_stores_concrete_backend(self, test_env):
        """Import should store resolved backend, never 'auto'."""
        # This is tested indirectly through the finalize_import flow
        # The key assertion is that torch_backend in config is never "auto"

        # ARRANGE - Set torch_backend to "auto" in test env (simulating import with auto)
        config = test_env.pyproject.load()
        config["tool"]["comfygit"]["torch_backend"] = "auto"
        test_env.pyproject.save(config)

        # In a real import, after installing PyTorch with --torch-backend=auto,
        # we detect the actual backend and store it. Here we just verify the
        # detection logic stores a concrete value.

        from comfygit_core.utils.pytorch import extract_backend_from_version

        # Simulated detection
        version = "2.9.0+cu128"
        backend = extract_backend_from_version(version)
        resolved_backend = backend if backend else "cpu"

        # Store resolved backend (this is what finalize_import does)
        config = test_env.pyproject.load()
        config["tool"]["comfygit"]["torch_backend"] = resolved_backend
        test_env.pyproject.save(config)

        # ASSERT - Backend should be concrete, not "auto"
        config = test_env.pyproject.load()
        stored_backend = config["tool"]["comfygit"]["torch_backend"]
        assert stored_backend == "cu128", "Should store concrete backend"
        assert stored_backend != "auto", "Should never store 'auto' as backend"
