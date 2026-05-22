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
        "comfygit_core.core",
        "comfygit_core.models",
        "comfygit_core.readiness",
        "comfygit_core.runtime",
        "comfygit_core.workflow",
        "comfygit_core.assets",
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


def test_common_adapter_model_types_are_public():
    """Types used by CLI/Manager adapters should be available from models."""
    from comfygit_core.models import (
        BatchDownloadCallbacks,
        CDDependencyConflictError,
        CDExportError,
        CDNodeConflictError,
        CDRegistryDataError,
        CDWorkspaceNotFoundError,
        EnvironmentManifestSnapshot,
        EnvironmentReadiness,
        EnvironmentStatus,
        ImportCallbacks,
        ManifestModel,
        ManifestWorkflowModel,
        ModelResolutionContext,
        NodeInstallCallbacks,
        NodeResolutionContext,
        RefDiff,
        ResolutionResult,
        UVCommandError,
        WorkflowAnalysisStatus,
        WorkflowExecutionContract,
        WorkflowSyncStatus,
    )

    assert BatchDownloadCallbacks.__name__ == "BatchDownloadCallbacks"
    assert CDDependencyConflictError.__name__ == "CDDependencyConflictError"
    assert CDExportError.__name__ == "CDExportError"
    assert CDNodeConflictError.__name__ == "CDNodeConflictError"
    assert CDRegistryDataError.__name__ == "CDRegistryDataError"
    assert CDWorkspaceNotFoundError.__name__ == "CDWorkspaceNotFoundError"
    assert EnvironmentManifestSnapshot.__name__ == "EnvironmentManifestSnapshot"
    assert EnvironmentReadiness.__name__ == "EnvironmentReadiness"
    assert EnvironmentStatus.__name__ == "EnvironmentStatus"
    assert ManifestModel.__name__ == "ManifestModel"
    assert ManifestWorkflowModel.__name__ == "ManifestWorkflowModel"
    assert ImportCallbacks.__name__ == "ImportCallbacks"
    assert ModelResolutionContext.__name__ == "ModelResolutionContext"
    assert NodeInstallCallbacks.__name__ == "NodeInstallCallbacks"
    assert NodeResolutionContext.__name__ == "NodeResolutionContext"
    assert RefDiff.__name__ == "RefDiff"
    assert ResolutionResult.__name__ == "ResolutionResult"
    assert UVCommandError.__name__ == "UVCommandError"
    assert WorkflowAnalysisStatus.__name__ == "WorkflowAnalysisStatus"
    assert WorkflowExecutionContract.__name__ == "WorkflowExecutionContract"
    assert WorkflowSyncStatus.__name__ == "WorkflowSyncStatus"
