"""Reusable environment readiness checks for handoff-sensitive workflows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from ..models.manifest import (
    EnvironmentManifestSnapshot,
    ManifestModel,
    ManifestWorkflowModel,
)
from ..models.readiness import (
    DependencyCriticality,
    EnvironmentReadiness,
    ModelSourceCandidate,
    ModelSourceWarning,
    NodeProvenanceWarning,
    ReadinessBlockingIssue,
    ReadinessContext,
    ReadinessEnvironment,
    ReadinessModelSourceReader,
    ReadinessWarnings,
)
from ..models.shared import NodeInfo

ReadinessInput = ReadinessContext | ReadinessEnvironment


def _resolve_manifest_artifact_path(manifest_dir: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(
            f"Contract API prompt path must be relative to the manifest: {relative_path}"
        )
    return manifest_dir / path


def _safe_list(value: object) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    if isinstance(value, Iterable) and not isinstance(value, str):
        try:
            return list(value)
        except TypeError:
            return []
    return []


def _safe_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _dependency_criticality(value: object) -> DependencyCriticality:
    return "optional" if value == "optional" else "required"


def _model_key(model: ManifestModel | ManifestWorkflowModel) -> str | None:
    return _safe_str(model.hash) or _safe_str(model.filename)


def node_criticality(node: NodeInfo) -> DependencyCriticality:
    return "optional" if node.criticality == "optional" else "required"


def node_is_required(node: NodeInfo) -> bool:
    return node_criticality(node) == "required"


def node_has_portable_provenance(node: NodeInfo) -> bool:
    """Return whether a tracked custom node can be reconstructed elsewhere."""
    source = (node.source or "unknown").lower()

    if source == "registry":
        return bool(node.registry_id and node.version and node.version != "dev")
    if source == "git":
        return bool(node.repository and node.version and node.version != "dev")
    if source == "development":
        return bool(node.repository and node.pinned_commit)

    return False


def node_provenance_reason(node: NodeInfo) -> str:
    source = (node.source or "unknown").lower()
    if source == "registry":
        return "Registry node is missing a registry package id or pinned version."
    if source == "git":
        return "Git node is missing a repository URL or pinned commit/version."
    if source == "development":
        return "Development node is missing portable git repository and pinned commit metadata."
    return "Node source is unknown."


class _WorkspaceModelSourceReader:
    """Adapter from Workspace model-source APIs to readiness source hints."""

    def __init__(self, workspace: object) -> None:
        self._workspace = workspace

    def get_model_source_candidates(
        self,
        model_hash: str,
    ) -> tuple[ModelSourceCandidate, ...]:
        sources = self._get_sources(model_hash)
        candidates: list[ModelSourceCandidate] = []
        seen_urls: set[str] = set()
        for source in sources:
            candidate = _source_to_candidate(source)
            if candidate is None or candidate.url in seen_urls:
                continue
            seen_urls.add(candidate.url)
            candidates.append(candidate)
        return tuple(candidates)

    def _get_sources(self, model_hash: str) -> list[Any]:
        get_model_sources = getattr(self._workspace, "get_model_sources", None)
        if callable(get_model_sources):
            try:
                return _safe_list(get_model_sources(model_hash))
            except Exception:
                return []
        return []


def _source_to_candidate(source: object) -> ModelSourceCandidate | None:
    if isinstance(source, ModelSourceCandidate):
        return source
    if isinstance(source, Mapping):
        source_mapping = cast(Mapping[str, object], source)
        url = _safe_str(source_mapping.get("url"))
        source_type = _safe_str(source_mapping.get("type")) or "custom"
    else:
        url = _safe_str(getattr(source, "url", None))
        source_type = _safe_str(getattr(source, "type", None)) or "custom"
    if not url:
        return None
    return ModelSourceCandidate(type=source_type, url=url)


def _source_reader_from_workspace(workspace: object | None) -> ReadinessModelSourceReader | None:
    if workspace is None:
        return None
    return _WorkspaceModelSourceReader(workspace)


def _manifest_snapshot_from_env(env: ReadinessEnvironment) -> EnvironmentManifestSnapshot:
    get_manifest_snapshot = getattr(env, "get_manifest_snapshot", None)
    if callable(get_manifest_snapshot):
        return cast(EnvironmentManifestSnapshot, get_manifest_snapshot())

    raise TypeError(
        "Readiness checks require an Environment with get_manifest_snapshot()."
    )


def build_readiness_context(
    env: ReadinessEnvironment,
    *,
    include_blocking: bool = True,
) -> ReadinessContext:
    """Adapt an Environment-shaped object into typed readiness inputs."""
    workflow_status = None
    has_uncommitted_git_changes = False

    if include_blocking:
        workflow_status = env.workflow_manager.get_workflow_status()
        has_uncommitted_git_changes = env.git_manager.has_uncommitted_changes()

    return ReadinessContext(
        manifest=_manifest_snapshot_from_env(env),
        manifest_dir=Path(env.cec_path),
        workflow_status=workflow_status,
        has_uncommitted_git_changes=has_uncommitted_git_changes,
        model_source_reader=_source_reader_from_workspace(getattr(env, "workspace", None)),
    )


def _as_readiness_context(
    source: ReadinessInput,
    *,
    include_blocking: bool = False,
) -> ReadinessContext:
    if isinstance(source, ReadinessContext):
        return source
    return build_readiness_context(source, include_blocking=include_blocking)


def collect_model_source_warnings(source: ReadinessInput) -> list[ModelSourceWarning]:
    """Collect manifest models that do not have a known download source."""
    context = _as_readiness_context(source)
    models_without_sources = [
        model
        for model in context.manifest.models.values()
        if not model_has_sources(model)
    ]
    if not models_without_sources:
        return []

    warnings_by_key: dict[str, ModelSourceWarning] = {}
    models_by_hash = {
        model.hash: model
        for model in models_without_sources
        if model.hash
    }
    models_by_filename = {
        model.filename: model
        for model in models_without_sources
        if model.filename
    }

    for workflow_name, workflow in context.manifest.workflows.items():
        for workflow_model in workflow.models:
            model_data = (
                models_by_hash.get(workflow_model.hash)
                if workflow_model.hash
                else None
            ) or models_by_filename.get(workflow_model.filename)
            if model_data is None:
                continue

            key = _model_key(model_data)
            if not key:
                continue

            criticality = _dependency_criticality(workflow_model.criticality)
            warning = warnings_by_key.get(key)
            if warning is None:
                warning = ModelSourceWarning(
                    filename=model_data.filename or workflow_model.filename or "unknown",
                    hash=model_data.hash,
                    criticality=criticality,
                    workflows=[],
                    source_candidates=model_source_candidates(context, model_data),
                )
                warnings_by_key[key] = warning
            elif warning.criticality == "optional" and criticality == "required":
                warning.criticality = "required"

            if workflow_name not in warning.workflows:
                warning.workflows.append(workflow_name)

    # Include unreferenced manifest models too; they still affect environment
    # handoff when the environment is shared as a whole.
    for model_data in models_without_sources:
        key = _model_key(model_data)
        if not key or key in warnings_by_key:
            continue
        warnings_by_key[key] = ModelSourceWarning(
            filename=model_data.filename or "unknown",
            hash=model_data.hash,
            criticality="required",
            workflows=[],
            source_candidates=model_source_candidates(context, model_data),
        )

    return list(warnings_by_key.values())


def model_has_sources(
    source_or_model: ReadinessInput | ManifestModel | ManifestWorkflowModel,
    model: ManifestModel | ManifestWorkflowModel | None = None,
) -> bool:
    """Return whether the manifest itself records a model source.

    The optional first argument keeps compatibility with older helper calls that
    passed ``(env, model)`` while allowing the typed form ``model_has_sources(model)``.
    """
    model_data = model if model is not None else source_or_model
    return bool(getattr(model_data, "sources", None))


def model_source_candidates(
    source: ReadinessInput,
    model: ManifestModel | ManifestWorkflowModel,
) -> list[ModelSourceCandidate]:
    """Return workspace-index source hints without satisfying manifest readiness."""
    context = _as_readiness_context(source)
    model_hash = _safe_str(model.hash)
    if not model_hash or context.model_source_reader is None:
        return []

    candidates: list[ModelSourceCandidate] = []
    seen_urls: set[str] = set()
    try:
        raw_candidates = context.model_source_reader.get_model_source_candidates(model_hash)
    except Exception:
        return []

    for raw_candidate in raw_candidates:
        candidate = _source_to_candidate(raw_candidate)
        if candidate is None or candidate.url in seen_urls:
            continue
        seen_urls.add(candidate.url)
        candidates.append(candidate)
    return candidates


def collect_node_provenance_warnings(source: ReadinessInput) -> list[NodeProvenanceWarning]:
    """Collect required custom nodes that do not have portable provenance."""
    context = _as_readiness_context(source)
    warnings = []
    for node in context.manifest.nodes.values():
        if not node_is_required(node):
            continue
        if node_has_portable_provenance(node):
            continue
        warnings.append(
            NodeProvenanceWarning(
                name=node.name or node.registry_id or "unknown",
                source=node.source or "unknown",
                criticality=node_criticality(node),
                registry_id=node.registry_id,
                repository=node.repository,
                version=node.version,
                pinned_commit=node.pinned_commit,
                reason=node_provenance_reason(node),
            )
        )
    return warnings


def collect_contract_artifact_blockers(source: ReadinessInput) -> list[ReadinessBlockingIssue]:
    """Collect workflow contracts whose referenced API prompt artifact is unavailable."""
    context = _as_readiness_context(source)
    missing: list[str] = []
    invalid: list[str] = []

    for workflow_name, workflow in context.manifest.workflows.items():
        contract = workflow.execution_contract
        api_prompt_file = _safe_str(getattr(contract, "api_prompt_file", None))
        if not api_prompt_file:
            continue

        try:
            api_prompt_path = _resolve_manifest_artifact_path(
                context.manifest_dir,
                api_prompt_file,
            )
        except ValueError:
            invalid.append(f"{workflow_name}: {api_prompt_file}")
            continue

        if not api_prompt_path.exists():
            missing.append(f"{workflow_name}: {api_prompt_file}")

    issues: list[ReadinessBlockingIssue] = []
    if missing:
        issues.append(
            ReadinessBlockingIssue(
                type="missing_contract_api_prompts",
                message="Cannot hand off environment - workflow contract API prompt files are missing",
                details=missing,
            )
        )
    if invalid:
        issues.append(
            ReadinessBlockingIssue(
                type="invalid_contract_api_prompt_paths",
                message="Cannot hand off environment - workflow contract API prompt paths are invalid",
                details=invalid,
            )
        )
    return issues


def build_readiness_from_context(
    context: ReadinessContext,
    *,
    include_blocking: bool = True,
) -> EnvironmentReadiness:
    """Validate handoff readiness from typed manifest and source-state inputs."""
    blocking_issues: list[ReadinessBlockingIssue] = []

    if include_blocking:
        status = context.workflow_status
        if status is not None:
            if status.sync_status.has_changes:
                uncommitted = (
                    list(status.sync_status.new)
                    + list(status.sync_status.modified)
                    + list(status.sync_status.deleted)
                )
                blocking_issues.append(
                    ReadinessBlockingIssue(
                        type="uncommitted_workflows",
                        message="Cannot export with uncommitted workflow changes",
                        details=uncommitted,
                    )
                )

            if not status.is_commit_safe:
                blocking_issues.append(
                    ReadinessBlockingIssue(
                        type="unresolved_issues",
                        message="Cannot export - workflows have unresolved issues",
                        details=[],
                    )
                )

        if context.has_uncommitted_git_changes:
            blocking_issues.append(
                ReadinessBlockingIssue(
                    type="uncommitted_git_changes",
                    message="Cannot export with uncommitted git changes",
                    details=[],
                )
            )

        blocking_issues.extend(collect_contract_artifact_blockers(context))

    return EnvironmentReadiness(
        blocking_issues=blocking_issues,
        warnings=ReadinessWarnings(
            models_without_sources=collect_model_source_warnings(context),
            nodes_without_provenance=collect_node_provenance_warnings(context),
        ),
    )


def build_environment_readiness(
    env: ReadinessEnvironment, *, include_blocking: bool = True
) -> EnvironmentReadiness:
    """Validate local environment handoff readiness.

    Export and git push are both exits from a managed environment into a
    portable state. This validator keeps reproducibility warnings aligned while
    allowing callers to choose whether source-state blockers are also included.
    """
    context = build_readiness_context(env, include_blocking=include_blocking)
    return build_readiness_from_context(context, include_blocking=include_blocking)
