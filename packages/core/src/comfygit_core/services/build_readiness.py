"""Build/materialization readiness checks backed by ComfyGit manifest semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlparse

import tomllib

from ..models.build_readiness import (
    BuildAssetCatalog,
    BuildCustomNodeSummary,
    BuildDependencyProof,
    BuildModelSummary,
    BuildReadiness,
    BuildSourceValidationResult,
    BuildSourceValidator,
    BuildWorkflowContractIOSummary,
    BuildWorkflowContractSummary,
    BuildWorkflowSummary,
)
from ..models.manifest import (
    EnvironmentManifestSnapshot,
    ManifestModel,
    ManifestWorkflowEntry,
    ManifestWorkflowModel,
)
from ..models.shared import NodeInfo

BLOCKED_BUILD_STATUSES = {
    "blocked_missing_source",
    "blocked_unverified",
    "blocked_incompatible",
}


@dataclass(frozen=True)
class _ValidatedSourceProof:
    status: str
    source: str | None
    detail: str
    source_validation: Mapping[str, Any] | None


def build_readiness_from_pyproject_toml(
    pyproject_toml: str,
    *,
    asset_catalog: BuildAssetCatalog | None = None,
    source_validator: BuildSourceValidator | None = None,
) -> BuildReadiness:
    """Create a build-readiness proof from a ComfyGit environment pyproject."""
    try:
        manifest = tomllib.loads(pyproject_toml)
    except tomllib.TOMLDecodeError as exc:
        return BuildReadiness(
            status="failed",
            environment_name="",
            python_version=None,
            comfyui_version=None,
            blockers=(f"pyproject.toml is not valid TOML: {exc}",),
        )

    return build_readiness_from_manifest_dict(
        manifest,
        asset_catalog=asset_catalog,
        source_validator=source_validator,
    )


def build_readiness_from_manifest_dict(
    manifest: Mapping[str, Any],
    *,
    asset_catalog: BuildAssetCatalog | None = None,
    source_validator: BuildSourceValidator | None = None,
) -> BuildReadiness:
    """Create a build-readiness proof from parsed pyproject manifest data."""
    plain_manifest = dict(manifest)
    has_comfygit_manifest = bool(
        _dict_value(_dict_value(plain_manifest, "tool"), "comfygit")
    )
    snapshot = EnvironmentManifestSnapshot.from_toml_dict(plain_manifest)
    readiness = build_readiness_from_manifest_snapshot(
        snapshot,
        asset_catalog=asset_catalog,
        source_validator=source_validator,
    )
    if has_comfygit_manifest:
        return readiness

    blocker = "pyproject.toml does not contain a [tool.comfygit] manifest."
    return BuildReadiness(
        status="blocked",
        environment_name=readiness.environment_name,
        python_version=readiness.python_version,
        comfyui_version=readiness.comfyui_version,
        workflows=readiness.workflows,
        custom_nodes=readiness.custom_nodes,
        python_dependencies=readiness.python_dependencies,
        dependency_proof=readiness.dependency_proof,
        warnings=readiness.warnings,
        blockers=(*readiness.blockers, blocker),
    )


def build_readiness_from_manifest_snapshot(
    snapshot: EnvironmentManifestSnapshot,
    *,
    asset_catalog: BuildAssetCatalog | None = None,
    source_validator: BuildSourceValidator | None = None,
) -> BuildReadiness:
    """Create a build-readiness proof from a typed manifest snapshot."""
    python_dependencies = _dedupe(
        [
            *snapshot.project.dependencies,
            *(
                dependency
                for group in snapshot.dependency_groups.values()
                for dependency in group
            ),
        ]
    )
    workflows = tuple(
        _workflow_summary(workflow, model_catalog=snapshot.models)
        for workflow in snapshot.workflows.values()
    )
    custom_nodes = tuple(
        _custom_node_summary(identifier, node)
        for identifier, node in snapshot.nodes.items()
    )

    dependency_proof: list[BuildDependencyProof] = []
    warnings: list[str] = []
    blockers: list[str] = []

    for dependency in python_dependencies:
        dependency_proof.append(_classify_python_dependency(dependency))

    for node in custom_nodes:
        proof = _classify_custom_node(node, source_validator=source_validator)
        dependency_proof.append(proof)
        _collect_issue(proof, warnings=warnings, blockers=blockers)

    for workflow in workflows:
        for model in workflow.models:
            proof = _classify_model_dependency(
                model,
                model_catalog=snapshot.models,
                asset_catalog=asset_catalog,
                source_validator=source_validator,
            )
            dependency_proof.append(proof)
            _collect_issue(proof, warnings=warnings, blockers=blockers)

    if not workflows:
        warnings.append("No workflows are declared in [tool.comfygit.workflows].")
    if not _manifest_python_version(snapshot):
        warnings.append("No Python version is declared; build policy must choose a default.")
    if not snapshot.comfyui_version:
        warnings.append("No ComfyUI version is declared; build policy must choose a default.")

    return BuildReadiness(
        status="blocked" if blockers else "ready",
        environment_name=_environment_name(snapshot),
        python_version=_manifest_python_version(snapshot),
        comfyui_version=snapshot.comfyui_version,
        workflows=workflows,
        custom_nodes=custom_nodes,
        python_dependencies=tuple(python_dependencies),
        dependency_proof=tuple(dependency_proof),
        warnings=tuple(warnings),
        blockers=tuple(blockers),
    )


def _classify_python_dependency(dependency: str) -> BuildDependencyProof:
    source = _source_from_dependency(dependency)
    return BuildDependencyProof(
        kind="python_package",
        name=dependency,
        status="available_source" if source else "available_registry",
        required=True,
        source=source,
        detail="Python package will be installed during image construction.",
    )


def _classify_custom_node(
    node: BuildCustomNodeSummary,
    *,
    source_validator: BuildSourceValidator | None,
) -> BuildDependencyProof:
    sources = [
        source
        for source in (node.repository, node.download_url)
        if source is not None and _is_accepted_source(source)
    ]
    if sources:
        validated = _validate_sources(
            sources,
            kind="custom_node",
            required=node.required,
            source_validator=source_validator,
            metadata={
                "name": node.name,
                "registry_id": node.registry_id,
                "identifier": node.identifier,
            },
        )
        if validated is not None:
            return BuildDependencyProof(
                kind="custom_node",
                name=node.name,
                status=cast(Any, validated.status),
                required=node.required,
                source=validated.source,
                detail=validated.detail,
                source_validation=validated.source_validation,
            )
        return BuildDependencyProof(
            kind="custom_node",
            name=node.name,
            status="available_source",
            required=node.required,
            source=sources[0],
            detail="Custom node can be acquired from its declared source during image construction.",
        )

    if node.registry_id and node.source in {"registry", "comfy-registry"}:
        return BuildDependencyProof(
            kind="custom_node",
            name=node.name,
            status="available_registry",
            required=node.required,
            detail="Custom node can be resolved from the registry during image construction.",
        )

    if not node.required:
        return BuildDependencyProof(
            kind="custom_node",
            name=node.name,
            status="missing_optional",
            required=False,
            detail="Optional custom node has no repository, download URL, or supported registry source.",
        )

    return BuildDependencyProof(
        kind="custom_node",
        name=node.name,
        status="blocked_missing_source",
        required=True,
        detail="Custom node has no repository, download URL, or supported registry source.",
    )


def _classify_model_dependency(
    model: BuildModelSummary,
    *,
    model_catalog: Mapping[str, ManifestModel],
    asset_catalog: BuildAssetCatalog | None,
    source_validator: BuildSourceValidator | None,
) -> BuildDependencyProof:
    required = _is_required(model.criticality)
    sources = _accepted_sources(list(model.sources))
    catalog_entry = model_catalog.get(model.content_hash or "")

    if not sources and catalog_entry is not None:
        sources = _accepted_sources(list(catalog_entry.sources))

    cache_hit = None
    if model.content_hash and asset_catalog is not None:
        cache_hit = asset_catalog.lookup_by_hash(
            content_hash=model.content_hash,
            category=model.category,
        )
    if cache_hit:
        return BuildDependencyProof(
            kind="model",
            name=model.filename or model.content_hash or "unknown-model",
            status="available_cached",
            required=required,
            content_hash=model.content_hash,
            category=model.category,
            workflow=model.workflow,
            detail="Model content is already available in managed cache/catalog state.",
            cache_hit=cache_hit,
        )

    if sources:
        validated = _validate_sources(
            sources,
            kind="model",
            required=required,
            source_validator=source_validator,
            metadata={
                "filename": model.filename,
                "category": model.category,
                "workflow": model.workflow,
                "content_hash": model.content_hash,
            },
        )
        if validated is not None:
            return BuildDependencyProof(
                kind="model",
                name=model.filename or validated.source or model.content_hash or "unknown-model",
                status=cast(Any, validated.status),
                required=required,
                source=validated.source,
                content_hash=model.content_hash,
                category=model.category,
                workflow=model.workflow,
                detail=validated.detail,
                source_validation=validated.source_validation,
            )

        detail = "Model can be acquired from an accepted external source."
        if not model.content_hash:
            detail += " Add a trusted hash later to make this dependency reproducible."
        return BuildDependencyProof(
            kind="model",
            name=model.filename or sources[0],
            status="available_source",
            required=required,
            source=sources[0],
            content_hash=model.content_hash,
            category=model.category,
            workflow=model.workflow,
            detail=detail,
        )

    if not required:
        return BuildDependencyProof(
            kind="model",
            name=model.filename or model.content_hash or "unknown-model",
            status="missing_optional",
            required=False,
            content_hash=model.content_hash,
            category=model.category,
            workflow=model.workflow,
            detail="Optional model has no managed cache hit or accepted source.",
        )

    if model.content_hash:
        detail = "Required model has a content hash but is not present in managed cache and has no accepted source."
    else:
        detail = "Required model has no accepted source or content identity."
    return BuildDependencyProof(
        kind="model",
        name=model.filename or model.content_hash or "unknown-model",
        status="blocked_missing_source",
        required=True,
        content_hash=model.content_hash,
        category=model.category,
        workflow=model.workflow,
        detail=detail,
    )


def _validate_sources(
    sources: list[str],
    *,
    kind: str,
    required: bool,
    source_validator: BuildSourceValidator | None,
    metadata: Mapping[str, Any],
) -> _ValidatedSourceProof | None:
    if source_validator is None:
        return None

    attempts: list[BuildSourceValidationResult] = []
    for source in sources:
        result = source_validator.validate_source(
            source=source,
            kind=kind,
            metadata=metadata,
        )
        attempts.append(result)
        if result.status == "verified":
            return _ValidatedSourceProof(
                status="available_source",
                source=source,
                detail=f"{kind.replace('_', ' ').title()} source was verified.",
                source_validation={
                    "status": "verified",
                    "selected": result.to_dict(),
                    "attempts": [item.to_dict() for item in attempts],
                },
            )

    detail = f"{kind.replace('_', ' ').title()} source could not be verified."
    if attempts:
        detail = f"{detail} {attempts[-1].detail}"
    elif required:
        detail = f"{detail} No source validation attempts were produced."

    return _ValidatedSourceProof(
        status="blocked_unverified",
        source=sources[0] if sources else None,
        detail=detail,
        source_validation={
            "status": "unverified",
            "attempts": [item.to_dict() for item in attempts],
        },
    )


def _workflow_summary(
    workflow: ManifestWorkflowEntry,
    *,
    model_catalog: Mapping[str, ManifestModel],
) -> BuildWorkflowSummary:
    return BuildWorkflowSummary(
        name=workflow.name,
        path=workflow.path,
        nodes=workflow.node_packs,
        models=tuple(
            _model_summary(workflow.name, model, model_catalog=model_catalog)
            for model in workflow.models
        ),
        execution_contract=_contract_summary(workflow),
    )


def _model_summary(
    workflow_name: str,
    model: ManifestWorkflowModel,
    *,
    model_catalog: Mapping[str, ManifestModel],
) -> BuildModelSummary:
    catalog_entry = model_catalog.get(model.hash or "")
    filename = _first_nonempty(model.filename, getattr(catalog_entry, "filename", None))
    category = _first_nonempty(model.category, getattr(catalog_entry, "category", None))
    relative_path = _first_nonempty(
        model.relative_path,
        getattr(catalog_entry, "relative_path", None),
    )
    sources = tuple(_dedupe([*model.sources, *(catalog_entry.sources if catalog_entry else [])]))
    size_bytes = getattr(catalog_entry, "size", None) if catalog_entry is not None else None
    return BuildModelSummary(
        filename=filename,
        category=category,
        criticality=model.criticality,
        status=model.status,
        content_hash=model.hash,
        relative_path=relative_path,
        size_bytes=size_bytes,
        sources=sources,
        workflow=workflow_name,
    )


def _custom_node_summary(identifier: str, node: NodeInfo) -> BuildCustomNodeSummary:
    criticality = node.criticality or "required"
    return BuildCustomNodeSummary(
        identifier=identifier,
        name=node.name or node.registry_id or identifier or "unknown-node",
        source=(node.source or "unknown").lower(),
        required=_is_required(criticality),
        criticality=criticality,
        registry_id=node.registry_id,
        repository=node.repository,
        download_url=node.download_url,
        version=node.version,
        pinned_commit=node.pinned_commit,
    )


def _contract_summary(workflow: ManifestWorkflowEntry) -> BuildWorkflowContractSummary:
    contract = workflow.execution_contract
    if contract is None:
        return BuildWorkflowContractSummary()
    active_contract = contract.active_contract
    inputs = tuple(
        BuildWorkflowContractIOSummary(
            name=item.name,
            type=item.type,
            required=item.required,
        )
        for item in (active_contract.inputs if active_contract else [])
        if item.name
    )
    outputs = tuple(
        BuildWorkflowContractIOSummary(
            name=item.name,
            type=item.type,
        )
        for item in (active_contract.outputs if active_contract else [])
        if item.name
    )
    return BuildWorkflowContractSummary(
        version=contract.version,
        default_contract=contract.default_contract,
        input_count=len(inputs),
        output_count=len(outputs),
        inputs=inputs,
        outputs=outputs,
    )


def _collect_issue(
    proof: BuildDependencyProof,
    *,
    warnings: list[str],
    blockers: list[str],
) -> None:
    message = f"{proof.kind} {proof.name}: {proof.detail or proof.status}"
    if proof.status in BLOCKED_BUILD_STATUSES and proof.required:
        blockers.append(message)
    elif proof.status == "missing_optional" or proof.status in BLOCKED_BUILD_STATUSES:
        warnings.append(message)


def _source_from_dependency(dependency: str) -> str | None:
    if " @ " not in dependency:
        return None
    source = dependency.split(" @ ", 1)[1].strip()
    return source if _is_accepted_source(source) else None


def _accepted_sources(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if _is_accepted_source(value) and value not in result:
            result.append(value)
    return result


def _is_accepted_source(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https", "git+https", "hf", "s3"} and parsed.netloc:
        return True
    return value.startswith("git@") and ":" in value


def _manifest_python_version(snapshot: EnvironmentManifestSnapshot) -> str | None:
    return snapshot.python_version or _normalize_requires_python(snapshot.project.requires_python)


def _normalize_requires_python(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.removeprefix("==").removesuffix(".*") or text


def _environment_name(snapshot: EnvironmentManifestSnapshot) -> str:
    return (snapshot.project.name or "").removeprefix("comfygit-env-")


def _is_required(criticality: str | None) -> bool:
    return criticality != "optional"


def _dict_value(mapping: Mapping[str, Any] | Any, key: str) -> dict[str, Any]:
    value = mapping.get(key) if isinstance(mapping, Mapping) else None
    return dict(value) if isinstance(value, Mapping) else {}


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _first_nonempty(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None
