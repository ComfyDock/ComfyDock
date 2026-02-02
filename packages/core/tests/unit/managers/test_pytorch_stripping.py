"""Tests for PyTorch config stripping from tracked pyproject.toml.

Phase 2 of PyTorch Temporary Injection Pattern:
- Strip PyTorch config from tracked pyproject.toml during environment creation
- Write .pytorch-backend file instead
- Migration for existing environments
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import tomlkit
from comfygit_core.managers.pyproject_manager import PyprojectManager


class TestStripPytorchConfig:
    """Tests for stripping PyTorch config from pyproject.toml."""

    @pytest.fixture
    def pyproject_with_pytorch(self):
        """Create a pyproject.toml with PyTorch config (as current code generates)."""
        with TemporaryDirectory() as tmpdir:
            cec_path = Path(tmpdir) / ".cec"
            cec_path.mkdir()
            pyproject_path = cec_path / "pyproject.toml"

            # This is what the current environment creation produces
            config = {
                "project": {
                    "name": "comfygit-env-test",
                    "version": "0.1.0",
                    "requires-python": ">=3.12",
                    "dependencies": []
                },
                "tool": {
                    "comfygit": {
                        "schema_version": 1,
                        "comfyui_version": "v0.3.60",
                        "python_version": "3.12",
                        "torch_backend": "cu128",
                        "nodes": {}
                    },
                    "uv": {
                        "index": [
                            {
                                "name": "pytorch-cu128",
                                "url": "https://download.pytorch.org/whl/cu128",
                                "explicit": True
                            }
                        ],
                        "sources": {
                            "torch": {"index": "pytorch-cu128"},
                            "torchvision": {"index": "pytorch-cu128"},
                            "torchaudio": {"index": "pytorch-cu128"},
                        },
                        "constraint-dependencies": [
                            "torch==2.9.0+cu128",
                            "torchvision==0.20.0+cu128",
                            "torchaudio==2.5.0+cu128",
                        ]
                    }
                }
            }

            with open(pyproject_path, 'w') as f:
                tomlkit.dump(config, f)

            yield {
                "cec_path": cec_path,
                "pyproject_path": pyproject_path,
            }

    def test_strip_pytorch_indexes(self, pyproject_with_pytorch):
        """Should remove PyTorch-related indexes from tool.uv.index."""
        pyproject = PyprojectManager(pyproject_with_pytorch["pyproject_path"])

        # Act: Strip PyTorch config
        pyproject.strip_pytorch_config()

        # Assert: No PyTorch indexes remain
        config = pyproject.load()
        indexes = config.get("tool", {}).get("uv", {}).get("index", [])

        pytorch_indexes = [idx for idx in indexes if "pytorch" in idx.get("name", "").lower()]
        assert len(pytorch_indexes) == 0, f"PyTorch indexes should be removed: {pytorch_indexes}"

    def test_strip_pytorch_sources(self, pyproject_with_pytorch):
        """Should remove PyTorch package sources from tool.uv.sources."""
        pyproject = PyprojectManager(pyproject_with_pytorch["pyproject_path"])

        # Act
        pyproject.strip_pytorch_config()

        # Assert: No PyTorch sources remain
        config = pyproject.load()
        sources = config.get("tool", {}).get("uv", {}).get("sources", {})

        pytorch_packages = {"torch", "torchvision", "torchaudio"}
        remaining_pytorch = pytorch_packages & set(sources.keys())
        assert len(remaining_pytorch) == 0, f"PyTorch sources should be removed: {remaining_pytorch}"

    def test_strip_pytorch_constraints(self, pyproject_with_pytorch):
        """Should remove PyTorch package constraints from tool.uv.constraint-dependencies."""
        pyproject = PyprojectManager(pyproject_with_pytorch["pyproject_path"])

        # Act
        pyproject.strip_pytorch_config()

        # Assert: No PyTorch constraints remain
        config = pyproject.load()
        constraints = config.get("tool", {}).get("uv", {}).get("constraint-dependencies", [])

        pytorch_packages = {"torch", "torchvision", "torchaudio"}
        pytorch_constraints = [c for c in constraints if any(pkg in c.lower() for pkg in pytorch_packages)]
        assert len(pytorch_constraints) == 0, f"PyTorch constraints should be removed: {pytorch_constraints}"

    def test_strip_preserves_non_pytorch_config(self, pyproject_with_pytorch):
        """Should preserve non-PyTorch uv config."""
        pyproject = PyprojectManager(pyproject_with_pytorch["pyproject_path"])

        # Add non-PyTorch config first
        config = pyproject.load()
        config["tool"]["uv"]["index"].append({
            "name": "mycompany",
            "url": "https://pypi.mycompany.com/simple",
            "explicit": True
        })
        config["tool"]["uv"]["sources"]["mypackage"] = {"index": "mycompany"}
        config["tool"]["uv"]["constraint-dependencies"].append("numpy>=1.24")
        pyproject.save(config)

        # Act
        pyproject.strip_pytorch_config()

        # Assert: Non-PyTorch config is preserved
        config = pyproject.load()
        indexes = config.get("tool", {}).get("uv", {}).get("index", [])
        sources = config.get("tool", {}).get("uv", {}).get("sources", {})
        constraints = config.get("tool", {}).get("uv", {}).get("constraint-dependencies", [])

        # Check preserved items
        index_names = [idx.get("name") for idx in indexes]
        assert "mycompany" in index_names
        assert "mypackage" in sources
        assert "numpy>=1.24" in constraints

    def test_strip_removes_torch_backend_field(self, pyproject_with_pytorch):
        """Should remove torch_backend from tool.comfygit section."""
        pyproject = PyprojectManager(pyproject_with_pytorch["pyproject_path"])

        # Verify it exists before
        config = pyproject.load()
        assert "torch_backend" in config["tool"]["comfygit"]

        # Act
        pyproject.strip_pytorch_config()

        # Assert
        config = pyproject.load()
        assert "torch_backend" not in config["tool"]["comfygit"]

    def test_strip_cleans_up_empty_uv_section(self, pyproject_with_pytorch):
        """Should remove empty tool.uv section after stripping."""
        pyproject = PyprojectManager(pyproject_with_pytorch["pyproject_path"])

        # Act: Strip on a pyproject that only has PyTorch config in tool.uv
        pyproject.strip_pytorch_config()

        # Assert: Empty sections are removed
        config = pyproject.load()
        # If tool.uv is empty, it should be removed
        uv_config = config.get("tool", {}).get("uv", {})
        if uv_config:
            # If uv section exists, it should have non-empty content
            assert uv_config.get("index") or uv_config.get("sources") or uv_config.get("constraint-dependencies"), \
                "Empty tool.uv section should be removed"


class TestWritePytorchBackendFile:
    """Tests for writing .pytorch-backend file."""

    @pytest.fixture
    def temp_cec(self):
        """Create a temporary .cec directory."""
        with TemporaryDirectory() as tmpdir:
            cec_path = Path(tmpdir) / ".cec"
            cec_path.mkdir()
            pyproject_path = cec_path / "pyproject.toml"

            config = {
                "project": {
                    "name": "test-env",
                    "version": "0.1.0",
                    "requires-python": ">=3.12",
                    "dependencies": []
                },
                "tool": {
                    "comfygit": {
                        "schema_version": 1,
                        "torch_backend": "cu128",
                    }
                }
            }

            with open(pyproject_path, 'w') as f:
                tomlkit.dump(config, f)

            yield {
                "cec_path": cec_path,
                "pyproject_path": pyproject_path,
            }

    def test_write_backend_file_from_pyproject(self, temp_cec):
        """Should write .pytorch-backend from torch_backend in pyproject.toml."""
        from comfygit_core.managers.pytorch_backend_manager import PyTorchBackendManager

        pytorch_manager = PyTorchBackendManager(temp_cec["cec_path"])
        pyproject = PyprojectManager(temp_cec["pyproject_path"])

        # Act: Extract backend from pyproject and write to file
        config = pyproject.load()
        backend = config["tool"]["comfygit"].get("torch_backend")
        if backend:
            pytorch_manager.set_backend(backend)

        # Assert
        backend_file = temp_cec["cec_path"] / ".pytorch-backend"
        assert backend_file.exists()
        assert backend_file.read_text().strip() == "cu128"


class TestMigratePytorchConfig:
    """Tests for migrating existing environments to new schema."""

    @pytest.fixture
    def legacy_pyproject(self):
        """Create a legacy pyproject.toml (schema v1 with inline PyTorch config)."""
        with TemporaryDirectory() as tmpdir:
            cec_path = Path(tmpdir) / ".cec"
            cec_path.mkdir()
            pyproject_path = cec_path / "pyproject.toml"

            # Legacy format - PyTorch config inline, schema v1
            config = {
                "project": {
                    "name": "comfygit-env-legacy",
                    "version": "0.1.0",
                    "requires-python": ">=3.12",
                    "dependencies": []
                },
                "tool": {
                    "comfygit": {
                        "schema_version": 1,
                        "comfyui_version": "v0.3.60",
                        "python_version": "3.12",
                        "torch_backend": "cu121",
                        "nodes": {}
                    },
                    "uv": {
                        "index": [
                            {
                                "name": "pytorch-cu121",
                                "url": "https://download.pytorch.org/whl/cu121",
                                "explicit": True
                            }
                        ],
                        "sources": {
                            "torch": {"index": "pytorch-cu121"},
                            "torchvision": {"index": "pytorch-cu121"},
                            "torchaudio": {"index": "pytorch-cu121"},
                        },
                        "constraint-dependencies": [
                            "torch==2.5.0+cu121",
                            "torchvision==0.20.0+cu121",
                            "torchaudio==2.5.0+cu121",
                        ]
                    }
                }
            }

            with open(pyproject_path, 'w') as f:
                tomlkit.dump(config, f)

            yield {
                "cec_path": cec_path,
                "pyproject_path": pyproject_path,
            }

    def test_migrate_does_not_create_backend_file(self, legacy_pyproject):
        """Migration should NOT create .pytorch-backend file (user must set explicitly)."""
        pyproject = PyprojectManager(legacy_pyproject["pyproject_path"])

        # Act: Run migration
        pyproject.migrate_pytorch_config()

        # Assert: .pytorch-backend file should NOT exist
        backend_file = legacy_pyproject["cec_path"] / ".pytorch-backend"
        assert not backend_file.exists(), ".pytorch-backend should NOT be created by migration"

    def test_migrate_strips_pytorch_from_pyproject(self, legacy_pyproject):
        """Migration should remove PyTorch config from pyproject.toml."""
        pyproject = PyprojectManager(legacy_pyproject["pyproject_path"])

        # Act
        pyproject.migrate_pytorch_config()

        # Assert: PyTorch config removed
        config = pyproject.load()

        # No torch_backend in comfygit section
        assert "torch_backend" not in config["tool"]["comfygit"]

        # No PyTorch indexes/sources/constraints
        uv_config = config.get("tool", {}).get("uv", {})
        indexes = uv_config.get("index", [])
        sources = uv_config.get("sources", {})
        constraints = uv_config.get("constraint-dependencies", [])

        assert not any("pytorch" in idx.get("name", "").lower() for idx in indexes)
        assert "torch" not in sources
        assert not any("torch==" in c for c in constraints)

    def test_migrate_bumps_schema_version(self, legacy_pyproject):
        """Migration should bump schema_version to 2."""
        pyproject = PyprojectManager(legacy_pyproject["pyproject_path"])

        # Act
        pyproject.migrate_pytorch_config()

        # Assert
        config = pyproject.load()
        assert config["tool"]["comfygit"]["schema_version"] == 2

    def test_migrate_is_idempotent(self, legacy_pyproject):
        """Running migration twice should not change anything after first run."""
        pyproject = PyprojectManager(legacy_pyproject["pyproject_path"])

        # Act: Run migration twice
        pyproject.migrate_pytorch_config()
        first_content = legacy_pyproject["pyproject_path"].read_text()

        pyproject.migrate_pytorch_config()
        second_content = legacy_pyproject["pyproject_path"].read_text()

        # Assert: Content unchanged after second migration
        assert first_content == second_content

    def test_migrate_skips_already_migrated(self, legacy_pyproject):
        """Should skip migration if schema_version is already 2."""
        pyproject = PyprojectManager(legacy_pyproject["pyproject_path"])

        # Setup: Set schema to v2 manually
        config = pyproject.load()
        config["tool"]["comfygit"]["schema_version"] = 2
        pyproject.save(config)

        original_content = legacy_pyproject["pyproject_path"].read_text()

        # Act
        result = pyproject.migrate_pytorch_config()

        # Assert: No changes made
        assert result is False, "Should return False when already migrated"
        assert legacy_pyproject["pyproject_path"].read_text() == original_content


class TestMigrateFromConstraintDependencies:
    """Tests for stripping embedded constraint-dependencies during migration."""

    @pytest.fixture
    def pyproject_with_constraints(self, tmp_path):
        """Create a pyproject with PyTorch in constraint-dependencies but NO torch_backend field."""
        cec_path = tmp_path / ".cec"
        cec_path.mkdir()
        pyproject_path = cec_path / "pyproject.toml"

        # This mimics old environments that had PyTorch configured via constraint-dependencies
        # but never had an explicit torch_backend field
        config = {
            "project": {"name": "test-env", "version": "0.1.0"},
            "tool": {
                "comfygit": {
                    "comfyui_version": "v0.4.0",
                    "python_version": "3.12",
                    # NOTE: No torch_backend or schema_version!
                },
                "uv": {
                    "constraint-dependencies": [
                        "torch==2.9.1+cu129",
                        "torchvision==0.24.1+cu129",
                        "torchaudio==2.9.1+cu129",
                    ],
                    "index": [
                        {"name": "pytorch-cu129", "url": "https://download.pytorch.org/whl/cu129", "explicit": True}
                    ],
                    "sources": {
                        "torch": {"index": "pytorch-cu129"},
                        "torchvision": {"index": "pytorch-cu129"},
                        "torchaudio": {"index": "pytorch-cu129"},
                    },
                },
            },
        }

        with open(pyproject_path, 'w') as f:
            tomlkit.dump(config, f)

        yield {"cec_path": cec_path, "pyproject_path": pyproject_path}

    def test_migrate_does_not_create_backend_file(self, pyproject_with_constraints):
        """Migration should NOT create .pytorch-backend file (user must set explicitly)."""
        pyproject = PyprojectManager(pyproject_with_constraints["pyproject_path"])

        # Act
        pyproject.migrate_pytorch_config()

        # Assert: .pytorch-backend file should NOT exist
        backend_file = pyproject_with_constraints["cec_path"] / ".pytorch-backend"
        assert not backend_file.exists(), ".pytorch-backend should NOT be created by migration"

    def test_migrate_strips_constraint_dependencies(self, pyproject_with_constraints):
        """Migration should strip PyTorch config including constraint-dependencies."""
        pyproject = PyprojectManager(pyproject_with_constraints["pyproject_path"])

        # Act
        pyproject.migrate_pytorch_config()

        # Assert: PyTorch config removed
        config = pyproject.load()
        uv_config = config.get("tool", {}).get("uv", {})
        constraints = uv_config.get("constraint-dependencies", [])

        # Should not have torch constraints anymore
        assert not any("torch" in c for c in constraints)

    def test_migrate_handles_missing_schema_version(self, pyproject_with_constraints):
        """Migration should treat missing schema_version as v1 and migrate."""
        pyproject = PyprojectManager(pyproject_with_constraints["pyproject_path"])

        # Verify schema_version is NOT in the config (the fixture doesn't include it)
        config = pyproject.load()
        assert "schema_version" not in config["tool"]["comfygit"]

        # Act
        result = pyproject.migrate_pytorch_config()

        # Assert: Migration should run (missing schema_version = v1)
        assert result is True

        # Assert: schema_version now set to 2
        config = pyproject.load()
        assert config["tool"]["comfygit"]["schema_version"] == 2


class TestStripPytorchConfigOutOfOrderTables:
    """Tests for stripping PyTorch config with out-of-order TOML tables.

    When pyproject.toml has split [tool.uv] sections (e.g., sources at top,
    more sources at bottom), tomlkit uses OutOfOrderTableProxy which has
    different behavior than regular Container when deleting keys.
    """

    @pytest.fixture
    def pyproject_with_out_of_order_tables(self):
        """Create pyproject.toml with out-of-order tool.uv sections.

        This reproduces the real-world structure where:
        - [[tool.uv.index]] is defined with AoT syntax
        - [tool.uv.sources.torch] etc are defined
        - Later, [tool.uv.sources.comfygit-core] is added separately

        This causes tomlkit to use OutOfOrderTableProxy.
        """
        with TemporaryDirectory() as tmpdir:
            cec_path = Path(tmpdir) / ".cec"
            cec_path.mkdir()
            pyproject_path = cec_path / "pyproject.toml"

            # Write TOML as string to preserve exact structure with AoT
            content = '''[project]
name = "comfygit-env-test"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["torch", "torchvision", "torchaudio"]

[tool.comfygit]
comfyui_version = "v0.3.75"
python_version = "3.12"

[tool.uv]
constraint-dependencies = ["torch==2.9.1+cu129", "torchvision==0.24.1+cu129", "torchaudio==2.9.1+cu129"]

[[tool.uv.index]]
name = "pytorch-cu129"
url = "https://download.pytorch.org/whl/cu129"
explicit = true

[tool.uv.sources.torch]
index = "pytorch-cu129"

[tool.uv.sources.torchvision]
index = "pytorch-cu129"

[tool.uv.sources.torchaudio]
index = "pytorch-cu129"

[dependency-groups]
system-nodes = ["comfygit-core>=0.3.5"]

[tool.uv.sources.comfygit-core]
path = "/path/to/local/core"
editable = true
'''
            pyproject_path.write_text(content)

            yield {"cec_path": cec_path, "pyproject_path": pyproject_path}

    def test_strip_handles_out_of_order_aot_tables(self, pyproject_with_out_of_order_tables):
        """Should not crash when stripping PyTorch config from out-of-order tables.

        Bug: When pyproject.toml has [[tool.uv.index]] (AoT syntax) and out-of-order
        [tool.uv.sources] sections, tomlkit uses OutOfOrderTableProxy. After filtering
        the AoT to an empty list and reassigning, `del uv_config['index']` raises
        NonExistentKey even though `'index' in uv_config` returns True.
        """
        pyproject = PyprojectManager(pyproject_with_out_of_order_tables["pyproject_path"])

        # This should NOT raise NonExistentKey
        pyproject.strip_pytorch_config()

        # Assert: PyTorch config is stripped
        config = pyproject.load()
        uv_config = config.get("tool", {}).get("uv", {})

        # Index should be gone (was only pytorch-cu129)
        assert "index" not in uv_config or len(uv_config.get("index", [])) == 0

        # PyTorch sources should be gone
        sources = uv_config.get("sources", {})
        assert "torch" not in sources
        assert "torchvision" not in sources
        assert "torchaudio" not in sources

        # Non-PyTorch source should remain
        assert "comfygit-core" in sources

        # PyTorch constraints should be gone
        constraints = uv_config.get("constraint-dependencies", [])
        assert not any("torch" in c for c in constraints)

    def test_migrate_handles_out_of_order_aot_tables(self, pyproject_with_out_of_order_tables):
        """Migration should work with out-of-order TOML tables."""
        pyproject = PyprojectManager(pyproject_with_out_of_order_tables["pyproject_path"])

        # This should NOT raise NonExistentKey
        result = pyproject.migrate_pytorch_config()

        assert result is True

        # Verify schema version updated
        config = pyproject.load()
        assert config["tool"]["comfygit"]["schema_version"] == 2
