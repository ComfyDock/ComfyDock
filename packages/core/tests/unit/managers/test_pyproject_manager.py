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


class TestWorkflowExecutionContractLoading:
    """Test workflow execution contracts load through the canonical model."""

    def test_get_execution_contract_loads_workflow_contract_model(self, temp_pyproject):
        from comfygit_core.models import WorkflowExecutionContract as PublicWorkflowExecutionContract
        from comfygit_core.models.workflow_contract import WorkflowExecutionContract

        manager = PyprojectManager(temp_pyproject)
        config = manager.load()
        config["tool"]["comfygit"]["workflows"] = {
            "simple_txt2img": {
                "path": "workflows/simple_txt2img.json",
                "execution_contract": {
                    "version": 1,
                    "default_contract": "default",
                    "contracts": {
                        "default": {
                            "display_name": "Default",
                            "description": "Primary API shape",
                            "inputs": [
                                {
                                    "name": "prompt",
                                    "type": "string",
                                    "node_id": 6,
                                    "widget_idx": 0,
                                    "required": True,
                                    "default": "a test prompt",
                                },
                                {
                                    "name": "steps",
                                    "type": "integer",
                                    "node_id": "3",
                                    "widget_index": 2,
                                    "required": False,
                                    "default": 30,
                                    "min": 1,
                                    "max": 150,
                                },
                            ],
                            "outputs": [
                                {
                                    "name": "image",
                                    "type": "image",
                                    "node_id": 9,
                                    "selector": "slot:0",
                                }
                            ],
                        }
                    },
                },
            }
        }
        manager.save(config)

        contract = manager.workflows.get_execution_contract("simple_txt2img")

        assert isinstance(contract, WorkflowExecutionContract)
        assert isinstance(contract, PublicWorkflowExecutionContract)
        assert contract is not None
        assert contract.active_contract is not None
        assert contract.active_contract.display_name == "Default"
        assert contract.active_contract.inputs[0].name == "prompt"
        assert contract.active_contract.inputs[1].widget_idx == 2
        assert contract.active_contract.inputs[1].widget_index == 2
        assert contract.active_contract.outputs[0].selector_slot == 0
        assert contract.to_public_schema() == {
            "inputs": [
                {
                    "name": "prompt",
                    "type": "string",
                    "node_id": 6,
                    "required": True,
                    "widget_idx": 0,
                    "default": "a test prompt",
                },
                {
                    "name": "steps",
                    "type": "integer",
                    "node_id": "3",
                    "required": False,
                    "widget_idx": 2,
                    "default": 30,
                    "min": 1,
                    "max": 150,
                },
            ],
            "outputs": [
                {
                    "name": "image",
                    "type": "image",
                    "node_id": 9,
                    "selector": "slot:0",
                }
            ],
        }

    def test_execution_contract_serializes_large_numeric_bounds_as_toml_safe_strings(self, temp_pyproject):
        import tomllib

        from comfygit_core.models.workflow_contract import (
            NamedWorkflowContract,
            WorkflowContractInput,
            WorkflowExecutionContract,
        )

        manager = PyprojectManager(temp_pyproject)
        large_uint64_bound = 18446744073709552000
        contract = WorkflowExecutionContract(
            contracts={
                "default": NamedWorkflowContract(
                    inputs=[
                        WorkflowContractInput(
                            name="seed",
                            type="number",
                            node_id="3",
                            required=True,
                            widget_idx=0,
                            default=large_uint64_bound,
                            min=0,
                            max=large_uint64_bound,
                        ),
                    ],
                    outputs=[],
                )
            }
        )

        manager.workflows.set_execution_contract("simple_txt2img", contract)
        content = temp_pyproject.read_text()

        assert f'default = "{large_uint64_bound}"' in content
        assert f'max = "{large_uint64_bound}"' in content
        tomllib.loads(content)

        loaded = manager.workflows.get_execution_contract("simple_txt2img")

        assert loaded is not None
        active = loaded.active_contract
        assert active is not None
        seed_input = active.inputs[0]
        assert seed_input.default == large_uint64_bound
        assert seed_input.max == large_uint64_bound
        assert loaded.to_public_schema()["inputs"][0]["default"] == large_uint64_bound
        assert loaded.to_public_schema()["inputs"][0]["max"] == large_uint64_bound

    def test_save_sanitizes_existing_raw_contract_numbers_for_uv(self, temp_pyproject):
        import tomllib

        manager = PyprojectManager(temp_pyproject)
        large_uint64_bound = 18446744073709552000
        config = manager.load()
        config["tool"]["comfygit"]["workflows"] = {
            "simple_txt2img": {
                "path": "workflows/simple_txt2img.json",
                "execution_contract": {
                    "version": 1,
                    "default_contract": "default",
                    "contracts": {
                        "default": {
                            "inputs": [
                                {
                                    "name": "seed",
                                    "type": "number",
                                    "node_id": "3",
                                    "required": True,
                                    "default": large_uint64_bound,
                                    "max": large_uint64_bound,
                                }
                            ],
                            "outputs": [],
                        }
                    },
                },
            }
        }

        manager.save(config)
        content = temp_pyproject.read_text()

        assert f'default = "{large_uint64_bound}"' in content
        assert f'max = "{large_uint64_bound}"' in content
        tomllib.loads(content)

    def test_get_manifest_snapshot_projects_major_manifest_sections(self, temp_pyproject):
        from comfygit_core.models import EnvironmentManifestSnapshot
        from comfygit_core.models.manifest import ManifestModel, ManifestWorkflowModel
        from comfygit_core.models.workflow import WorkflowNodeWidgetRef
        from comfygit_core.models.workflow_contract import (
            NamedWorkflowContract,
            WorkflowContractInput,
            WorkflowContractOutput,
            WorkflowExecutionContract,
        )

        manager = PyprojectManager(temp_pyproject)
        config = manager.load()
        config["dependency-groups"] = {
            "demo-node-a1b2c3d4": ["requests>=2"],
        }
        config["tool"]["uv"] = {
            "exclude-dependencies": ["opencv-python"],
            "constraint-dependencies": ["numpy<3"],
            "sources": {"demo-package": {"git": "https://example.invalid/demo.git"}},
        }
        manager.save(config)

        manager.nodes.add(
            NodeInfo(
                name="DemoNode",
                repository="https://example.invalid/DemoNode.git",
                version="abc123",
                source="git",
                criticality="optional",
            ),
            "demo-node",
        )
        manager.models.add_model(
            ManifestModel(
                hash="modelhash",
                filename="model.safetensors",
                size=123,
                relative_path="checkpoints/model.safetensors",
                category="checkpoints",
                sources=["https://example.invalid/model.safetensors"],
            )
        )
        manager.workflows.set_node_packs("simple_txt2img", {"demo-node"})
        manager.workflows.set_custom_node_mapping(
            "simple_txt2img",
            "DemoNodeType",
            "demo-node",
        )
        manager.workflows.set_workflow_models(
            "simple_txt2img",
            [
                ManifestWorkflowModel(
                    filename="model.safetensors",
                    category="checkpoints",
                    criticality="required",
                    status="resolved",
                    nodes=[
                        WorkflowNodeWidgetRef(
                            node_id="4",
                            node_type="CheckpointLoaderSimple",
                            widget_index=0,
                            widget_value="model.safetensors",
                        )
                    ],
                    hash="modelhash",
                )
            ],
        )
        manager.workflows.set_execution_contract(
            "simple_txt2img",
            WorkflowExecutionContract(
                contracts={
                    "default": NamedWorkflowContract(
                        inputs=[
                            WorkflowContractInput(
                                name="prompt",
                                type="string",
                                node_id="6",
                                widget_idx=0,
                                required=True,
                            )
                        ],
                        outputs=[
                            WorkflowContractOutput(
                                name="image",
                                type="image",
                                node_id="9",
                                selector="primary",
                            )
                        ],
                    )
                }
            ),
        )

        snapshot = manager.get_manifest_snapshot()

        assert isinstance(snapshot, EnvironmentManifestSnapshot)
        assert snapshot.project.name == "test-project"
        assert snapshot.comfyui_version == "v0.3.60"
        assert snapshot.python_version == "3.11"
        assert snapshot.uv.exclude_dependencies == ("opencv-python",)
        assert snapshot.uv.constraints == ("numpy<3",)
        assert snapshot.dependency_groups["demo-node-a1b2c3d4"] == ("requests>=2",)
        assert snapshot.nodes["demo-node"].criticality == "optional"
        assert snapshot.models["modelhash"].relative_path == "checkpoints/model.safetensors"

        workflow = snapshot.workflows["simple_txt2img"]
        assert workflow.path == "workflows/simple_txt2img.json"
        assert workflow.node_packs == ("demo-node",)
        assert workflow.custom_node_map["DemoNodeType"] == "demo-node"
        assert workflow.models[0].hash == "modelhash"
        assert workflow.has_execution_contract is True
        assert workflow.execution_contract is not None
        assert workflow.execution_contract.active_contract is not None
        assert workflow.execution_contract.active_contract.inputs[0].name == "prompt"

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
        assert 'criticality = "required"' in content

    def test_get_existing_defaults_missing_node_criticality_to_required(self, temp_pyproject):
        """Legacy manifests without node criticality should read as required."""
        manager = PyprojectManager(temp_pyproject)
        config = manager.load()
        config.setdefault("tool", {}).setdefault("comfygit", {})["nodes"] = {
            "legacy-node": {
                "name": "legacy-node",
                "version": "1.0.0",
                "source": "registry",
            }
        }
        manager.save(config)

        nodes = manager.nodes.get_existing()

        assert nodes["legacy-node"].criticality == "required"

    def test_add_node_preserves_optional_criticality(self, temp_pyproject):
        """Explicit optional criticality should round-trip through pyproject."""
        manager = PyprojectManager(temp_pyproject)
        node_info = NodeInfo(
            name="scratch-node",
            version="dev",
            source="development",
            criticality="optional",
        )

        manager.nodes.add(node_info, "scratch-node")

        nodes = manager.nodes.get_existing()
        assert nodes["scratch-node"].criticality == "optional"

    def test_set_node_criticality_updates_existing_node(self, temp_pyproject):
        """Users should be able to explicitly override package-level criticality."""
        manager = PyprojectManager(temp_pyproject)
        manager.nodes.add(
            NodeInfo(name="test-node", version="1.0.0", source="registry"),
            "test-node",
        )

        changed = manager.nodes.set_criticality("test-node", "optional")

        nodes = manager.nodes.get_existing()
        assert changed is True
        assert nodes["test-node"].criticality == "optional"

    def test_set_node_criticality_returns_false_for_missing_node(self, temp_pyproject):
        """Missing nodes should not create manifest entries while updating criticality."""
        manager = PyprojectManager(temp_pyproject)

        changed = manager.nodes.set_criticality("missing-node", "optional")

        assert changed is False

    def test_invalid_node_criticality_is_rejected(self, temp_pyproject):
        """Custom-node criticality intentionally supports only required or optional."""
        manager = PyprojectManager(temp_pyproject)
        manager.nodes.add(
            NodeInfo(name="test-node", version="1.0.0", source="registry"),
            "test-node",
        )

        with pytest.raises(ValueError, match="Invalid node criticality"):
            manager.nodes.set_criticality("test-node", "flexible")

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

    def test_manual_workflow_model_round_trips_without_nodes(self, temp_pyproject):
        """Manual workflow models can be stored without fake node references."""
        from comfygit_core.models.manifest import ManifestWorkflowModel

        manager = PyprojectManager(temp_pyproject)
        manual_model = ManifestWorkflowModel(
            hash="abc123hash",
            filename="custom-model.safetensors",
            category="custom_loader",
            criticality="required",
            status="resolved",
            nodes=[],
            relative_path="custom_loader/custom-model.safetensors",
            declared_by="manual",
        )

        manager.workflows.set_workflow_models("test_workflow", [manual_model])

        models = manager.workflows.get_workflow_models("test_workflow")
        assert len(models) == 1
        assert models[0].nodes == []
        assert models[0].relative_path == "custom_loader/custom-model.safetensors"
        assert models[0].declared_by == "manual"

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


class TestStripLocalPathSources:
    """Tests for stripping local path sources from pyproject."""

    def test_strip_local_path_sources_removes_local_paths(self, temp_pyproject):
        """Should remove sources that include local filesystem paths."""
        manager = PyprojectManager(temp_pyproject)

        config = manager.load()
        config.setdefault("tool", {})
        config["tool"].setdefault("uv", {})
        config["tool"]["uv"]["sources"] = {
            "local_pkg": {"path": "/tmp/local_pkg", "editable": True},
            "remote_pkg": {"url": "https://example.com/remote_pkg.whl"},
            "mixed_pkg": [
                {"url": "https://example.com/one.whl"},
                {"path": "/tmp/other"},
            ],
        }
        manager.save(config)

        removed = manager.strip_local_path_sources()
        assert set(removed) == {"local_pkg", "mixed_pkg"}

        updated = manager.load()
        sources = updated.get("tool", {}).get("uv", {}).get("sources", {})
        assert "local_pkg" not in sources
        assert "mixed_pkg" not in sources
        assert "remote_pkg" in sources

    def test_strip_and_readd_index_produces_array_of_tables(self, temp_pyproject):
        """Test that stripping indexes with list comprehension and re-adding preserves format.

        This tests the TOML formatting behavior: when indexes are stripped via list
        comprehension, add_index should still produce array-of-tables format ([[tool.uv.index]])
        instead of inline format (index = [{...}]).
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

        # Simulate stripping PyTorch indexes with list comprehension
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

    def test_initial_pyproject_has_system_uv_override(self):
        """Test that newly created pyproject.toml has the system uv override.

        exclude-dependencies is set by first sync() from package_config.toml,
        not hardcoded in initial config.
        """
        from comfygit_core.factories.environment_factory import EnvironmentFactory

        # Create initial pyproject config
        config = EnvironmentFactory._create_initial_pyproject(
            name="test-env",
            python_version="3.11",
            comfyui_version="v0.3.60",
            comfyui_version_type="tag",
            comfyui_commit_sha="abc123"
        )

        # Verify uv section exists with only system-tool policy.
        assert "tool" in config
        assert "uv" in config["tool"]
        assert config["tool"]["uv"] == {"override-dependencies": ["uv>=0.11.8"]}


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

    def test_set_exclude_dependencies_replaces_existing(self, temp_pyproject):
        """set_exclude_dependencies should replace, not merge."""
        manager = PyprojectManager(temp_pyproject)

        # Set initial exclusions
        manager.uv_config.set_exclude_dependencies(["pkg-a", "pkg-b"])
        config = manager.load(force_reload=True)
        assert config["tool"]["uv"]["exclude-dependencies"] == ["pkg-a", "pkg-b"]

        # Replace with different list
        manager.uv_config.set_exclude_dependencies(["pkg-c"])
        config = manager.load(force_reload=True)
        assert config["tool"]["uv"]["exclude-dependencies"] == ["pkg-c"]

    def test_set_exclude_dependencies_empty_removes_key(self, temp_pyproject):
        """Empty list should remove exclude-dependencies entirely."""
        manager = PyprojectManager(temp_pyproject)

        # Set some exclusions first
        manager.uv_config.set_exclude_dependencies(["pkg-a"])
        assert "exclude-dependencies" in manager.load(force_reload=True)["tool"]["uv"]

        # Set empty list
        manager.uv_config.set_exclude_dependencies([])
        config = manager.load(force_reload=True)
        # Key should be removed (or uv section might not exist if it was the only key)
        assert "exclude-dependencies" not in config.get("tool", {}).get("uv", {})


class TestSyncExtrasConfig:
    """Tests for default sync extras configuration."""

    def test_set_and_get_sync_extras(self, temp_pyproject):
        """Should store normalized sync extras under tool.comfygit.sync."""
        manager = PyprojectManager(temp_pyproject)

        manager.set_sync_extras(["CUDA", "vision"])

        assert manager.get_sync_extras() == ["cuda", "vision"]
        config = manager.load(force_reload=True)
        assert config["tool"]["comfygit"]["sync"]["extras"] == ["cuda", "vision"]

    def test_resolve_sync_extras_merges_defaults(self, temp_pyproject):
        """resolve_sync_extras should merge defaults with explicit extras."""
        manager = PyprojectManager(temp_pyproject)
        manager.set_sync_extras(["cuda"])

        extras, all_extras = manager.resolve_sync_extras(["vision"], False)

        assert all_extras is False
        assert extras == ["cuda", "vision"]
