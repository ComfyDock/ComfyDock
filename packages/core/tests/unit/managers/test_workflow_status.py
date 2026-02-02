"""Tests for enhanced WorkflowManager status system."""

from pathlib import Path

from comfygit_core.models.workflow import (
    DetailedWorkflowStatus,
    WorkflowAnalysisStatus,
    WorkflowSyncStatus,
)


class TestWorkflowSyncStatus:
    """Test WorkflowSyncStatus dataclass."""

    def test_has_changes_with_new_workflows(self):
        """Test has_changes property with new workflows."""
        status = WorkflowSyncStatus(new=["workflow1"], modified=[], deleted=[], synced=[])
        assert status.has_changes is True

    def test_has_changes_with_modified_workflows(self):
        """Test has_changes property with modified workflows."""
        status = WorkflowSyncStatus(new=[], modified=["workflow1"], deleted=[], synced=[])
        assert status.has_changes is True

    def test_has_changes_with_deleted_workflows(self):
        """Test has_changes property with deleted workflows."""
        status = WorkflowSyncStatus(new=[], modified=[], deleted=["workflow1"], synced=[])
        assert status.has_changes is True

    def test_has_changes_with_only_synced(self):
        """Test has_changes property with only synced workflows."""
        status = WorkflowSyncStatus(new=[], modified=[], deleted=[], synced=["workflow1"])
        assert status.has_changes is False

    def test_total_count(self):
        """Test total_count property."""
        status = WorkflowSyncStatus(
            new=["wf1", "wf2"],
            modified=["wf3"],
            deleted=["wf4"],
            synced=["wf5", "wf6"]
        )
        assert status.total_count == 6


class TestDetailedWorkflowStatus:
    """Test DetailedWorkflowStatus dataclass."""

    def test_total_issues_with_no_issues(self):
        """Test total_issues when no workflows have issues."""
        from comfygit_core.models.workflow import (
            ResolutionResult,
            WorkflowDependencies,
        )

        sync_status = WorkflowSyncStatus(synced=["wf1"])
        analysis = WorkflowAnalysisStatus(
            name="wf1",
            sync_state="synced",
            dependencies=WorkflowDependencies(workflow_name="wf1"),
            resolution=ResolutionResult(workflow_name="wf1")  # No issues
        )

        status = DetailedWorkflowStatus(
            sync_status=sync_status,
            analyzed_workflows=[analysis]
        )

        assert status.total_issues == 0
        assert status.is_commit_safe is True

    def test_total_issues_with_unresolved_models(self):
        """Test total_issues with unresolved models."""
        from comfygit_core.models.workflow import (
            ResolutionResult,
            WorkflowDependencies,
            WorkflowNodeWidgetRef,
        )

        sync_status = WorkflowSyncStatus(modified=["wf1"])

        model_ref = WorkflowNodeWidgetRef(
            node_id="3",
            node_type="CheckpointLoaderSimple",
            widget_index=0,
            widget_value="model.safetensors"
        )

        analysis = WorkflowAnalysisStatus(
            name="wf1",
            sync_state="modified",
            dependencies=WorkflowDependencies(workflow_name="wf1"),
            resolution=ResolutionResult(workflow_name="wf1", models_unresolved=[model_ref])
        )

        status = DetailedWorkflowStatus(
            sync_status=sync_status,
            analyzed_workflows=[analysis]
        )

        assert status.total_issues == 1
        assert status.total_unresolved_models == 1
        assert status.is_commit_safe is False


class TestWorkflowAnalysisStatusDownloadIntents:
    """Test WorkflowAnalysisStatus download intent detection."""

    def test_has_issues_with_download_intents(self):
        """Test that has_issues returns True when download intents are present."""
        from comfygit_core.models.workflow import (
            ResolutionResult,
            ResolvedModel,
            WorkflowDependencies,
            WorkflowNodeWidgetRef,
        )

        WorkflowSyncStatus(synced=["wf1"])

        model_ref = WorkflowNodeWidgetRef(
            node_id="4",
            node_type="CheckpointLoaderSimple",
            widget_index=0,
            widget_value="model.safetensors"
        )

        # Create resolved model with download_intent match_type
        download_intent = ResolvedModel(
            workflow="wf1",
            reference=model_ref,
            match_type="download_intent",
            resolved_model=None,
            model_source="https://example.com/model.safetensors",
            target_path=Path("checkpoints/model.safetensors"),
            is_optional=False,
            match_confidence=1.0
        )

        analysis = WorkflowAnalysisStatus(
            name="wf1",
            sync_state="synced",
            dependencies=WorkflowDependencies(workflow_name="wf1"),
            resolution=ResolutionResult(
                workflow_name="wf1",
                models_resolved=[download_intent]
            )
        )

        assert analysis.has_issues is True

    def test_has_issues_without_download_intents(self):
        """Test that has_issues returns False when no download intents."""
        from comfygit_core.models.workflow import (
            ResolutionResult,
            WorkflowDependencies,
        )

        analysis = WorkflowAnalysisStatus(
            name="wf1",
            sync_state="synced",
            dependencies=WorkflowDependencies(workflow_name="wf1"),
            resolution=ResolutionResult(workflow_name="wf1")
        )

        assert analysis.has_issues is False

    def test_download_intents_count(self):
        """Test download_intents_count property."""
        from comfygit_core.models.workflow import (
            ResolutionResult,
            ResolvedModel,
            WorkflowDependencies,
            WorkflowNodeWidgetRef,
        )

        ref1 = WorkflowNodeWidgetRef(
            node_id="4",
            node_type="CheckpointLoaderSimple",
            widget_index=0,
            widget_value="model1.safetensors"
        )

        ref2 = WorkflowNodeWidgetRef(
            node_id="10",
            node_type="LoraLoader",
            widget_index=0,
            widget_value="lora.safetensors"
        )

        download1 = ResolvedModel(
            workflow="wf1",
            reference=ref1,
            match_type="download_intent",
            model_source="https://example.com/model1.safetensors",
            target_path=Path("checkpoints/model1.safetensors")
        )

        download2 = ResolvedModel(
            workflow="wf1",
            reference=ref2,
            match_type="download_intent",
            model_source="https://example.com/lora.safetensors",
            target_path=Path("loras/lora.safetensors")
        )

        # Add a regular resolved model
        regular_model = ResolvedModel(
            workflow="wf1",
            reference=ref1,
            match_type="exact",
            resolved_model=None
        )

        analysis = WorkflowAnalysisStatus(
            name="wf1",
            sync_state="synced",
            dependencies=WorkflowDependencies(workflow_name="wf1"),
            resolution=ResolutionResult(
                workflow_name="wf1",
                models_resolved=[download1, download2, regular_model]
            )
        )

        assert analysis.download_intents_count == 2


class TestIssueSummaryConsistency:
    """Test that issue_summary is consistent with has_issues.

    The key invariant: if has_issues is True, issue_summary must NOT be "No issues".
    """

    def test_issue_summary_with_uninstalled_nodes(self):
        """issue_summary should include uninstalled nodes when they exist.

        This tests the semantic bug where has_issues=True (due to uninstalled nodes)
        but issue_summary="No issues" (because it only checked resolution failures).
        """
        from comfygit_core.models.workflow import (
            ResolutionResult,
            WorkflowDependencies,
        )

        analysis = WorkflowAnalysisStatus(
            name="wf1",
            sync_state="synced",
            dependencies=WorkflowDependencies(workflow_name="wf1"),
            resolution=ResolutionResult(workflow_name="wf1"),  # No resolution issues
            uninstalled_nodes=["comfyui-custom-node", "comfyui-another-node"]  # But has uninstalled!
        )

        # has_issues should be True due to uninstalled_nodes
        assert analysis.has_issues is True, "has_issues should be True when uninstalled_nodes exist"

        # issue_summary should NOT say "No issues" when has_issues is True
        assert analysis.issue_summary != "No issues", (
            "issue_summary should reflect uninstalled_nodes, not return 'No issues'"
        )
        assert "2 packages to install" in analysis.issue_summary

    def test_issue_summary_with_download_intents(self):
        """issue_summary should include download intents when they exist."""
        from comfygit_core.models.workflow import (
            ResolutionResult,
            ResolvedModel,
            WorkflowDependencies,
            WorkflowNodeWidgetRef,
        )

        model_ref = WorkflowNodeWidgetRef(
            node_id="4",
            node_type="CheckpointLoaderSimple",
            widget_index=0,
            widget_value="model.safetensors"
        )

        download_intent = ResolvedModel(
            workflow="wf1",
            reference=model_ref,
            match_type="download_intent",
            model_source="https://example.com/model.safetensors",
            target_path=Path("checkpoints/model.safetensors")
        )

        analysis = WorkflowAnalysisStatus(
            name="wf1",
            sync_state="synced",
            dependencies=WorkflowDependencies(workflow_name="wf1"),
            resolution=ResolutionResult(
                workflow_name="wf1",
                models_resolved=[download_intent]
            )
        )

        # has_issues should be True due to download_intent
        assert analysis.has_issues is True, "has_issues should be True with download intents"

        # issue_summary should NOT say "No issues"
        assert analysis.issue_summary != "No issues", (
            "issue_summary should reflect download intents, not return 'No issues'"
        )
        assert "1 pending download" in analysis.issue_summary

    def test_issue_summary_no_issues_when_actually_no_issues(self):
        """issue_summary should return 'No issues' only when has_issues is False."""
        from comfygit_core.models.workflow import (
            ResolutionResult,
            WorkflowDependencies,
        )

        analysis = WorkflowAnalysisStatus(
            name="wf1",
            sync_state="synced",
            dependencies=WorkflowDependencies(workflow_name="wf1"),
            resolution=ResolutionResult(workflow_name="wf1")
        )

        # Both should agree
        assert analysis.has_issues is False
        assert analysis.issue_summary == "No issues"

    def test_issue_summary_with_combined_issues(self):
        """issue_summary should include all issue types."""
        from comfygit_core.models.workflow import (
            ResolutionResult,
            ResolvedModel,
            WorkflowDependencies,
            WorkflowNode,
            WorkflowNodeWidgetRef,
        )

        model_ref = WorkflowNodeWidgetRef(
            node_id="4",
            node_type="CheckpointLoaderSimple",
            widget_index=0,
            widget_value="model.safetensors"
        )

        download_intent = ResolvedModel(
            workflow="wf1",
            reference=model_ref,
            match_type="download_intent",
            model_source="https://example.com/model.safetensors",
            target_path=Path("checkpoints/model.safetensors")
        )

        unresolved_node = WorkflowNode(id="5", type="UnknownCustomNode")

        analysis = WorkflowAnalysisStatus(
            name="wf1",
            sync_state="synced",
            dependencies=WorkflowDependencies(workflow_name="wf1"),
            resolution=ResolutionResult(
                workflow_name="wf1",
                models_resolved=[download_intent],
                nodes_unresolved=[unresolved_node]
            ),
            uninstalled_nodes=["comfyui-custom-node"]
        )

        assert analysis.has_issues is True
        summary = analysis.issue_summary

        # Should include all issue types
        assert "1 missing node" in summary, f"Expected missing node in: {summary}"
        assert "1 package" in summary, f"Expected packages to install in: {summary}"
        assert "1 pending download" in summary, f"Expected pending download in: {summary}"
