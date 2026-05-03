"""Reusable environment readiness checks for handoff-sensitive workflows."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..models.readiness import (
    EnvironmentReadiness,
    ModelSourceWarning,
    NodeProvenanceWarning,
    ReadinessBlockingIssue,
    ReadinessWarnings,
)


def _safe_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if isinstance(value, Iterable) and not isinstance(value, str):
        try:
            return list(value)
        except TypeError:
            return []
    return []


def _safe_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def node_criticality(node: Any) -> str:
    return "optional" if getattr(node, "criticality", None) == "optional" else "required"


def node_is_required(node: Any) -> bool:
    return node_criticality(node) == "required"


def node_has_portable_provenance(node: Any) -> bool:
    """Return whether a tracked custom node can be reconstructed elsewhere."""
    source = (getattr(node, "source", None) or "unknown").lower()
    version = getattr(node, "version", None)
    repository = getattr(node, "repository", None)
    registry_id = getattr(node, "registry_id", None)
    pinned_commit = getattr(node, "pinned_commit", None)

    if source == "registry":
        return bool(registry_id and version and version != "dev")
    if source == "git":
        return bool(repository and version and version != "dev")
    if source == "development":
        return bool(repository and pinned_commit)

    return False


def node_provenance_reason(node: Any) -> str:
    source = (getattr(node, "source", None) or "unknown").lower()
    if source == "registry":
        return "Registry node is missing a registry package id or pinned version."
    if source == "git":
        return "Git node is missing a repository URL or pinned commit/version."
    if source == "development":
        return "Development node is missing portable git repository and pinned commit metadata."
    return "Node source is unknown."


def collect_model_source_warnings(env: Any) -> list[ModelSourceWarning]:
    """Collect manifest models that do not have a known download source."""
    pyproject = getattr(env, "pyproject", None)
    models_manager = getattr(pyproject, "models", None)
    workflows_manager = getattr(pyproject, "workflows", None)
    if not models_manager or not workflows_manager:
        return []

    models = _safe_list(models_manager.get_all())
    models_without_sources = [
        model
        for model in models
        if not model_has_sources(env, model)
    ]
    if not models_without_sources:
        return []

    warnings_by_key: dict[str, ModelSourceWarning] = {}
    models_by_hash = {
        getattr(model, "hash", None): model
        for model in models_without_sources
        if getattr(model, "hash", None)
    }
    models_by_filename = {
        getattr(model, "filename", None): model
        for model in models_without_sources
        if getattr(model, "filename", None)
    }

    get_workflows = getattr(workflows_manager, "get_all_with_resolutions", None)
    workflow_map = get_workflows() if callable(get_workflows) else {}
    workflow_names = list(workflow_map.keys()) if isinstance(workflow_map, dict) else []
    get_workflow_models = getattr(workflows_manager, "get_workflow_models", None)

    for workflow_name in workflow_names:
        workflow_models = _safe_list(
            get_workflow_models(workflow_name) if callable(get_workflow_models) else []
        )
        for workflow_model in workflow_models:
            model_hash = getattr(workflow_model, "hash", None)
            filename = getattr(workflow_model, "filename", None)
            model_data = models_by_hash.get(model_hash) or models_by_filename.get(filename)
            if model_data is None:
                continue

            key = _safe_str(getattr(model_data, "hash", None)) or _safe_str(
                getattr(model_data, "filename", None)
            )
            if not key:
                continue

            warning = warnings_by_key.get(key)
            if warning is None:
                warning = ModelSourceWarning(
                    filename=_safe_str(getattr(model_data, "filename", None))
                    or _safe_str(filename)
                    or "unknown",
                    hash=_safe_str(getattr(model_data, "hash", None)),
                    criticality=_safe_str(getattr(model_data, "criticality", None))
                    or "required",
                    workflows=[],
                    source_candidates=model_source_candidates(env, model_data),
                )
                warnings_by_key[key] = warning
            warning.workflows.append(workflow_name)

    # Include unreferenced manifest models too; they still affect environment
    # handoff when the environment is shared as a whole.
    for model_data in models_without_sources:
        key = _safe_str(getattr(model_data, "hash", None)) or _safe_str(
            getattr(model_data, "filename", None)
        )
        if not key or key in warnings_by_key:
            continue
        warnings_by_key[key] = ModelSourceWarning(
            filename=_safe_str(getattr(model_data, "filename", None)) or "unknown",
            hash=_safe_str(getattr(model_data, "hash", None)),
            criticality=_safe_str(getattr(model_data, "criticality", None)) or "required",
            workflows=[],
            source_candidates=model_source_candidates(env, model_data),
        )

    return list(warnings_by_key.values())


def model_has_sources(env: Any, model: Any) -> bool:
    """Return whether the environment manifest itself records a model source."""
    return bool(getattr(model, "sources", None))


def model_source_candidates(env: Any, model: Any) -> list[dict[str, Any]]:
    """Return workspace-index source hints without satisfying manifest readiness."""
    model_hash = _safe_str(getattr(model, "hash", None))
    if not model_hash:
        return []

    model_repository = getattr(getattr(env, "workspace", None), "model_repository", None)
    get_sources = getattr(model_repository, "get_sources", None)
    if not callable(get_sources):
        return []

    try:
        sources = _safe_list(get_sources(model_hash))
    except Exception:
        return []

    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = _safe_str(source.get("url"))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        candidates.append(
            {
                "type": _safe_str(source.get("type")) or "custom",
                "url": url,
            }
        )
    return candidates


def collect_node_provenance_warnings(env: Any) -> list[NodeProvenanceWarning]:
    """Collect required custom nodes that do not have portable provenance."""
    nodes_manager = getattr(getattr(env, "pyproject", None), "nodes", None)
    if not nodes_manager:
        return []

    nodes = _safe_list(nodes_manager.get_existing())
    warnings = []
    for node in nodes:
        if not node_is_required(node):
            continue
        if node_has_portable_provenance(node):
            continue
        warnings.append(
            NodeProvenanceWarning(
                name=_safe_str(getattr(node, "name", None))
                or _safe_str(getattr(node, "registry_id", None))
                or "unknown",
                source=_safe_str(getattr(node, "source", None)) or "unknown",
                criticality=node_criticality(node),
                registry_id=_safe_str(getattr(node, "registry_id", None)),
                repository=_safe_str(getattr(node, "repository", None)),
                version=_safe_str(getattr(node, "version", None)),
                pinned_commit=_safe_str(getattr(node, "pinned_commit", None)),
                reason=node_provenance_reason(node),
            )
        )
    return warnings


def build_environment_readiness(
    env: Any, *, include_blocking: bool = True
) -> EnvironmentReadiness:
    """Validate local environment handoff readiness.

    Export and git push are both exits from a managed environment into a
    portable state. This validator keeps reproducibility warnings aligned while
    allowing callers to choose whether source-state blockers are also included.
    """
    blocking_issues: list[ReadinessBlockingIssue] = []

    if include_blocking:
        status = env.workflow_manager.get_workflow_status()
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

        if env.git_manager.has_uncommitted_changes():
            blocking_issues.append(
                ReadinessBlockingIssue(
                    type="uncommitted_git_changes",
                    message="Cannot export with uncommitted git changes",
                    details=[],
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

    return EnvironmentReadiness(
        blocking_issues=blocking_issues,
        warnings=ReadinessWarnings(
            models_without_sources=collect_model_source_warnings(env),
            nodes_without_provenance=collect_node_provenance_warnings(env),
        ),
    )
