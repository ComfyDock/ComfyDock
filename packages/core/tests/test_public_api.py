"""Smoke tests for the supported comfygit_core import surface."""

from importlib import import_module


def test_core_entrypoints_are_importable():
    """Root and core package entrypoints should expose Environment/Workspace."""
    from comfygit_core import Environment, Workspace
    from comfygit_core.core import Environment as CoreEnvironment
    from comfygit_core.core import Workspace as CoreWorkspace

    assert Environment is CoreEnvironment
    assert Workspace is CoreWorkspace


def test_workspace_public_constructors_are_available():
    """Consumers should not need WorkspaceFactory for normal workspace access."""
    from comfygit_core import Workspace

    assert callable(Workspace.open)
    assert callable(Workspace.create)
    assert callable(Workspace.from_path)
    assert callable(Workspace.open_or_create)
    assert callable(Workspace.default_root)
    assert callable(Workspace.exists)
    assert callable(Workspace.list_remote_refs)
    assert callable(Workspace.get_civitai_token)
    assert callable(Workspace.get_workspace_id)
    assert callable(Workspace.set_civitai_token)
    assert callable(Workspace.get_huggingface_token)
    assert callable(Workspace.set_huggingface_token)
    assert callable(Workspace.get_github_token)
    assert callable(Workspace.set_github_token)
    assert callable(Workspace.get_external_uv_cache)
    assert callable(Workspace.set_external_uv_cache)
    assert callable(Workspace.suggest_model_download_path)
    assert callable(Workspace.download_model_request)
    assert callable(Workspace.get_resource_inventory)
    assert callable(Workspace.get_model_inventory)
    assert callable(Workspace.get_environment_inventory)
    assert callable(Workspace.plan_model_deletion)
    assert callable(Workspace.apply_model_deletion_plan)


def test_environment_public_git_facade_methods_are_available():
    """Consumers should not need GitManager for remote operations."""
    from comfygit_core import Environment

    assert callable(Environment.get_manifest_snapshot)
    assert callable(Environment.list_manifest_nodes)
    assert callable(Environment.get_manifest_node)
    assert callable(Environment.list_manifest_workflows)
    assert callable(Environment.get_manifest_workflow)
    assert callable(Environment.list_manifest_models)
    assert callable(Environment.get_manifest_model)
    assert callable(Environment.get_workflow_manifest_models)
    assert callable(Environment.get_workflow_custom_node_map)
    assert callable(Environment.get_readiness)
    assert callable(Environment.get_lifecycle_status)
    assert callable(Environment.list_remotes)
    assert callable(Environment.add_remote)
    assert callable(Environment.remove_remote)
    assert callable(Environment.set_remote_url)
    assert callable(Environment.get_tracking_remote)
    assert callable(Environment.fetch_remote)
    assert callable(Environment.get_remote_sync_status)
    assert callable(Environment.pull_remote)
    assert callable(Environment.push_remote)
    assert callable(Environment.check_remote_auth)


def test_factory_and_path_internals_are_not_root_public_api():
    """Workspace setup internals should stay behind the Workspace facade."""
    import comfygit_core
    import comfygit_core.core
    import comfygit_core.models

    assert "WorkspaceFactory" not in comfygit_core.__all__
    assert "WorkspacePaths" not in comfygit_core.__all__
    assert "WorkspaceFactory" not in comfygit_core.core.__all__
    assert "WorkspacePaths" not in comfygit_core.core.__all__
    assert "WorkspacePaths" not in comfygit_core.models.__all__


def test_public_facade_modules_export_declared_symbols():
    """Only documented facade modules define the stable public API."""
    public_modules = [
        "comfygit_core",
        "comfygit_core.confirmation",
        "comfygit_core.core",
        "comfygit_core.git",
        "comfygit_core.imports",
        "comfygit_core.models",
        "comfygit_core.readiness",
        "comfygit_core.runtime",
        "comfygit_core.workflow",
        "comfygit_core.assets",
        "comfygit_core.build_readiness",
    ]

    for module_name in public_modules:
        module = import_module(module_name)
        exports = getattr(module, "__all__", None)
        assert isinstance(exports, list | tuple), f"{module_name} missing __all__"
        assert exports, f"{module_name} has empty __all__"
        for export_name in exports:
            assert hasattr(module, export_name), (
                f"{module_name} export '{export_name}' is declared but not importable"
            )


def test_runtime_public_helpers_are_available():
    """Adapters should not need low-level uv integration imports for runtime setup."""
    from comfygit_core.runtime import create_uv_venv

    assert callable(create_uv_venv)


def test_common_adapter_types_are_public():
    """Types used by CLI/Manager adapters should be available from public facades."""
    from comfygit_core.build_readiness import build_readiness_from_manifest_snapshot
    from comfygit_core.confirmation import AutoConfirmStrategy, ConfirmationStrategy
    from comfygit_core.imports import import_unmanaged_comfyui_environment, scan_unmanaged_comfyui
    from comfygit_core.models import (
        BatchDownloadCallbacks,
        BuildAssetCatalog,
        BuildDependencyProof,
        BuildReadiness,
        BuildSourceValidator,
        CDDependencyConflictError,
        CDExportError,
        CDNodeConflictError,
        CDRegistryDataError,
        CDWorkspaceNotFoundError,
        DependencyCriticality,
        DependencyGroupRemovalResult,
        EnvironmentLifecycleStatus,
        EnvironmentManifestSnapshot,
        EnvironmentReadiness,
        EnvironmentStatus,
        GitBranch,
        GitCommitSummary,
        GitRemote,
        GitRemoteBranch,
        GitRemoteRefs,
        GitRemoteTag,
        GitSyncStatus,
        ImportCallbacks,
        LifecycleAction,
        LifecycleIssue,
        LifecycleLayerSummary,
        LifecycleOperationState,
        LifecycleRuntimeState,
        ManifestModel,
        ManifestWorkflowModel,
        ModelIndexSource,
        ModelIndexStats,
        ModelLocation,
        ModelResolutionContext,
        ModelSourceCandidate,
        NodeInstallCallbacks,
        NodeResolutionContext,
        OverlayActivationResult,
        OverlayTemplateResult,
        ReadinessBlockingIssueType,
        ReadinessContext,
        ReadinessEnvironment,
        ReadinessGitStatusReader,
        ReadinessModelSourceReader,
        ReadinessWorkflowStatus,
        ReadinessWorkflowStatusReader,
        ReadinessWorkflowSyncStatus,
        RefDiff,
        ResolutionResult,
        TorchBackendDetection,
        TorchBackendSelection,
        TorchBackendStatus,
        UnmanagedComfyUIImportPreview,
        UnmanagedComfyUIImportResult,
        UnmanagedCustomNodeScan,
        UnmanagedDevelopmentNodeLink,
        UnmanagedModelReferenceScan,
        UnmanagedWorkflowScan,
        UVCommandContext,
        UVCommandError,
        WorkflowAnalysisStatus,
        WorkflowDependencies,
        WorkflowExecutionContract,
        WorkflowSyncStatus,
    )
    from comfygit_core.readiness import collect_node_provenance_warnings

    assert AutoConfirmStrategy.__name__ == "AutoConfirmStrategy"
    assert BatchDownloadCallbacks.__name__ == "BatchDownloadCallbacks"
    assert BuildAssetCatalog.__name__ == "BuildAssetCatalog"
    assert BuildDependencyProof.__name__ == "BuildDependencyProof"
    assert BuildReadiness.__name__ == "BuildReadiness"
    assert BuildSourceValidator.__name__ == "BuildSourceValidator"
    assert CDDependencyConflictError.__name__ == "CDDependencyConflictError"
    assert CDExportError.__name__ == "CDExportError"
    assert CDNodeConflictError.__name__ == "CDNodeConflictError"
    assert CDRegistryDataError.__name__ == "CDRegistryDataError"
    assert CDWorkspaceNotFoundError.__name__ == "CDWorkspaceNotFoundError"
    assert DependencyCriticality is not None
    assert DependencyGroupRemovalResult.__name__ == "DependencyGroupRemovalResult"
    assert EnvironmentLifecycleStatus.__name__ == "EnvironmentLifecycleStatus"
    assert EnvironmentManifestSnapshot.__name__ == "EnvironmentManifestSnapshot"
    assert EnvironmentReadiness.__name__ == "EnvironmentReadiness"
    assert EnvironmentStatus.__name__ == "EnvironmentStatus"
    assert GitBranch.__name__ == "GitBranch"
    assert GitCommitSummary.__name__ == "GitCommitSummary"
    assert GitRemote.__name__ == "GitRemote"
    assert GitRemoteBranch.__name__ == "GitRemoteBranch"
    assert GitRemoteRefs.__name__ == "GitRemoteRefs"
    assert GitRemoteTag.__name__ == "GitRemoteTag"
    assert GitSyncStatus.__name__ == "GitSyncStatus"
    assert ManifestModel.__name__ == "ManifestModel"
    assert ManifestWorkflowModel.__name__ == "ManifestWorkflowModel"
    assert LifecycleAction.__name__ == "LifecycleAction"
    assert LifecycleIssue.__name__ == "LifecycleIssue"
    assert LifecycleLayerSummary.__name__ == "LifecycleLayerSummary"
    assert LifecycleOperationState.__name__ == "LifecycleOperationState"
    assert LifecycleRuntimeState.__name__ == "LifecycleRuntimeState"
    assert ModelIndexSource.__name__ == "ModelIndexSource"
    assert ModelIndexStats.__name__ == "ModelIndexStats"
    assert ModelLocation.__name__ == "ModelLocation"
    assert ImportCallbacks.__name__ == "ImportCallbacks"
    assert ModelResolutionContext.__name__ == "ModelResolutionContext"
    assert ModelSourceCandidate.__name__ == "ModelSourceCandidate"
    assert NodeInstallCallbacks.__name__ == "NodeInstallCallbacks"
    assert NodeResolutionContext.__name__ == "NodeResolutionContext"
    assert OverlayActivationResult.__name__ == "OverlayActivationResult"
    assert OverlayTemplateResult.__name__ == "OverlayTemplateResult"
    assert ConfirmationStrategy.__name__ == "ConfirmationStrategy"
    assert RefDiff.__name__ == "RefDiff"
    assert ReadinessBlockingIssueType is not None
    assert ReadinessContext.__name__ == "ReadinessContext"
    assert ReadinessEnvironment.__name__ == "ReadinessEnvironment"
    assert ReadinessGitStatusReader.__name__ == "ReadinessGitStatusReader"
    assert ReadinessModelSourceReader.__name__ == "ReadinessModelSourceReader"
    assert ReadinessWorkflowStatus.__name__ == "ReadinessWorkflowStatus"
    assert ReadinessWorkflowSyncStatus.__name__ == "ReadinessWorkflowSyncStatus"
    assert ReadinessWorkflowStatusReader.__name__ == "ReadinessWorkflowStatusReader"
    assert ResolutionResult.__name__ == "ResolutionResult"
    assert TorchBackendDetection.__name__ == "TorchBackendDetection"
    assert TorchBackendSelection.__name__ == "TorchBackendSelection"
    assert TorchBackendStatus.__name__ == "TorchBackendStatus"
    assert UVCommandContext.__name__ == "UVCommandContext"
    assert UVCommandError.__name__ == "UVCommandError"
    assert UnmanagedComfyUIImportPreview.__name__ == "UnmanagedComfyUIImportPreview"
    assert UnmanagedComfyUIImportResult.__name__ == "UnmanagedComfyUIImportResult"
    assert UnmanagedCustomNodeScan.__name__ == "UnmanagedCustomNodeScan"
    assert UnmanagedDevelopmentNodeLink.__name__ == "UnmanagedDevelopmentNodeLink"
    assert UnmanagedModelReferenceScan.__name__ == "UnmanagedModelReferenceScan"
    assert UnmanagedWorkflowScan.__name__ == "UnmanagedWorkflowScan"
    assert WorkflowAnalysisStatus.__name__ == "WorkflowAnalysisStatus"
    assert WorkflowDependencies.__name__ == "WorkflowDependencies"
    assert WorkflowExecutionContract.__name__ == "WorkflowExecutionContract"
    assert WorkflowSyncStatus.__name__ == "WorkflowSyncStatus"
    assert callable(build_readiness_from_manifest_snapshot)
    assert callable(collect_node_provenance_warnings)
    assert callable(import_unmanaged_comfyui_environment)
    assert callable(scan_unmanaged_comfyui)


def test_git_remote_refs_model_round_trips_to_public_json_shape():
    """Git facade results should stay typed until JSON/API edges serialize them."""
    from comfygit_core.models import GitRemoteRefs

    refs = GitRemoteRefs.from_dict(
        {
            "default_branch": "main",
            "head_commit": "abc123",
            "branches": [
                {"name": "main", "commit": "abc123", "is_default": True},
                {"name": "dev", "commit": "def456", "is_default": False},
            ],
            "tags": [
                {"name": "v1.0.0", "commit": "abc123"},
            ],
        }
    )

    assert refs.default_branch == "main"
    assert refs.branches[0].is_default is True
    assert refs.to_dict() == {
        "default_branch": "main",
        "head_commit": "abc123",
        "branches": [
            {"name": "main", "commit": "abc123", "is_default": True},
            {"name": "dev", "commit": "def456", "is_default": False},
        ],
        "tags": [
            {"name": "v1.0.0", "commit": "abc123"},
        ],
    }


def test_model_index_public_models_round_trip_to_public_json_shape():
    """Workspace model-index facade results should be typed until API edges serialize them."""
    from comfygit_core.models import ModelIndexSource, ModelIndexStats, ModelLocation

    location = ModelLocation.from_dict({
        "id": 12,
        "model_hash": "abc123",
        "base_directory": "/models",
        "relative_path": "checkpoints/test.safetensors",
        "filename": "test.safetensors",
        "mtime": 123.0,
        "last_seen": 456,
    })
    source = ModelIndexSource.from_dict({
        "model_hash": "abc123",
        "type": "huggingface",
        "url": "https://huggingface.co/example/model/resolve/main/test.safetensors",
        "metadata": {"repo": "example/model"},
        "added_time": 789,
    })
    stats = ModelIndexStats.from_dict({
        "total_models": 1,
        "total_locations": 2,
        "total_sources": 3,
    })

    assert location.full_path == "/models/checkpoints/test.safetensors"
    assert location.to_dict() == {
        "id": 12,
        "model_hash": "abc123",
        "base_directory": "/models",
        "relative_path": "checkpoints/test.safetensors",
        "filename": "test.safetensors",
        "mtime": 123.0,
        "last_seen": 456,
    }
    assert source.to_dict() == {
        "model_hash": "abc123",
        "type": "huggingface",
        "url": "https://huggingface.co/example/model/resolve/main/test.safetensors",
        "metadata": {"repo": "example/model"},
        "added_time": 789,
    }
    assert stats.to_dict() == {
        "total_models": 1,
        "total_locations": 2,
        "total_sources": 3,
    }


def test_resource_inventory_contract_types_are_public():
    from comfygit_core.models import (
        EnvironmentDependency,
        EnvironmentInventory,
        ModelDeletionApplyResult,
        ModelDeletionPlan,
        ModelInventoryEntry,
        ModelSource,
        StorageSummary,
        WorkspaceInventory,
    )

    assert all((
        EnvironmentDependency,
        EnvironmentInventory,
        ModelDeletionApplyResult,
        ModelDeletionPlan,
        ModelInventoryEntry,
        ModelSource,
        StorageSummary,
        WorkspaceInventory,
    ))
