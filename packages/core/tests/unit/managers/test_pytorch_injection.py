"""Tests for PyTorch injection context manager."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import tomlkit
from comfygit_core.managers.overlay_manager import OverlayManager
from comfygit_core.managers.pyproject_manager import PyprojectManager
from comfygit_core.managers.pytorch_backend_manager import PyTorchBackendManager


class TestPyTorchInjectionContext:
    """Tests for PyTorch injection context manager."""

    @pytest.fixture
    def temp_env(self):
        """Create a temporary environment with pyproject.toml and .cec dir."""
        with TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir)
            cec_path = env_path / ".cec"
            cec_path.mkdir()

            # Create pyproject.toml
            pyproject_path = cec_path / "pyproject.toml"
            initial_config = {
                "project": {
                    "name": "test-env",
                    "version": "0.1.0",
                    "requires-python": ">=3.11",
                    "dependencies": ["numpy>=1.0"],
                },
                "tool": {
                    "comfygit": {
                        "comfyui_version": "v0.3.60",
                        "python_version": "3.11",
                    }
                }
            }
            with open(pyproject_path, 'w') as f:
                tomlkit.dump(initial_config, f)

            # Create .pytorch-backend file
            backend_file = cec_path / ".pytorch-backend"
            backend_file.write_text("cu128")

            yield {
                "env_path": env_path,
                "cec_path": cec_path,
                "pyproject_path": pyproject_path,
                "backend_file": backend_file,
            }

    def test_injection_adds_pytorch_config(self, temp_env):
        """Should inject PyTorch config before yielding."""
        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        # Read original content
        original_content = temp_env["pyproject_path"].read_text()
        assert "pytorch" not in original_content.lower()

        # Use injection context
        with pyproject.pytorch_injection_context(pytorch_manager):
            # Inside context, should have PyTorch config
            injected_content = temp_env["pyproject_path"].read_text()
            assert "pytorch-cu128" in injected_content
            assert "download.pytorch.org" in injected_content

    def test_injection_restores_on_success(self, temp_env):
        """Should restore original config after successful exit."""
        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        original_content = temp_env["pyproject_path"].read_text()

        with pyproject.pytorch_injection_context(pytorch_manager):
            # Inside context, config is injected
            pass

        # After context, should be restored to original
        restored_content = temp_env["pyproject_path"].read_text()
        assert restored_content == original_content

    def test_injection_restores_on_error(self, temp_env):
        """Should restore original config even when an error occurs."""
        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        original_content = temp_env["pyproject_path"].read_text()

        with pytest.raises(ValueError):
            with pyproject.pytorch_injection_context(pytorch_manager):
                # Simulate an error during sync
                raise ValueError("Simulated sync failure")

        # After error, should still be restored
        restored_content = temp_env["pyproject_path"].read_text()
        assert restored_content == original_content

    def test_injection_includes_index(self, temp_env):
        """Should inject PyTorch index configuration."""
        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        with pyproject.pytorch_injection_context(pytorch_manager):
            config = pyproject.load(force_reload=True)

            # Should have tool.uv.index
            uv_config = config.get("tool", {}).get("uv", {})
            indexes = uv_config.get("index", [])

            assert len(indexes) > 0
            pytorch_index = next(
                (idx for idx in indexes if "pytorch" in idx.get("name", "")),
                None
            )
            assert pytorch_index is not None
            assert "cu128" in pytorch_index.get("url", "")

    def test_injection_includes_sources(self, temp_env):
        """Should inject PyTorch package sources."""
        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        with pyproject.pytorch_injection_context(pytorch_manager):
            config = pyproject.load(force_reload=True)

            # Should have tool.uv.sources.torch
            uv_config = config.get("tool", {}).get("uv", {})
            sources = uv_config.get("sources", {})

            assert "torch" in sources

    def test_injection_preserves_existing_config(self, temp_env):
        """Should preserve existing non-PyTorch config during injection."""
        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        with pyproject.pytorch_injection_context(pytorch_manager):
            config = pyproject.load(force_reload=True)

            # Original config should still be there
            assert config["project"]["name"] == "test-env"
            assert "numpy>=1.0" in config["project"]["dependencies"]
            assert config["tool"]["comfygit"]["comfyui_version"] == "v0.3.60"

    def test_injection_with_different_backend(self, temp_env):
        """Should inject correct config based on backend file content."""
        # Change backend to cpu
        temp_env["backend_file"].write_text("cpu")

        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        with pyproject.pytorch_injection_context(pytorch_manager):
            content = temp_env["pyproject_path"].read_text()
            assert "pytorch-cpu" in content
            assert "/cpu" in content  # Should have cpu in URL path

    def test_injection_with_backend_override(self, temp_env):
        """Should use backend_override instead of file content when provided."""
        # Backend file says cu128
        temp_env["backend_file"].write_text("cu128")

        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        # Override to cu126
        with pyproject.pytorch_injection_context(pytorch_manager, backend_override="cu126"):
            content = temp_env["pyproject_path"].read_text()
            assert "pytorch-cu126" in content
            assert "cu128" not in content  # Should NOT have original backend
            assert "/cu126" in content  # Should have override backend in URL path


class TestPyTorchInjectionEdgeCases:
    """Tests for edge cases in PyTorch injection."""

    @pytest.fixture
    def temp_env(self):
        """Create a temporary environment."""
        with TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir)
            cec_path = env_path / ".cec"
            cec_path.mkdir()

            pyproject_path = cec_path / "pyproject.toml"
            initial_config = {
                "project": {
                    "name": "test-env",
                    "version": "0.1.0",
                    "requires-python": ">=3.11",
                    "dependencies": [],
                }
            }
            with open(pyproject_path, 'w') as f:
                tomlkit.dump(initial_config, f)

            backend_file = cec_path / ".pytorch-backend"
            backend_file.write_text("cu128")

            yield {
                "cec_path": cec_path,
                "pyproject_path": pyproject_path,
                "backend_file": backend_file,
            }

    def test_injection_with_existing_uv_config(self, temp_env):
        """Should merge with existing tool.uv config, not overwrite."""
        # Add existing uv config
        pyproject = PyprojectManager(temp_env["pyproject_path"])
        config = pyproject.load()
        config["tool"] = config.get("tool", {})
        config["tool"]["uv"] = {
            "index": [
                {"name": "pypi", "url": "https://pypi.org/simple", "explicit": False}
            ]
        }
        pyproject.save(config)

        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        with pyproject.pytorch_injection_context(pytorch_manager):
            injected_config = pyproject.load(force_reload=True)
            indexes = injected_config["tool"]["uv"]["index"]

            # Should have both original and PyTorch indexes
            index_names = [idx.get("name") for idx in indexes]
            assert "pypi" in index_names
            assert "pytorch-cu128" in index_names

    def test_injection_without_backend_file_raises_error(self, temp_env):
        """Should raise ValueError when .pytorch-backend file is missing."""
        # Remove backend file
        temp_env["backend_file"].unlink()

        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        # get_backend() should raise ValueError when file is missing
        # The error is raised inside the context manager initialization
        with pytest.raises(ValueError):
            with pyproject.pytorch_injection_context(pytorch_manager):
                pass


class TestInjectionStripsExistingConfig:
    """Test that injection handles polluted pyproject.toml."""

    @pytest.fixture
    def temp_env(self):
        """Create a temporary environment with polluted PyTorch config."""
        with TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir)
            cec_path = env_path / ".cec"
            cec_path.mkdir()

            # Create pyproject.toml with cu121 config (pollution)
            pyproject_path = cec_path / "pyproject.toml"
            polluted_config = {
                "project": {
                    "name": "test-env",
                    "version": "0.1.0",
                    "requires-python": ">=3.11",
                    "dependencies": ["numpy>=1.0"],
                },
                "tool": {
                    "comfygit": {
                        "comfyui_version": "v0.3.60",
                        "python_version": "3.11",
                    },
                    "uv": {
                        "index": [
                            {"name": "pytorch-cu121", "url": "https://download.pytorch.org/whl/cu121", "explicit": True}
                        ],
                        "sources": {
                            "torch": {"index": "pytorch-cu121"},
                            "torchvision": {"index": "pytorch-cu121"},
                            "torchaudio": {"index": "pytorch-cu121"},
                        },
                        "constraint-dependencies": [
                            "torch==2.5.0+cu121",
                            "numpy>=1.20.0",  # Non-PyTorch constraint
                        ]
                    }
                }
            }
            with open(pyproject_path, 'w') as f:
                tomlkit.dump(polluted_config, f)

            # Create .pytorch-backend file with different backend
            backend_file = cec_path / ".pytorch-backend"
            backend_file.write_text("cu128")

            yield {
                "cec_path": cec_path,
                "pyproject_path": pyproject_path,
                "backend_file": backend_file,
            }

    def test_injection_strips_conflicting_pytorch_config(self, temp_env):
        """Injection should strip existing PyTorch config before adding new."""
        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        # Verify polluted state before injection
        config = pyproject.load()
        indexes = config.get("tool", {}).get("uv", {}).get("index", [])
        cu121_indexes = [i for i in indexes if "cu121" in i.get("name", "")]
        assert len(cu121_indexes) == 1, "Should have cu121 pollution before test"

        # ACT - Use injection context
        with pyproject.pytorch_injection_context(pytorch_manager):
            # Inside context, check injected config
            injected_config = pyproject.load(force_reload=True)
            indexes = injected_config.get("tool", {}).get("uv", {}).get("index", [])

            # Old cu121 config should be stripped
            cu121_indexes = [i for i in indexes if "cu121" in i.get("name", "")]
            assert len(cu121_indexes) == 0, "Old cu121 indexes should be stripped"

            # New cu128 config should be injected
            cu128_indexes = [i for i in indexes if "cu128" in i.get("name", "")]
            assert len(cu128_indexes) == 1, "New cu128 index should be added"

            # Sources should point to new index
            sources = injected_config.get("tool", {}).get("uv", {}).get("sources", {})
            assert sources.get("torch", {}).get("index") == "pytorch-cu128"

            # Non-PyTorch constraints should be preserved
            constraints = injected_config.get("tool", {}).get("uv", {}).get("constraint-dependencies", [])
            numpy_constraints = [c for c in constraints if "numpy" in c]
            assert len(numpy_constraints) == 1, "Non-PyTorch constraints should be preserved"

    def test_injection_is_idempotent(self, temp_env):
        """Multiple injections should produce same result."""
        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        # First injection
        with pyproject.pytorch_injection_context(pytorch_manager):
            temp_env["pyproject_path"].read_text()

        # Reload the polluted state
        polluted_config = {
            "project": {
                "name": "test-env",
                "version": "0.1.0",
                "requires-python": ">=3.11",
                "dependencies": ["numpy>=1.0"],
            },
            "tool": {
                "comfygit": {
                    "comfyui_version": "v0.3.60",
                    "python_version": "3.11",
                },
                "uv": {
                    "index": [
                        {"name": "pytorch-cu121", "url": "https://download.pytorch.org/whl/cu121", "explicit": True}
                    ],
                    "sources": {
                        "torch": {"index": "pytorch-cu121"},
                    },
                }
            }
        }
        with open(temp_env["pyproject_path"], 'w') as f:
            tomlkit.dump(polluted_config, f)

        # Second injection on polluted file
        with pyproject.pytorch_injection_context(pytorch_manager):
            second_config = pyproject.load(force_reload=True)
            indexes = second_config.get("tool", {}).get("uv", {}).get("index", [])

            # Should still have exactly one cu128 index
            cu128_indexes = [i for i in indexes if "cu128" in i.get("name", "")]
            assert len(cu128_indexes) == 1, "Should have exactly one cu128 index"

            # No cu121 leftovers
            cu121_indexes = [i for i in indexes if "cu121" in i.get("name", "")]
            assert len(cu121_indexes) == 0, "Old config should be fully stripped"


class TestSyncProjectWithPyTorchManager:
    """Tests for sync_project with pytorch_manager parameter."""

    @pytest.fixture
    def temp_env(self):
        """Create a temporary environment with pyproject.toml and .cec dir."""
        with TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir)
            cec_path = env_path / ".cec"
            cec_path.mkdir()

            # Create pyproject.toml
            pyproject_path = cec_path / "pyproject.toml"
            initial_config = {
                "project": {
                    "name": "test-env",
                    "version": "0.1.0",
                    "requires-python": ">=3.11",
                    "dependencies": [],
                },
            }
            with open(pyproject_path, 'w') as f:
                tomlkit.dump(initial_config, f)

            # Create .pytorch-backend file
            backend_file = cec_path / ".pytorch-backend"
            backend_file.write_text("cu128")

            yield {
                "env_path": env_path,
                "cec_path": cec_path,
                "pyproject_path": pyproject_path,
                "backend_file": backend_file,
            }

    def test_sync_project_without_pytorch_manager_no_injection(self, temp_env):
        """sync_project without pytorch_manager should not inject config."""
        from unittest.mock import MagicMock

        from comfygit_core.managers.uv_project_manager import UVProjectManager

        pyproject = PyprojectManager(temp_env["pyproject_path"])

        # Mock UVCommand to avoid actual uv calls
        mock_uv_command = MagicMock()
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_uv_command.sync.return_value = mock_result

        # Create UVProjectManager with mock
        uv_manager = UVProjectManager(
            uv_command=mock_uv_command,
            pyproject_manager=pyproject,
            overlay_manager=OverlayManager(temp_env["cec_path"]),
        )

        # Sync without pytorch_manager
        uv_manager.sync_project()

        # Should NOT have PyTorch config
        content = temp_env["pyproject_path"].read_text()
        assert "pytorch" not in content.lower()

    def test_sync_project_with_pytorch_manager_uses_disposable_injection(self, temp_env):
        """sync_project should inject PyTorch config only into a temp project."""
        from types import SimpleNamespace

        from comfygit_core.managers.uv_project_manager import UVProjectManager

        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        original_content = temp_env["pyproject_path"].read_text()

        injected_content = None
        sync_cwd = None

        class FakeUVCommand:
            def for_cwd(self, cwd):
                self.cwd = cwd
                return self

            def sync(self, *args, **kwargs):
                nonlocal injected_content, sync_cwd
                sync_cwd = self.cwd
                injected_content = (self.cwd / "pyproject.toml").read_text()
                return SimpleNamespace(stdout="")

        fake_uv_command = FakeUVCommand()

        uv_manager = UVProjectManager(
            uv_command=fake_uv_command,
            pyproject_manager=pyproject,
            overlay_manager=OverlayManager(temp_env["cec_path"]),
        )

        # Sync with pytorch_manager
        uv_manager.sync_project(pytorch_manager=pytorch_manager)

        # During sync, should have had PyTorch config
        assert injected_content is not None
        assert "pytorch-cu128" in injected_content
        assert sync_cwd is not None
        assert not sync_cwd.exists()

        # The tracked pyproject should never have been injected.
        assert temp_env["pyproject_path"].read_text() == original_content

    def test_sync_project_backend_override_reinstalls_pytorch_runtime_packages(self, temp_env, monkeypatch):
        """Backend overrides should revalidate PyTorch's NVIDIA runtime wheels."""
        from unittest.mock import MagicMock

        from comfygit_core.constants import PYTORCH_CORE_PACKAGES, PYTORCH_PACKAGE_NAMES
        from comfygit_core.managers.uv_project_manager import UVProjectManager

        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        monkeypatch.setattr(
            "comfygit_core.utils.pytorch_prober.probe_pytorch_versions",
            lambda *_args, **_kwargs: (
                {
                    "torch": "2.11.0+cu129",
                    "torchvision": "0.26.0+cu129",
                    "torchaudio": "2.11.0+cu129",
                },
                "cu129",
            ),
        )

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_uv_command = MagicMock()
        mock_uv_command.for_cwd.return_value = mock_uv_command
        mock_uv_command.sync.return_value = mock_result

        uv_manager = UVProjectManager(
            uv_command=mock_uv_command,
            pyproject_manager=pyproject,
            overlay_manager=OverlayManager(temp_env["cec_path"]),
        )

        uv_manager.sync_project(pytorch_manager=pytorch_manager)
        normal_reinstall = mock_uv_command.sync.call_args.kwargs["reinstall_package"]
        assert normal_reinstall == sorted(PYTORCH_CORE_PACKAGES)

        uv_manager.sync_project(pytorch_manager=pytorch_manager, backend_override="cu129")
        override_reinstall = mock_uv_command.sync.call_args.kwargs["reinstall_package"]
        assert override_reinstall == sorted(PYTORCH_PACKAGE_NAMES)
        assert "nvidia-cusparselt-cu12" in override_reinstall
        assert "nvidia-nvshmem-cu12" in override_reinstall

    def test_sync_project_restores_on_sync_error(self, temp_env):
        """sync_project should restore config even when uv sync fails."""
        from unittest.mock import MagicMock

        from comfygit_core.managers.uv_project_manager import UVProjectManager
        from comfygit_core.models.exceptions import UVCommandError

        pyproject = PyprojectManager(temp_env["pyproject_path"])
        pytorch_manager = PyTorchBackendManager(temp_env["cec_path"])

        original_content = temp_env["pyproject_path"].read_text()

        # Mock UVCommand to raise error from the disposable project sync.
        mock_uv_command = MagicMock()
        mock_uv_command.for_cwd.return_value = mock_uv_command
        mock_uv_command.sync.side_effect = UVCommandError("Sync failed", returncode=1)

        uv_manager = UVProjectManager(
            uv_command=mock_uv_command,
            pyproject_manager=pyproject,
            overlay_manager=OverlayManager(temp_env["cec_path"]),
        )

        # Sync should raise error
        with pytest.raises(UVCommandError):
            uv_manager.sync_project(pytorch_manager=pytorch_manager)

        # After error, should still be restored to original
        restored_content = temp_env["pyproject_path"].read_text()
        assert restored_content == original_content

    def test_sync_project_with_overlay_copies_back_lock_not_pyproject(self, temp_env):
        """Overlay sync should use a disposable project and copy back only uv.lock."""
        from types import SimpleNamespace

        from comfygit_core.managers.uv_project_manager import UVProjectManager

        overlays_dir = temp_env["cec_path"] / "overlays"
        overlays_dir.mkdir(exist_ok=True)
        (overlays_dir / ".local.toml").write_text(
            """
[overlay]
description = "Local package override"

[sources.localpkg]
path = "../dev/localpkg"
editable = true
""".lstrip(),
            encoding="utf-8",
        )

        pyproject = PyprojectManager(temp_env["pyproject_path"])
        original_content = temp_env["pyproject_path"].read_text()
        expected_path = str((temp_env["cec_path"] / "../dev/localpkg").resolve())

        class FakeUVCommand:
            def for_cwd(self, cwd):
                self.cwd = cwd
                return self

            def sync(self, *args, **kwargs):
                config = tomlkit.parse((self.cwd / "pyproject.toml").read_text())
                source_path = config["tool"]["uv"]["sources"]["localpkg"]["path"]
                assert source_path == expected_path
                (self.cwd / "uv.lock").write_text("# temp lock\n", encoding="utf-8")
                return SimpleNamespace(stdout="synced")

        uv_manager = UVProjectManager(
            uv_command=FakeUVCommand(),
            pyproject_manager=pyproject,
            overlay_manager=OverlayManager(temp_env["cec_path"]),
        )

        assert uv_manager.sync_project() == "synced"
        assert temp_env["pyproject_path"].read_text() == original_content
        assert (temp_env["cec_path"] / "uv.lock").read_text(encoding="utf-8") == "# temp lock\n"
        assert not any((temp_env["cec_path"] / ".comfygit-tmp").glob("uv-project-*"))

    def test_sync_project_removes_stale_disposable_projects(self, temp_env):
        """A previous interrupted sync should not poison the next resolution."""
        from types import SimpleNamespace

        from comfygit_core.managers.uv_project_manager import UVProjectManager

        overlays_dir = temp_env["cec_path"] / "overlays"
        overlays_dir.mkdir(exist_ok=True)
        (overlays_dir / ".local.toml").write_text(
            """
[overlay]
description = "Local package override"

[sources.localpkg]
path = "/tmp/localpkg"
editable = true
""".lstrip(),
            encoding="utf-8",
        )
        stale_path = temp_env["cec_path"] / ".comfygit-tmp" / "uv-project-stale"
        stale_path.mkdir(parents=True)
        (stale_path / "marker").write_text("stale", encoding="utf-8")

        class FakeUVCommand:
            def for_cwd(self, cwd):
                assert not stale_path.exists()
                self.cwd = cwd
                return self

            def sync(self, *args, **kwargs):
                return SimpleNamespace(stdout="")

        uv_manager = UVProjectManager(
            uv_command=FakeUVCommand(),
            pyproject_manager=PyprojectManager(temp_env["pyproject_path"]),
            overlay_manager=OverlayManager(temp_env["cec_path"]),
        )

        uv_manager.sync_project()
        assert not any((temp_env["cec_path"] / ".comfygit-tmp").glob("uv-project-*"))
