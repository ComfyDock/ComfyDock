"""Tests for PyprojectManager TOML formatting."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import tomlkit

from comfygit_core.managers.pyproject_manager import PyprojectManager
from comfygit_core.models.shared import NodeInfo


@pytest.fixture
def temp_pyproject():
    """Create a temporary pyproject.toml for testing."""
    with TemporaryDirectory() as tmpdir:
        pyproject_path = Path(tmpdir) / "pyproject.toml"

        # Create a basic pyproject.toml structure
        initial_config = {
            "project": {
                "name": "test-project",
                "version": "0.1.0",
                "requires-python": ">=3.11",
                "dependencies": [],
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

        yield pyproject_path


class TestModelHandlerFormatting:
    """Test that model operations produce clean TOML output."""

    def test_add_required_model_only(self, temp_pyproject):
        """Test adding only required models doesn't create optional section."""
        from comfygit_core.models.manifest import ManifestModel
        manager = PyprojectManager(temp_pyproject)

        # Add a required model
        model = ManifestModel(
            hash="abc123",
            filename="test_model.safetensors",
            size=1234567,
            relative_path="checkpoints/test_model.safetensors",
            category="checkpoints"
        )
        manager.models.add_model(model)

        # Read the raw TOML output
        with open(temp_pyproject) as f:
            content = f.read()

        # Verify structure - models are now stored by hash
        assert "[tool.comfygit.models]" in content
        assert "abc123" in content

        # Verify inline table format (all on one line)
        lines = content.split('\n')
        model_line = [l for l in lines if 'abc123' in l][0]
        assert 'filename' in model_line
        assert 'size' in model_line
        assert 'relative_path' in model_line

    def test_add_optional_model_only(self, temp_pyproject):
        """Test adding models to global manifest."""
        from comfygit_core.models.manifest import ManifestModel
        manager = PyprojectManager(temp_pyproject)

        # Add a model
        model = ManifestModel(
            hash="xyz789",
            filename="optional_model.safetensors",
            size=9876543,
            relative_path="checkpoints/optional.safetensors",
            category="checkpoints"
        )
        manager.models.add_model(model)

        # Read the raw TOML output
        with open(temp_pyproject) as f:
            content = f.read()

        # Verify structure - global models section
        assert "[tool.comfygit.models]" in content
        assert "xyz789" in content

    def test_add_both_model_categories(self, temp_pyproject):
        """Test adding multiple models to global manifest."""
        from comfygit_core.models.manifest import ManifestModel
        manager = PyprojectManager(temp_pyproject)

        # Add multiple models
        model1 = ManifestModel(
            hash="req123",
            filename="required.safetensors",
            size=1000,
            relative_path="checkpoints/required.safetensors",
            category="checkpoints"
        )
        model2 = ManifestModel(
            hash="opt456",
            filename="optional.safetensors",
            size=2000,
            relative_path="loras/optional.safetensors",
            category="loras"
        )
        manager.models.add_model(model1)
        manager.models.add_model(model2)

        # Read the raw TOML output
        with open(temp_pyproject) as f:
            content = f.read()

        # Both models should be in global section
        assert "[tool.comfygit.models]" in content
        assert "req123" in content
        assert "opt456" in content

    def test_remove_all_models_cleans_sections(self, temp_pyproject):
        """Test removing all models cleans up empty sections."""
        from comfygit_core.models.manifest import ManifestModel
        manager = PyprojectManager(temp_pyproject)

        # Add models
        model1 = ManifestModel(hash="hash1", filename="model1.safetensors", size=1000, relative_path="checkpoints/model1.safetensors", category="checkpoints")
        model2 = ManifestModel(hash="hash2", filename="model2.safetensors", size=2000, relative_path="loras/model2.safetensors", category="loras")
        manager.models.add_model(model1)
        manager.models.add_model(model2)

        # Remove all models
        manager.models.remove_model("hash1")
        manager.models.remove_model("hash2")

        # Read the raw TOML output
        with open(temp_pyproject) as f:
            content = f.read()

        # Model sections should not exist
        assert "[tool.comfygit.models" not in content


class TestNodeHandlerFormatting:
    """Test that node operations produce clean TOML output."""

    def test_add_node(self, temp_pyproject):
        """Test adding a node creates the nodes section."""
        manager = PyprojectManager(temp_pyproject)

        node_info = NodeInfo(
            name="test-node",
            version="1.0.0",
            source="registry",
            registry_id="test-node-id",
            repository="https://github.com/test/node"
        )

        manager.nodes.add(node_info, "test-node-id")

        # Read the raw TOML output
        with open(temp_pyproject) as f:
            content = f.read()

        # Verify nodes section exists
        assert "[tool.comfygit.nodes" in content
        assert "test-node-id" in content

    def test_remove_all_nodes_cleans_section(self, temp_pyproject):
        """Test removing all nodes cleans up empty section."""
        manager = PyprojectManager(temp_pyproject)

        # Add a node
        node_info = NodeInfo(
            name="test-node",
            version="1.0.0",
            source="registry"
        )
        manager.nodes.add(node_info, "test-node-id")

        # Remove the node
        manager.nodes.remove("test-node-id")

        # Read the raw TOML output
        with open(temp_pyproject) as f:
            content = f.read()

        # Nodes section should not exist
        assert "[tool.comfygit.nodes]" not in content


class TestWorkflowModelDeduplication:
    """Test that workflow model entries don't duplicate when resolving to different filenames."""

    def test_resolving_unresolved_to_different_filename_replaces(self, temp_pyproject):
        """Test that resolving a model to a different filename replaces the unresolved entry."""
        from comfygit_core.models.manifest import ManifestWorkflowModel
        from comfygit_core.models.workflow import WorkflowNodeWidgetRef

        manager = PyprojectManager(temp_pyproject)

        # Create unresolved model entry (what analyze_workflow creates)
        unresolved_ref = WorkflowNodeWidgetRef(
            node_id="4",
            node_type="CheckpointLoaderSimple",
            widget_index=0,
            widget_value="v1-5-pruned-emaonly-fp16.safetensors"
        )
        unresolved_model = ManifestWorkflowModel(
            filename="v1-5-pruned-emaonly-fp16.safetensors",
            category="checkpoints",
            criticality="flexible",
            status="unresolved",
            nodes=[unresolved_ref]
        )

        # Add unresolved model
        manager.workflows.add_workflow_model("test_workflow", unresolved_model)

        # Verify it was added
        models = manager.workflows.get_workflow_models("test_workflow")
        assert len(models) == 1
        assert models[0].filename == "v1-5-pruned-emaonly-fp16.safetensors"
        assert models[0].status == "unresolved"
        assert models[0].hash is None

        # Now resolve to a DIFFERENT filename (user selected fuzzy match)
        resolved_model = ManifestWorkflowModel(
            hash="abc123hash",
            filename="v1-5-pruned-emaonly.safetensors",  # Different!
            category="checkpoints",
            criticality="flexible",
            status="resolved",
            nodes=[unresolved_ref]  # Same node reference!
        )

        # Add resolved model (progressive write)
        manager.workflows.add_workflow_model("test_workflow", resolved_model)

        # Verify: should have REPLACED the unresolved entry, not created duplicate
        models = manager.workflows.get_workflow_models("test_workflow")
        assert len(models) == 1, "Should not duplicate when resolving to different filename"
        assert models[0].filename == "v1-5-pruned-emaonly.safetensors"
        assert models[0].status == "resolved"
        assert models[0].hash == "abc123hash"


class TestCleanupBehavior:
    """Test the cleanup behavior of empty sections."""

    def test_empty_sections_removed_on_save(self, temp_pyproject):
        """Test that empty sections are automatically removed on save."""
        # Manually create config with empty sections
        config = {
            "project": {"name": "test"},
            "tool": {
                "comfygit": {
                    "python_version": "3.11",
                    "nodes": {},  # Empty
                    "models": {
                        "required": {},  # Empty
                        "optional": {}   # Empty
                    }
                }
            }
        }

        manager = PyprojectManager(temp_pyproject)
        manager.save(config)

        # Read back
        with open(temp_pyproject) as f:
            content = f.read()

        # Empty sections should be removed
        assert "[tool.comfygit.nodes]" not in content
        assert "[tool.comfygit.models" not in content


class TestPyprojectCaching:
    """Test instance-level caching behavior for pyproject.toml loading."""

    def test_multiple_loads_use_cache(self, temp_pyproject):
        """Multiple load() calls should use cached config, not reload from disk."""
        PyprojectManager.reset_load_stats()
        manager = PyprojectManager(temp_pyproject)

        # First load - should hit disk
        config1 = manager.load()
        stats1 = manager.get_load_stats()
        assert stats1['instance_loads'] == 1, "First load should read from disk"

        # Second load - should use cache
        config2 = manager.load()
        stats2 = manager.get_load_stats()
        assert stats2['instance_loads'] == 1, "Second load should use cache (no disk I/O)"

        # Third load - still cached
        config3 = manager.load()
        stats3 = manager.get_load_stats()
        assert stats3['instance_loads'] == 1, "Third load should use cache (no disk I/O)"

        # All configs should be identical
        assert config1 is config2, "Cached config should be same object"
        assert config2 is config3, "Cached config should be same object"

    def test_save_invalidates_cache(self, temp_pyproject):
        """Saving should invalidate cache, causing next load to read from disk."""
        PyprojectManager.reset_load_stats()
        manager = PyprojectManager(temp_pyproject)

        # Load once
        config = manager.load()
        assert manager.get_load_stats()['instance_loads'] == 1

        # Load again - should use cache
        manager.load()
        assert manager.get_load_stats()['instance_loads'] == 1

        # Modify and save
        config['project']['version'] = "2.0.0"
        manager.save(config)

        # Load after save - should reload from disk
        config_after_save = manager.load()
        stats = manager.get_load_stats()
        assert stats['instance_loads'] == 2, "Post-save load should reload from disk"
        assert config_after_save['project']['version'] == "2.0.0", "Should see updated version"

    def test_mtime_change_invalidates_cache(self, temp_pyproject):
        """Changing file mtime should invalidate cache."""
        import os

        PyprojectManager.reset_load_stats()
        manager = PyprojectManager(temp_pyproject)

        # Load once
        manager.load()
        assert manager.get_load_stats()['instance_loads'] == 1

        # Load again - cached
        manager.load()
        assert manager.get_load_stats()['instance_loads'] == 1

        # Bump mtime deterministically
        new_mtime = temp_pyproject.stat().st_mtime + 2
        os.utime(temp_pyproject, (new_mtime, new_mtime))

        # Load after mtime change - should reload
        manager.load()
        assert manager.get_load_stats()['instance_loads'] == 2, "Mtime change should trigger reload"

        # Load again - should use new cache
        manager.load()
        assert manager.get_load_stats()['instance_loads'] == 2, "Should use new cache"

    def test_force_reload_bypasses_cache(self, temp_pyproject):
        """force_reload=True should bypass cache and reload from disk."""
        PyprojectManager.reset_load_stats()
        manager = PyprojectManager(temp_pyproject)

        # Load once
        manager.load()
        assert manager.get_load_stats()['instance_loads'] == 1

        # Load with force_reload
        manager.load(force_reload=True)
        assert manager.get_load_stats()['instance_loads'] == 2, "force_reload should bypass cache"

        # Regular load should use newly cached config
        manager.load()
        assert manager.get_load_stats()['instance_loads'] == 2, "Should use cache from forced reload"

    def test_multiple_instances_have_independent_caches(self, temp_pyproject):
        """Multiple PyprojectManager instances should have independent caches."""
        PyprojectManager.reset_load_stats()

        # Create two managers for same file
        manager1 = PyprojectManager(temp_pyproject)
        manager2 = PyprojectManager(temp_pyproject)

        # Load with both
        config1 = manager1.load()
        config2 = manager2.load()

        # Both should have loaded from disk (independent caches)
        assert manager1.get_load_stats()['instance_loads'] == 1
        assert manager2.get_load_stats()['instance_loads'] == 1
        assert PyprojectManager._total_load_calls == 2

        # Configs are independent objects
        assert config1 is not config2, "Different instances should have different cached objects"

        # Second loads should use respective caches
        manager1.load()
        manager2.load()
        assert manager1.get_load_stats()['instance_loads'] == 1
        assert manager2.get_load_stats()['instance_loads'] == 1


class TestUVConfigFormatting:
    """Test that UV config operations produce consistent TOML formatting."""

    def test_add_index_produces_array_of_tables_format(self, temp_pyproject):
        """Test that add_index produces [[tool.uv.index]] format, not inline array.

        This is critical for git consistency - uv normalizes to array-of-tables format,
        so we should too to avoid spurious 'uncommitted changes' after checkout.
        """
        manager = PyprojectManager(temp_pyproject)

        # Add an index
        manager.uv_config.add_index(
            name="pytorch-cu129",
            url="https://download.pytorch.org/whl/cu129",
            explicit=True
        )

        # Read raw TOML content
        with open(temp_pyproject) as f:
            content = f.read()

        # Should use array-of-tables format [[tool.uv.index]]
        # NOT inline format: index = [{name = "...", ...}]
        assert "[[tool.uv.index]]" in content, (
            f"Expected array-of-tables format [[tool.uv.index]], got:\n{content}"
        )
        assert 'index = [{' not in content, (
            f"Should not use inline array format, got:\n{content}"
        )

        # Verify each field is on its own line
        assert '\nname = "pytorch-cu129"' in content
        assert '\nurl = "https://download.pytorch.org/whl/cu129"' in content
        assert '\nexplicit = true' in content

    def test_add_multiple_indexes_produces_multiple_array_of_tables(self, temp_pyproject):
        """Test that adding multiple indexes produces multiple [[tool.uv.index]] sections."""
        manager = PyprojectManager(temp_pyproject)

        # Add two indexes
        manager.uv_config.add_index("pytorch-cu129", "https://download.pytorch.org/whl/cu129", True)
        manager.uv_config.add_index("pytorch-cpu", "https://download.pytorch.org/whl/cpu", True)

        # Read raw TOML content
        with open(temp_pyproject) as f:
            content = f.read()

        # Should have two array-of-tables sections
        assert content.count("[[tool.uv.index]]") == 2, (
            f"Expected two [[tool.uv.index]] sections, got:\n{content}"
        )

    def test_update_existing_index_preserves_array_of_tables_format(self, temp_pyproject):
        """Test that updating an index preserves array-of-tables format."""
        manager = PyprojectManager(temp_pyproject)

        # Add index
        manager.uv_config.add_index("pytorch-cu129", "https://old-url.com", True)

        # Update it
        manager.uv_config.add_index("pytorch-cu129", "https://new-url.com", True)

        # Read raw TOML content
        with open(temp_pyproject) as f:
            content = f.read()

        # Should still use array-of-tables format
        assert "[[tool.uv.index]]" in content
        assert content.count("[[tool.uv.index]]") == 1
        assert "https://new-url.com" in content
        assert "https://old-url.com" not in content

    def test_index_format_roundtrip_preserves_style(self, temp_pyproject):
        """Test that loading and saving preserves array-of-tables format.

        This simulates what happens when git checkout restores a file and
        we then modify it - the format should be preserved.
        """
        # First, manually write array-of-tables format (like uv would)
        aot_content = '''[project]
name = "test-project"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[tool.comfygit]
comfyui_version = "v0.3.60"
python_version = "3.11"

[[tool.uv.index]]
name = "pytorch-cu129"
url = "https://download.pytorch.org/whl/cu129"
explicit = true
'''
        with open(temp_pyproject, 'w') as f:
            f.write(aot_content)

        manager = PyprojectManager(temp_pyproject)

        # Load, modify something else, save
        config = manager.load()
        config['tool']['comfygit']['python_version'] = "3.12"
        manager.save(config)

        # Read raw content
        with open(temp_pyproject) as f:
            content = f.read()

        # Array-of-tables format should be preserved
        assert "[[tool.uv.index]]" in content, (
            f"Array-of-tables format should be preserved after roundtrip, got:\n{content}"
        )

    def test_strip_and_readd_index_produces_array_of_tables(self, temp_pyproject):
        """Test that stripping indexes with list comprehension and re-adding preserves format.

        This is the critical bug scenario: after checkout, _override_pytorch_config_from_installed
        strips PyTorch indexes with a list comprehension, which creates a plain Python list.
        Then add_index appends to it, producing inline format instead of array-of-tables.
        """
        # Start with uv-formatted content (array-of-tables)
        uv_format = '''[project]
name = "test-project"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[tool.comfygit]
comfyui_version = "v0.3.60"
python_version = "3.11"

[tool.uv]
constraint-dependencies = ["torch==2.9.1+cu129"]

[[tool.uv.index]]
name = "pytorch-cu129"
url = "https://download.pytorch.org/whl/cu129"
explicit = true

[tool.uv.sources.torch]
index = "pytorch-cu129"
'''
        with open(temp_pyproject, 'w') as f:
            f.write(uv_format)

        manager = PyprojectManager(temp_pyproject)

        # Simulate _override_pytorch_config_from_installed stripping with list comprehension
        config = manager.load()
        indexes = config['tool']['uv'].get('index', [])
        config['tool']['uv']['index'] = [
            idx for idx in indexes
            if 'pytorch-' not in idx.get('name', '').lower()
        ]
        manager.save(config)

        # Now add the index back
        manager.uv_config.add_index("pytorch-cu129", "https://download.pytorch.org/whl/cu129", True)

        # Read raw content
        with open(temp_pyproject) as f:
            content = f.read()

        # Should use array-of-tables format, not inline
        assert "[[tool.uv.index]]" in content, (
            f"Expected array-of-tables format after strip-and-readd, got:\n{content}"
        )
        assert 'index = [{' not in content, (
            f"Should not use inline array format after strip-and-readd, got:\n{content}"
        )


class TestInitialPyprojectConfig:
    """Test initial pyproject.toml configuration."""

    def test_initial_pyproject_has_exclude_dependencies(self):
        """Test that newly created pyproject.toml includes exclude-dependencies."""
        from comfygit_core.factories.environment_factory import EnvironmentFactory

        # Create initial pyproject config
        config = EnvironmentFactory._create_initial_pyproject(
            name="test-env",
            python_version="3.11",
            comfyui_version="v0.3.60",
            comfyui_version_type="tag",
            comfyui_commit_sha="abc123"
        )

        # Verify exclude-dependencies exists
        assert "tool" in config
        assert "uv" in config["tool"]
        assert "exclude-dependencies" in config["tool"]["uv"]

        # Verify it includes opencv-python
        exclusions = config["tool"]["uv"]["exclude-dependencies"]
        assert "opencv-python" in exclusions


class TestExcludeDependencies:
    """Test exclude-dependencies handling in UV config."""

    def test_ensure_exclude_dependencies_adds_new(self, temp_pyproject):
        """Test that ensure_exclude_dependencies adds new packages."""
        manager = PyprojectManager(temp_pyproject)

        # Add exclude dependencies
        manager.uv_config.ensure_exclude_dependencies(["opencv-python", "some-other-package"])

        # Read config
        with open(temp_pyproject) as f:
            content = f.read()

        # Verify exclusions added
        assert "[tool.uv]" in content
        assert "exclude-dependencies" in content
        assert "opencv-python" in content
        assert "some-other-package" in content

    def test_ensure_exclude_dependencies_idempotent(self, temp_pyproject):
        """Test that ensure_exclude_dependencies is idempotent."""
        manager = PyprojectManager(temp_pyproject)

        # Add exclusions twice
        manager.uv_config.ensure_exclude_dependencies(["opencv-python"])
        manager.uv_config.ensure_exclude_dependencies(["opencv-python"])

        # Load config
        config = manager.load()
        exclusions = config['tool']['uv'].get('exclude-dependencies', [])

        # Should only appear once
        assert exclusions.count("opencv-python") == 1

    def test_ensure_exclude_dependencies_merges_with_existing(self, temp_pyproject):
        """Test that ensure_exclude_dependencies merges with existing exclusions."""
        # Manually create config with existing exclusions
        initial_config = {
            "project": {
                "name": "test-project",
                "version": "0.1.0",
                "requires-python": ">=3.11",
                "dependencies": [],
            },
            "tool": {
                "comfygit": {
                    "comfyui_version": "v0.3.60",
                    "python_version": "3.11",
                },
                "uv": {
                    "exclude-dependencies": ["existing-package"]
                }
            }
        }

        with open(temp_pyproject, 'w') as f:
            tomlkit.dump(initial_config, f)

        manager = PyprojectManager(temp_pyproject)

        # Add new exclusions
        manager.uv_config.ensure_exclude_dependencies(["opencv-python", "existing-package"])

        # Load config
        config = manager.load()
        exclusions = config['tool']['uv']['exclude-dependencies']

        # Should have both, no duplicates
        assert len(exclusions) == 2
        assert "existing-package" in exclusions
        assert "opencv-python" in exclusions