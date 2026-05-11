"""TDD tests for batched pyproject writes during commit.

Tests that commit operations minimize pyproject.toml I/O by batching writes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import (
    simulate_comfyui_save_workflow,
)
from helpers.model_index_builder import ModelIndexBuilder
from helpers.workflow_builder import WorkflowBuilder


class TestPyprojectBatchWrites:
    """Test that commit operations batch pyproject writes efficiently."""

    def test_commit_multiple_workflows_minimal_loads(
        self,
        test_env,
        workflow_fixtures,
        monkeypatch
    ):
        """FAILING TEST: Commit with 3 workflows should only load pyproject 2 times.

        Expected behavior:
        - Load 1: Initial load at start of execute_commit
        - Load 2: (Optional) Final verification load

        Current behavior (SHOULD FAIL):
        - Loads 11+ times due to incremental writes in apply_resolution loop

        This test will PASS once batched writes are implemented.
        """
        # ARRANGE: Create test models
        builder = ModelIndexBuilder(test_env.workspace)
        builder.add_model("sd15.safetensors", "checkpoints", size_mb=4)
        builder.add_model("style.safetensors", "loras", size_mb=2)
        builder.add_model("vae.safetensors", "vae", size_mb=1)
        builder.index_all()

        # Create 3 different workflows
        workflow1 = (
            WorkflowBuilder()
            .add_checkpoint_loader("sd15.safetensors")
            .add_lora_loader("style.safetensors")
            .build()
        )
        workflow2 = (
            WorkflowBuilder()
            .add_checkpoint_loader("sd15.safetensors")
            .build()
        )
        workflow3 = (
            WorkflowBuilder()
            .add_checkpoint_loader("sd15.safetensors")
            .add_lora_loader("style.safetensors")
            .build()
        )

        # Simulate ComfyUI saving all 3 workflows
        simulate_comfyui_save_workflow(test_env, "workflow1", workflow1)
        simulate_comfyui_save_workflow(test_env, "workflow2", workflow2)
        simulate_comfyui_save_workflow(test_env, "workflow3", workflow3)

        # Get workflow status first (this will do some loads for analysis)
        workflow_status = test_env.workflow_manager.get_workflow_status()

        # NOW track pyproject load calls (only during execute_commit)
        load_count = 0
        original_load = test_env.pyproject.load

        def counting_load(force_reload=False):
            nonlocal load_count
            load_count += 1
            return original_load(force_reload=force_reload)

        monkeypatch.setattr(test_env.pyproject, "load", counting_load)

        # ACT: Execute commit (this should batch all writes)
        test_env.execute_commit(workflow_status, message="Test batched writes")

        # ASSERT: Should only load pyproject 1 time during execute_commit
        # (1 initial load at start of execute_commit, all mutations in-memory, 1 save at end)
        assert load_count <= 2, (
            f"Expected at most 2 pyproject loads during execute_commit, "
            f"but got {load_count}. This indicates inefficient incremental writes."
        )

        # Verify commit actually worked
        assert (test_env.cec_path / "workflows/workflow1.json").exists()
        assert (test_env.cec_path / "workflows/workflow2.json").exists()
        assert (test_env.cec_path / "workflows/workflow3.json").exists()

    def test_apply_resolution_with_config_no_save(self, test_env):
        """Test that apply_resolution with config parameter doesn't save to disk.

        This tests the core batching mechanism: when config is passed,
        mutations happen in-memory without disk writes.
        """
        # ARRANGE: Create test model
        builder = ModelIndexBuilder(test_env.workspace)
        builder.add_model("sd15.safetensors", "checkpoints", size_mb=4)
        builder.index_all()

        # Create and save workflow
        workflow = WorkflowBuilder().add_checkpoint_loader("sd15.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "test", workflow)

        # Get resolution
        deps, resolution = test_env.workflow_manager.analyze_and_resolve_workflow("test")

        # Track save calls
        save_count = 0
        original_save = test_env.pyproject.save

        def counting_save(config):
            nonlocal save_count
            save_count += 1
            return original_save(config)

        import unittest.mock as mock

        # ACT: Call apply_resolution with in-memory config
        config = test_env.pyproject.load()
        with mock.patch.object(test_env.pyproject, 'save', side_effect=counting_save):
            test_env.workflow_manager.apply_resolution(resolution, config=config)

        # ASSERT: No saves should have occurred
        assert save_count == 0, (
            f"apply_resolution with config should not save to disk, "
            f"but save was called {save_count} times"
        )

        # Verify mutations happened in memory
        assert "test" in config["tool"]["comfygit"]["workflows"]
        assert "models" in config["tool"]["comfygit"]

    def test_apply_resolution_without_config_saves_immediately(self, test_env):
        """Test that apply_resolution WITHOUT config still works (backward compat).

        When config is not provided, apply_resolution should work as before,
        loading and saving immediately. This ensures we don't break existing code.
        """
        # ARRANGE: Create test model
        builder = ModelIndexBuilder(test_env.workspace)
        builder.add_model("sd15.safetensors", "checkpoints", size_mb=4)
        builder.index_all()

        # Create and save workflow
        workflow = WorkflowBuilder().add_checkpoint_loader("sd15.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "test", workflow)

        # Get resolution
        deps, resolution = test_env.workflow_manager.analyze_and_resolve_workflow("test")

        # Track save calls
        save_count = 0
        original_save = test_env.pyproject.save

        def counting_save(config):
            nonlocal save_count
            save_count += 1
            return original_save(config)

        import unittest.mock as mock

        # ACT: Call apply_resolution WITHOUT config (legacy mode)
        with mock.patch.object(test_env.pyproject, 'save', side_effect=counting_save):
            test_env.workflow_manager.apply_resolution(resolution)

        # ASSERT: Should have saved (exact count may vary, just verify it happened)
        assert save_count > 0, (
            "apply_resolution without config should save to disk for backward compatibility"
        )

        # Verify it actually wrote to disk
        config = test_env.pyproject.load()
        assert "test" in config["tool"]["comfygit"]["workflows"]


class TestModelHandlerBatching:
    """Test ModelHandler methods support batched operations."""

    def test_add_model_with_config_no_save(self, test_env):
        """Test that add_model with config doesn't save."""
        from comfygit_core.models.manifest import ManifestModel

        # ARRANGE
        model = ManifestModel(
            hash="abc123",
            filename="test.safetensors",
            size=1234,
            relative_path="checkpoints/test.safetensors",
            category="checkpoints",
            sources=["https://example.com/model"]
        )

        config = test_env.pyproject.load()

        # Track saves
        save_count = 0
        original_save = test_env.pyproject.save

        def counting_save(cfg):
            nonlocal save_count
            save_count += 1
            return original_save(cfg)

        import unittest.mock as mock

        # ACT: Add model with config
        with mock.patch.object(test_env.pyproject, 'save', side_effect=counting_save):
            test_env.pyproject.models.add_model(model, config=config)

        # ASSERT
        assert save_count == 0, "add_model with config should not save"
        assert "abc123" in config["tool"]["comfygit"]["models"]

    def test_add_model_without_config_saves(self, test_env):
        """Test that add_model without config saves (backward compat)."""
        from comfygit_core.models.manifest import ManifestModel

        # ARRANGE
        model = ManifestModel(
            hash="xyz789",
            filename="test2.safetensors",
            size=5678,
            relative_path="checkpoints/test2.safetensors",
            category="checkpoints",
            sources=[]
        )

        # Track saves
        save_count = 0
        original_save = test_env.pyproject.save

        def counting_save(cfg):
            nonlocal save_count
            save_count += 1
            return original_save(cfg)

        import unittest.mock as mock

        # ACT: Add model without config (legacy)
        with mock.patch.object(test_env.pyproject, 'save', side_effect=counting_save):
            test_env.pyproject.models.add_model(model)

        # ASSERT
        assert save_count == 1, "add_model without config should save once"

        # Verify it persisted
        config = test_env.pyproject.load()
        assert "xyz789" in config["tool"]["comfygit"]["models"]


class TestWorkflowHandlerBatching:
    """Test WorkflowHandler methods support batched operations."""

    def test_set_node_packs_with_config_no_save(self, test_env):
        """Test that set_node_packs with config doesn't save."""
        # ARRANGE
        config = test_env.pyproject.load()

        # Track saves
        save_count = 0
        original_save = test_env.pyproject.save

        def counting_save(cfg):
            nonlocal save_count
            save_count += 1
            return original_save(cfg)

        import unittest.mock as mock

        # ACT
        with mock.patch.object(test_env.pyproject, 'save', side_effect=counting_save):
            test_env.pyproject.workflows.set_node_packs(
                "test_workflow",
                {"comfyui-test-node"},
                config=config
            )

        # ASSERT
        assert save_count == 0, "set_node_packs with config should not save"
        assert "test_workflow" in config["tool"]["comfygit"]["workflows"]
        assert "comfyui-test-node" in config["tool"]["comfygit"]["workflows"]["test_workflow"]["nodes"]

    def test_set_workflow_models_with_config_no_save(self, test_env):
        """Test that set_workflow_models with config doesn't save."""
        from comfygit_core.models.manifest import ManifestWorkflowModel, WorkflowNodeWidgetRef

        # ARRANGE
        config = test_env.pyproject.load()

        ref = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="CheckpointLoaderSimple",
            widget_index=0,
            widget_value="test.safetensors"
        )

        model = ManifestWorkflowModel(
            hash="abc123",
            filename="test.safetensors",
            category="checkpoints",
            criticality="flexible",
            status="resolved",
            nodes=[ref],
            sources=[]
        )

        # Track saves
        save_count = 0
        original_save = test_env.pyproject.save

        def counting_save(cfg):
            nonlocal save_count
            save_count += 1
            return original_save(cfg)

        import unittest.mock as mock

        # ACT
        with mock.patch.object(test_env.pyproject, 'save', side_effect=counting_save):
            test_env.pyproject.workflows.set_workflow_models(
                "test_workflow",
                [model],
                config=config
            )

        # ASSERT
        assert save_count == 0, "set_workflow_models with config should not save"
        assert "test_workflow" in config["tool"]["comfygit"]["workflows"]
        assert len(config["tool"]["comfygit"]["workflows"]["test_workflow"]["models"]) == 1

    def test_set_execution_contract_with_config_no_save(self, test_env):
        """Test that set_execution_contract with config doesn't save."""
        import unittest.mock as mock

        from comfygit_core.models.manifest import (
            NamedWorkflowContract,
            WorkflowContractInput,
            WorkflowContractOutput,
            WorkflowExecutionContract,
        )

        config = test_env.pyproject.load()
        contract = WorkflowExecutionContract(
            version=1,
            default_contract="default",
            contracts={
                "default": NamedWorkflowContract(
                    inputs=[
                        WorkflowContractInput(
                            name="prompt",
                            type="string",
                            node_id=6,
                            widget_idx=0,
                            required=True,
                            default="",
                        ),
                        WorkflowContractInput(
                            name="steps",
                            type="integer",
                            node_id=12,
                            widget_idx=2,
                            required=False,
                            default=30,
                            min=1,
                            max=150,
                        ),
                        WorkflowContractInput(
                            name="scheduler",
                            type="enum",
                            node_id=19,
                            widget_idx=0,
                            required=True,
                            enum_values=["normal", "karras", "exponential"],
                        ),
                    ],
                    outputs=[
                        WorkflowContractOutput(
                            name="image",
                            type="image",
                            node_id=27,
                            selector="primary",
                        ),
                    ],
                ),
            },
        )

        save_count = 0
        original_save = test_env.pyproject.save

        def counting_save(cfg):
            nonlocal save_count
            save_count += 1
            return original_save(cfg)

        with mock.patch.object(test_env.pyproject, 'save', side_effect=counting_save):
            test_env.pyproject.workflows.set_execution_contract(
                "test_workflow",
                contract,
                config=config,
            )

        assert save_count == 0, "set_execution_contract with config should not save"
        workflow = config["tool"]["comfygit"]["workflows"]["test_workflow"]
        assert workflow["path"] == "workflows/test_workflow.json"
        assert "execution_contract" in workflow
        assert "status" not in workflow["execution_contract"]

    def test_execution_contract_round_trip(self, test_env):
        """Execution contracts should round-trip through pyproject handlers."""
        from comfygit_core.models.manifest import (
            NamedWorkflowContract,
            WorkflowContractInput,
            WorkflowContractOutput,
            WorkflowExecutionContract,
        )

        contract = WorkflowExecutionContract(
            version=1,
            default_contract="default",
            contracts={
                "default": NamedWorkflowContract(
                    display_name="Default",
                    description="Primary contract",
                    inputs=[
                        WorkflowContractInput(
                            name="prompt",
                            type="string",
                            node_id=6,
                            widget_idx=0,
                            required=True,
                            default="",
                        ),
                    ],
                    outputs=[
                        WorkflowContractOutput(
                            name="image",
                            type="image",
                            node_id=27,
                            selector="primary",
                        ),
                    ],
                ),
            },
        )

        test_env.pyproject.workflows.set_execution_contract("demo", contract)

        loaded = test_env.pyproject.workflows.get_execution_contract("demo")
        assert loaded == contract
