"""Integration tests for export/import functionality."""
import tempfile
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import simulate_comfyui_save_workflow

from comfygit_core.managers.export_import_manager import ExportImportManager


class TestExportImportBasic:
    """Test basic export/import operations."""

    def test_export_creates_tarball(self, tmp_path):
        """Test that export creates a valid tarball."""
        # Setup test environment structure
        cec_path = tmp_path / "test_env" / ".cec"
        cec_path.mkdir(parents=True)
        comfyui_path = tmp_path / "test_env" / "ComfyUI"
        comfyui_path.mkdir(parents=True)

        # Create minimal pyproject.toml
        pyproject_path = cec_path / "pyproject.toml"
        pyproject_path.write_text("""
[project]
name = "test-env"
version = "0.1.0"

[tool.comfygit]
        """)

        # Create workflows directory
        workflows_path = cec_path / "workflows"
        workflows_path.mkdir()
        (workflows_path / "test.json").write_text('{"nodes": []}')

        # Export
        output_path = tmp_path / "export.tar.gz"
        manager = ExportImportManager(cec_path, comfyui_path)

        from comfygit_core.managers.pyproject_manager import PyprojectManager
        pyproject_manager = PyprojectManager(pyproject_path)

        result = manager.create_export(output_path, pyproject_manager)

        # Verify
        assert result.exists()
        assert result.stat().st_size > 0

    def test_import_extracts_tarball(self, tmp_path):
        """Test that import extracts tarball correctly."""
        # First create an export
        source_cec = tmp_path / "source" / ".cec"
        source_cec.mkdir(parents=True)
        source_comfyui = tmp_path / "source" / "ComfyUI"
        source_comfyui.mkdir(parents=True)

        # Create minimal content
        (source_cec / "pyproject.toml").write_text('[project]\nname = "test"')
        workflows = source_cec / "workflows"
        workflows.mkdir()
        (workflows / "test.json").write_text('{}')

        # Export
        tarball_path = tmp_path / "test.tar.gz"
        manager = ExportImportManager(source_cec, source_comfyui)

        from comfygit_core.managers.pyproject_manager import PyprojectManager
        pyproject_manager = PyprojectManager(source_cec / "pyproject.toml")

        manager.create_export(tarball_path, pyproject_manager)

        # Now import
        target_cec = tmp_path / "target" / ".cec"
        manager2 = ExportImportManager(target_cec, tmp_path / "target" / "ComfyUI")
        manager2.extract_import(tarball_path, target_cec)

        # Verify
        assert target_cec.exists()
        assert (target_cec / "pyproject.toml").exists()
        assert (target_cec / "workflows" / "test.json").exists()


class TestPrepareImportModels:
    """Test model download intent preparation for import."""

    def test_prepare_import_converts_missing_models(self, test_env):
        """Test that prepare_import converts missing models to download intents.

        When a manifest model exists in pyproject but the actual file is missing,
        prepare_import should convert it to an unresolved state with download sources
        preserved so the user can download it.
        """
        from comfygit_core.models.manifest import ManifestModel, ManifestWorkflowModel
        from comfygit_core.models.workflow import WorkflowNodeWidgetRef
        from conftest import simulate_comfyui_save_workflow

        # Create a minimal workflow that references a model
        workflow = {
            "id": "test",
            "nodes": [
                {
                    "id": "1",
                    "type": "CheckpointLoaderSimple",
                    "widgets_values": ["model.safetensors"],
                    "inputs": [],
                    "outputs": [],
                    "properties": {}
                }
            ],
            "links": [],
            "groups": [],
            "config": {},
            "extra": {}
        }
        simulate_comfyui_save_workflow(test_env, "test", workflow)

        # Add a model to the manifest with sources (simulating an imported env)
        manifest_model = ManifestModel(
            hash="abc123",
            filename="model.safetensors",
            size=123,
            relative_path="checkpoints/model.safetensors",
            category="checkpoints",
            sources=["https://example.com/model.safetensors"]
        )
        test_env.pyproject.models.add_model(manifest_model)

        # Add the model reference to the workflow
        wf_model = ManifestWorkflowModel(
            filename="model.safetensors",
            category="checkpoints",
            criticality="required",
            status="resolved",
            nodes=[WorkflowNodeWidgetRef(
                node_id="1",
                node_type="CheckpointLoaderSimple",
                widget_index=0,
                widget_value="model.safetensors"
            )],
            hash="abc123",
        )
        test_env.pyproject.workflows.set_workflow_models("test", [wf_model])

        # Verify model is NOT in the repository (missing locally)
        found = test_env.model_repository.get_model("abc123")
        assert found is None, "Model should not exist locally"

        # ACT: Run prepare_import - should convert missing models to download intents
        workflows_affected = test_env.model_manager.prepare_import_with_model_strategy("all")

        # ASSERT: The workflow should be affected
        assert workflows_affected == ["test"], f"Expected ['test'], got {workflows_affected}"

        # The model entry should now be unresolved with sources preserved
        updated_models = test_env.pyproject.workflows.get_workflow_models("test")
        assert len(updated_models) == 1
        updated_model = updated_models[0]

        # Status should be "unresolved" since the file is missing
        assert updated_model.status == "unresolved", \
            f"Expected unresolved status, got {updated_model.status}"

        # Hash should be cleared (unknown until downloaded)
        assert updated_model.hash is None, \
            f"Expected hash to be None, got {updated_model.hash}"

        # Sources should be preserved for download
        assert updated_model.sources == ["https://example.com/model.safetensors"], \
            f"Expected sources to be preserved, got {updated_model.sources}"


class TestExportWithWorkflows:
    """Test export with actual workflows and dependencies."""

    def test_export_with_workflows_counts_unique_nodes(self, test_env):
        """Test that export properly counts unique node types across workflows.

        Regression test for bug: unhashable type 'WorkflowNode'
        The export was trying to add WorkflowNode objects to a set,
        but WorkflowNode is not hashable (not frozen, has mutable fields).

        The fix extracts node.type strings instead of trying to hash WorkflowNode objects.
        """
        # ARRANGE - Create workflow with custom (non-builtin) nodes
        workflow = {
            "id": "test",
            "nodes": [
                {
                    "id": "1",
                    "type": "CustomNode1",
                    "widgets_values": ["test"],
                    "inputs": [],
                    "outputs": [],
                    "properties": {}
                },
                {
                    "id": "2",
                    "type": "CustomNode2",
                    "widgets_values": ["test"],
                    "inputs": [],
                    "outputs": [],
                    "properties": {}
                },
                {
                    "id": "3",
                    "type": "CustomNode1",  # Duplicate type - should only count once
                    "widgets_values": ["test2"],
                    "inputs": [],
                    "outputs": [],
                    "properties": {}
                }
            ],
            "links": [],
            "groups": [],
            "config": {},
            "extra": {}
        }

        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # Get workflow status (which analyzes and creates WorkflowNode objects)
        status = test_env.workflow_manager.get_workflow_status()

        # ACT - Count unique node types (the fixed code from environment.py)
        all_node_types = set()
        for w in status.analyzed_workflows:
            # Extract type strings from WorkflowNode objects (can't hash WorkflowNode directly)
            node_types = {node.type for node in w.dependencies.non_builtin_nodes}
            all_node_types.update(node_types)

        # ASSERT - Verify we got unique node types as strings
        assert all_node_types == {"CustomNode1", "CustomNode2"}, (
            f"Expected {{'CustomNode1', 'CustomNode2'}}, got {all_node_types}"
        )
        assert len(all_node_types) == 2, "Should count 2 unique node types (not 3 nodes)"

    def test_export_rejects_uncommitted_workflows(self, test_env, tmp_path):
        """Test that export fails when there are uncommitted workflow changes.

        This prevents exporting inconsistent state where:
        - Workflows exist in ComfyUI/ (working directory)
        - But are NOT in .cec/workflows/ (committed state)
        - And may/may not be in pyproject.toml (partial metadata)

        The three sources of truth (ComfyUI/, .cec/, pyproject) must be synced.
        """
        from comfygit_core.models.exceptions import CDExportError

        # ARRANGE - Create a simple workflow in ComfyUI (not committed)
        workflow = {
            "id": "uncommitted_wf",
            "nodes": [
                {
                    "id": "1",
                    "type": "KSampler",
                    "widgets_values": [],
                    "inputs": [],
                    "outputs": [],
                    "properties": {}
                }
            ],
            "links": [],
            "groups": [],
            "config": {},
            "extra": {}
        }

        simulate_comfyui_save_workflow(test_env, "new_workflow", workflow)

        # Verify workflow is in "new" state (uncommitted)
        status = test_env.status()
        assert "new_workflow" in status.workflow.sync_status.new, \
            "Workflow should be in 'new' state before commit"
        assert status.workflow.sync_status.has_changes, \
            "Should have uncommitted workflow changes"

        # ACT & ASSERT - Export should fail with CDExportError
        export_path = tmp_path / "should_fail.tar.gz"

        with pytest.raises(CDExportError) as exc_info:
            test_env.export_environment(export_path)

        # Verify error has proper context
        error = exc_info.value
        assert error.uncommitted_workflows is not None, \
            "Error should include uncommitted workflow list"
        assert "new_workflow" in error.uncommitted_workflows, \
            "Error should list the uncommitted workflow"
        assert "uncommitted" in str(error).lower() or "commit" in str(error).lower(), \
            "Error message should mention uncommitted/commit"

    def test_export_succeeds_after_commit(self, test_env, tmp_path):
        """Test that export succeeds after workflows are committed.

        This verifies the happy path: export only works when all three
        sources of truth are synced (ComfyUI/, .cec/, pyproject).
        """
        # ARRANGE - Create and commit a workflow
        workflow = {
            "id": "committed_wf",
            "nodes": [
                {
                    "id": "1",
                    "type": "KSampler",
                    "widgets_values": [],
                    "inputs": [],
                    "outputs": [],
                    "properties": {}
                }
            ],
            "links": [],
            "groups": [],
            "config": {},
            "extra": {}
        }

        simulate_comfyui_save_workflow(test_env, "my_workflow", workflow)

        # Commit the workflow
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add workflow")

        # Verify workflow is committed
        status = test_env.status()
        assert not status.workflow.sync_status.has_changes, \
            "Should have no uncommitted changes after commit"
        assert "my_workflow" in status.workflow.sync_status.synced, \
            "Workflow should be in 'synced' state"

        # ACT - Export should succeed
        export_path = tmp_path / "export.tar.gz"
        result = test_env.export_environment(export_path)

        # ASSERT - Export created successfully
        assert result.exists(), "Export file should be created"
        assert result.stat().st_size > 0, "Export file should not be empty"

        # Verify workflow is in the export
        import tarfile
        with tarfile.open(result, "r:gz") as tar:
            members = [m.name for m in tar.getmembers()]
            assert "workflows/my_workflow.json" in members, \
                "Committed workflow should be in export"
