"""Public model types for ComfyGit Core."""

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, str] = {
    "ComfyDockError": "exceptions",
    "CDWorkspaceError": "exceptions",
    "CDEnvironmentError": "exceptions",
    "CDDependencyPreviewStaleError": "exceptions",
    "CDNodeNotFoundError": "exceptions",
    "CDRegistryError": "exceptions",
    "NodeInfo": "shared",
    "NodeDevLinkResult": "shared",
    "ModelInfo": "shared",
    "ModelWithLocation": "shared",
    "NodePackage": "shared",
    "UpdateResult": "shared",
    "NodeRemovalResult": "shared",
    "ManagerStatus": "shared",
    "ManagerUpdateResult": "shared",
    "ModelSourceStatus": "shared",
    "ModelSourceResult": "shared",
    "OverlayConfig": "overlay",
    "OverlayInfo": "overlay",
    "SyncResult": "sync",
    "APICredentials": "workspace_config",
    "ModelDirectory": "workspace_config",
    "WorkspaceConfig": "workspace_config",
    "EnvironmentManifestSnapshot": "manifest",
    "ManifestProjectSnapshot": "manifest",
    "ManifestUVSnapshot": "manifest",
    "ManifestWorkflowEntry": "manifest",
    "MaterializeOptions": "materialization",
    "MaterializeResult": "materialization",
    "DependencyResolutionPreview": "dependency_resolution",
    "DependencyResolutionAcceptance": "dependency_resolution",
    "DependencyResolutionApplyResult": "dependency_resolution",
    "PackageVersionChange": "dependency_resolution",
    "WorkflowContractInput": "workflow_contract",
    "WorkflowContractOutput": "workflow_contract",
    "NamedWorkflowContract": "workflow_contract",
    "WorkflowExecutionContract": "workflow_contract",
    "ComfyUIPrompt": "workflow_execution",
    "ContractOutputArtifact": "workflow_execution",
    "ContractOutputResult": "workflow_execution",
    "PromptAppliedInput": "workflow_execution",
    "PromptBuildIssue": "workflow_execution",
    "ContractPromptBuildResult": "workflow_execution",
    "EnvironmentReadiness": "readiness",
    "ModelSourceWarning": "readiness",
    "NodeProvenanceWarning": "readiness",
    "ReadinessBlockingIssue": "readiness",
    "ReadinessWarnings": "readiness",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
