"""Tests for schema_version preservation in pyproject.toml operations."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import tomlkit
from comfygit_core.managers.pyproject_manager import PyprojectManager


class TestSchemaVersionPreservation:
    """Tests for schema_version field preservation in _ensure_section_spacing."""

    @pytest.fixture
    def temp_pyproject(self):
        """Create a temporary pyproject.toml for testing."""
        with TemporaryDirectory() as tmpdir:
            pyproject_path = Path(tmpdir) / "pyproject.toml"
            yield pyproject_path

    def test_ensure_section_spacing_preserves_schema_version(self, temp_pyproject):
        """schema_version should be preserved after _ensure_section_spacing runs.

        This tests the bug where schema_version was being dropped because it wasn't
        in the metadata fields list used when rebuilding the [tool.comfygit] table.
        """
        # Create pyproject.toml with schema_version and workflows
        initial_config = {
            "project": {"name": "test", "version": "0.1.0"},
            "tool": {
                "comfygit": {
                    "schema_version": 2,
                    "comfyui_version": "v0.3.60",
                    "python_version": "3.11",
                    "workflows": {
                        "test_workflow": {
                            "path": "workflows/test_workflow.json"
                        }
                    }
                }
            }
        }
        with open(temp_pyproject, 'w') as f:
            tomlkit.dump(initial_config, f)

        # Load and save (this triggers _ensure_section_spacing)
        manager = PyprojectManager(temp_pyproject)
        config = manager.load()
        manager.save(config)

        # Reload and verify schema_version is preserved
        reloaded = manager.load(force_reload=True)
        assert "schema_version" in reloaded["tool"]["comfygit"], \
            "schema_version should be preserved after save"
        assert reloaded["tool"]["comfygit"]["schema_version"] == 2

    def test_schema_version_preserved_with_models_section(self, temp_pyproject):
        """schema_version should be preserved when models section exists."""
        initial_config = {
            "project": {"name": "test", "version": "0.1.0"},
            "tool": {
                "comfygit": {
                    "schema_version": 2,
                    "comfyui_version": "v0.3.60",
                    "python_version": "3.11",
                    "models": {
                        "abc123": {"filename": "model.safetensors", "size": 1000}
                    }
                }
            }
        }
        with open(temp_pyproject, 'w') as f:
            tomlkit.dump(initial_config, f)

        manager = PyprojectManager(temp_pyproject)
        config = manager.load()
        manager.save(config)

        reloaded = manager.load(force_reload=True)
        assert reloaded["tool"]["comfygit"]["schema_version"] == 2

    def test_schema_version_preserved_with_nodes_and_workflows(self, temp_pyproject):
        """schema_version should be preserved with all sections present."""
        initial_config = {
            "project": {"name": "test", "version": "0.1.0"},
            "tool": {
                "comfygit": {
                    "schema_version": 2,
                    "comfyui_version": "v0.3.60",
                    "python_version": "3.11",
                    "manifest_state": "local",
                    "nodes": {
                        "test-node": {"name": "TestNode", "source": "github"}
                    },
                    "workflows": {
                        "test_workflow": {"path": "workflows/test.json"}
                    },
                    "models": {
                        "hash123": {"filename": "model.safetensors", "size": 500}
                    }
                }
            }
        }
        with open(temp_pyproject, 'w') as f:
            tomlkit.dump(initial_config, f)

        manager = PyprojectManager(temp_pyproject)
        config = manager.load()
        manager.save(config)

        reloaded = manager.load(force_reload=True)
        assert reloaded["tool"]["comfygit"]["schema_version"] == 2
        assert reloaded["tool"]["comfygit"]["comfyui_version"] == "v0.3.60"
        assert reloaded["tool"]["comfygit"]["manifest_state"] == "local"

    def test_ensure_section_spacing_preserves_sync_subtable(self, temp_pyproject):
        """sync extras should survive formatting when workflows/models exist."""
        initial_config = {
            "project": {"name": "test", "version": "0.1.0"},
            "tool": {
                "comfygit": {
                    "schema_version": 2,
                    "comfyui_version": "v0.3.60",
                    "python_version": "3.11",
                    "sync": {"extras": ["xformers"]},
                    "workflows": {
                        "test_workflow": {"path": "workflows/test.json"}
                    },
                    "models": {
                        "hash123": {"filename": "model.safetensors", "size": 500}
                    },
                }
            },
        }
        with open(temp_pyproject, "w") as f:
            tomlkit.dump(initial_config, f)

        manager = PyprojectManager(temp_pyproject)
        manager.save(manager.load())

        reloaded = manager.load(force_reload=True)
        assert reloaded["tool"]["comfygit"]["sync"]["extras"] == ["xformers"]

    def test_set_sync_extras_persists_with_workflows_and_models(self, temp_pyproject):
        """set_sync_extras should persist after formatting rewrites comfygit."""
        initial_config = {
            "project": {"name": "test", "version": "0.1.0"},
            "tool": {
                "comfygit": {
                    "schema_version": 2,
                    "workflows": {
                        "test_workflow": {"path": "workflows/test.json"}
                    },
                    "models": {
                        "hash123": {"filename": "model.safetensors", "size": 500}
                    },
                }
            },
        }
        with open(temp_pyproject, "w") as f:
            tomlkit.dump(initial_config, f)

        manager = PyprojectManager(temp_pyproject)
        manager.set_sync_extras(["xformers"])

        assert manager.get_sync_extras() == ["xformers"]
        assert "xformers" in temp_pyproject.read_text()
