"""Workflow analysis orchestration service."""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..analyzers.workflow_dependency_parser import WorkflowDependencyParser
from ..logging.logging_config import get_logger
from ..models.workflow import ResolutionResult, ResolvedModel, WorkflowNodeWidgetRef
from ..repositories.comfyui_builtin_versions_repository import (
    ComfyUIBuiltinVersionsRepository,
)
from ..repositories.node_mappings_repository import NodeMappingsRepository
from ..repositories.workflow_repository import WorkflowRepository
from ..resolvers.global_node_resolver import GlobalNodeResolver
from ..resolvers.model_resolver import ModelResolver
from ..services.model_source_lookup import ModelSourceLookupService
from ..services.registry_data_manager import RegistryDataManager
from ..services.workflow_input import (
    detect_workflow_input_format,
    normalize_workflow_input,
)
from ..services.workflow_resolution_service import (
    ResolutionContext,
    WorkflowResolutionService,
)

if TYPE_CHECKING:
    from ..core.workspace import Workspace
    from ..models.workflow import WorkflowDependencies
    from ..repositories.model_repository import ModelRepository

logger = get_logger(__name__)


@dataclass
class AnalysisReport:
    """Complete analysis of a raw workflow file."""

    workflow_name: str
    input_format: str  # 'ui_list', 'ui_dict', 'api', 'api_wrapped'
    total_nodes: int
    total_unique_node_types: int
    builtin_nodes: list[str]
    version_gated_nodes: list[str]
    resolution: ResolutionResult
    total_model_refs: int
    models_with_embedded_urls: int
    models_without_sources: int
    draft_spec: dict[str, Any]
    node_resolution_rate: float
    model_resolution_rate: float
    overall_confidence: str  # 'high', 'medium', 'low', 'incomplete'
    unresolved_items: list[dict[str, str]]
    min_comfyui_version: str | None = None  # Minimum ComfyUI version required by builtin nodes

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["resolution"] = asdict(self.resolution)
        return data


class _NoopGlobalNodeResolver:
    """Fallback resolver when registry mappings are unavailable."""

    def resolve_single_node_with_context(self, _node, _context=None):
        return None


class _PropertyOnlyModelResolver:
    """Fallback resolver that only uses embedded URL metadata."""

    @staticmethod
    def resolve_model(ref: WorkflowNodeWidgetRef, model_context) -> list[ResolvedModel] | None:
        if not ref.property_url:
            return None

        filename = ref.widget_value.replace("\\", "/").rsplit("/", 1)[-1]
        target_directory = ref.property_directory or "models"
        target_path = Path(target_directory) / filename

        return [
            ResolvedModel(
                workflow=model_context.workflow_name,
                reference=ref,
                resolved_model=None,
                model_source=ref.property_url,
                target_path=target_path,
                match_type="property_download_intent",
                match_confidence=1.0,
            )
        ]


class WorkflowAnalysisService:
    """Analyze raw workflow files without requiring an environment."""

    def __init__(
        self,
        node_mappings_repository: NodeMappingsRepository | None = None,
        model_repository: ModelRepository | None = None,
        builtin_versions_repository: ComfyUIBuiltinVersionsRepository | None = None,
        model_source_lookup: ModelSourceLookupService | None = None,
        registry_available: bool = True,
        registry_error: str | None = None,
        version_agnostic: bool = False,
    ) -> None:
        """All dependencies optional — degrades gracefully."""
        self.node_mappings_repository = node_mappings_repository
        self.model_repository = model_repository
        self.builtin_versions_repository = builtin_versions_repository
        self.model_source_lookup = model_source_lookup
        self.registry_available = registry_available
        self.registry_error = registry_error
        self.version_agnostic = version_agnostic

        if node_mappings_repository is not None:
            node_resolver = GlobalNodeResolver(node_mappings_repository)
        else:
            node_resolver = _NoopGlobalNodeResolver()

        if model_repository is not None:
            model_resolver = ModelResolver(model_repository=model_repository)
        else:
            model_resolver = _PropertyOnlyModelResolver()

        self.resolution_service = WorkflowResolutionService(  # type: ignore[arg-type]
            node_resolver, model_resolver
        )

    @classmethod
    def create_standalone(
        cls,
        cache_dir: Path | None = None,
        version_agnostic: bool = False,
    ) -> "WorkflowAnalysisService":
        """Factory for standalone use (no workspace).

        Args:
            cache_dir: Where to cache registry data.
            version_agnostic: If True, treat all known builtins as resolved
                regardless of ComfyUI version. Useful for web tools that
                aren't tied to a specific installation.
        """
        cache_root = cache_dir or Path(tempfile.mkdtemp(prefix="comfygit-analyze-"))

        node_repo = None
        builtin_repo = None
        registry_error = None
        registry_available = True

        try:
            data_manager = RegistryDataManager(cache_root)
            node_repo = NodeMappingsRepository(data_manager)
            builtin_repo = ComfyUIBuiltinVersionsRepository(data_manager)
        except Exception as exc:
            registry_available = False
            registry_error = str(exc)
            logger.warning("Standalone analysis: registry data unavailable: %s", exc)

        return cls(
            node_mappings_repository=node_repo,
            model_repository=None,
            builtin_versions_repository=builtin_repo,
            model_source_lookup=ModelSourceLookupService(cache_dir=cache_root),
            registry_available=registry_available,
            registry_error=registry_error,
            version_agnostic=version_agnostic,
        )

    @classmethod
    def create_from_workspace(cls, workspace: Workspace) -> "WorkflowAnalysisService":
        """Factory for workspace-aware use."""
        return cls(
            node_mappings_repository=workspace.node_mapping_repository,
            model_repository=workspace.model_repository,
            builtin_versions_repository=workspace.comfyui_builtin_versions_repository,
            model_source_lookup=ModelSourceLookupService(
                cache_dir=workspace.paths.cache,
                workspace_config=workspace.workspace_config_manager,
            ),
            registry_available=True,
            registry_error=None,
        )

    def analyze(self, workflow_path: Path, online: bool = False) -> AnalysisReport:
        """Full pipeline: parse → classify → resolve → report."""
        workflow_data = WorkflowRepository.load_raw_json(workflow_path)
        return self.analyze_json(workflow_data, name=workflow_path.stem, online=online)

    def analyze_json(self, data: dict, name: str = "unnamed", online: bool = False) -> AnalysisReport:
        """Analyze from parsed JSON dict."""
        input_format = detect_workflow_input_format(data)
        workflow = normalize_workflow_input(data)

        parser = WorkflowDependencyParser(
            workflow=workflow,
            workflow_name=name,
            cec_path=None,
            builtin_versions_repository=self.builtin_versions_repository,
            version_agnostic=self.version_agnostic,
        )
        analysis = parser.analyze_dependencies()

        resolution_context = ResolutionContext(workflow_name=analysis.workflow_name)
        resolution = self.resolution_service.resolve(analysis, resolution_context)
        if online and self.model_source_lookup is not None:
            self._enrich_with_online_sources(resolution)

        # Compute minimum ComfyUI version from all builtin nodes used
        min_comfyui_version = self._compute_min_comfyui_version(analysis)

        unique_node_types = workflow.node_types
        unique_builtin_types = sorted({node.type for node in analysis.builtin_nodes})
        unique_version_gated_types = sorted({node.type for node in analysis.version_gated_nodes})
        unique_model_refs = self._dedupe_model_refs(analysis)
        models_with_embedded_urls = sum(1 for ref in unique_model_refs if ref.property_url)
        models_without_sources = sum(
            1
            for ref in unique_model_refs
            if not ref.property_url and self._model_ref_key(ref) not in self._resolved_model_source_keys(resolution)
        )

        node_total_for_rate = len(unique_node_types)
        node_resolved_for_rate = len(unique_builtin_types) + len(resolution.nodes_resolved)
        model_total_for_rate = len(unique_model_refs)
        model_resolved_for_rate = len(resolution.models_resolved)

        unresolved_items = self._build_unresolved_items(resolution)
        if not self.registry_available:
            unresolved_items.append(
                {
                    "type": "registry",
                    "name": "node_mappings",
                    "suggestion": "Registry data unavailable; node package resolution skipped.",
                    "next_action": "Connect to network and run `cg registry update`.",
                }
            )

        node_resolution_rate = (
            round((node_resolved_for_rate / node_total_for_rate) * 100.0, 2)
            if node_total_for_rate
            else 100.0
        )
        model_resolution_rate = (
            round((model_resolved_for_rate / model_total_for_rate) * 100.0, 2)
            if model_total_for_rate
            else 100.0
        )

        confidence_levels = self._collect_confidence_levels(resolution)
        overall_confidence = self._derive_overall_confidence(confidence_levels, unresolved_items)

        return AnalysisReport(
            workflow_name=name,
            input_format=input_format,
            total_nodes=len(workflow.nodes),
            total_unique_node_types=len(unique_node_types),
            builtin_nodes=unique_builtin_types,
            version_gated_nodes=unique_version_gated_types,
            resolution=resolution,
            total_model_refs=len(unique_model_refs),
            models_with_embedded_urls=models_with_embedded_urls,
            models_without_sources=models_without_sources,
            draft_spec=self._build_draft_spec(name, resolution, min_comfyui_version),
            node_resolution_rate=node_resolution_rate,
            model_resolution_rate=model_resolution_rate,
            overall_confidence=overall_confidence,
            unresolved_items=unresolved_items,
            min_comfyui_version=min_comfyui_version,
        )

    def _enrich_with_online_sources(self, resolution: ResolutionResult) -> None:
        """Enrich model source URLs using provider-backed online lookup."""
        assert self.model_source_lookup is not None

        # Enrich already-resolved local models with source URLs (best via hash lookup).
        for model in resolution.models_resolved:
            if model.model_source:
                continue
            if model.resolved_model is None:
                continue

            filename = model.resolved_model.filename
            model_hash = model.resolved_model.hash
            candidates = self.model_source_lookup.lookup_sources(
                filename=filename,
                model_hash=model_hash,
                max_results=3,
            )
            if candidates:
                model.model_source = candidates[0].url

        # Try to resolve unresolved model refs into URL-based intents.
        remaining_unresolved: list[WorkflowNodeWidgetRef] = []
        for ref in resolution.models_unresolved:
            candidates = self.model_source_lookup.lookup_sources(
                filename=ref.widget_value,
                model_hash=None,
                max_results=3,
            )
            if not candidates:
                remaining_unresolved.append(ref)
                continue

            high_confidence = [c for c in candidates if c.confidence == "high"]
            if len(high_confidence) == 1:
                resolution.models_resolved.append(
                    ResolvedModel(
                        workflow=resolution.workflow_name,
                        reference=ref,
                        model_source=high_confidence[0].url,
                        match_type="download_intent",
                        match_confidence=1.0,
                    )
                )
                continue

            ambiguous_candidates: list[ResolvedModel] = []
            for candidate in candidates:
                if candidate.confidence == "medium":
                    match_type = "filename"
                    confidence = 0.7
                elif candidate.confidence == "low":
                    match_type = "fuzzy"
                    confidence = 0.5
                else:
                    match_type = "download_intent"
                    confidence = 1.0

                ambiguous_candidates.append(
                    ResolvedModel(
                        workflow=resolution.workflow_name,
                        reference=ref,
                        model_source=candidate.url,
                        match_type=match_type,
                        match_confidence=confidence,
                    )
                )

            if ambiguous_candidates:
                resolution.models_ambiguous.append(ambiguous_candidates)
            else:
                remaining_unresolved.append(ref)

        resolution.models_unresolved = remaining_unresolved

    @staticmethod
    def _model_ref_key(ref: WorkflowNodeWidgetRef) -> tuple[str, str]:
        return (ref.widget_value, ref.node_type)

    def _dedupe_model_refs(self, analysis: WorkflowDependencies) -> list[WorkflowNodeWidgetRef]:
        deduped: dict[tuple[str, str], WorkflowNodeWidgetRef] = {}
        for ref in analysis.found_models:
            key = self._model_ref_key(ref)
            if key not in deduped:
                deduped[key] = ref
        return list(deduped.values())

    def _resolved_model_source_keys(self, resolution: ResolutionResult) -> set[tuple[str, str]]:
        keys: set[tuple[str, str]] = set()
        for model in resolution.models_resolved:
            if model.model_source:
                keys.add(self._model_ref_key(model.reference))
        return keys

    def _compute_min_comfyui_version(self, analysis: WorkflowDependencies) -> str | None:
        """Compute the minimum ComfyUI version required by all builtin nodes.

        Looks up each builtin node type in the version-indexed database and
        returns the highest `introduced_in` version found — that's the minimum
        ComfyUI version needed to run this workflow.
        """
        if not self.builtin_versions_repository:
            return None
        db = self.builtin_versions_repository.database
        if not db:
            return None

        from ..models.comfyui_builtin_versions import normalize_version_tag, parse_semver_tag

        max_version: tuple[int, int, int] | None = None
        max_version_tag: str | None = None

        # Collect all builtin node types (including version-gated ones)
        all_builtin_types = {node.type for node in analysis.builtin_nodes}
        all_builtin_types |= {node.type for node in analysis.version_gated_nodes}

        for node_type in all_builtin_types:
            entry = db.builtins.get(node_type)
            if not entry:
                continue
            intro_tag = normalize_version_tag(entry.introduced_in)
            if not intro_tag:
                continue
            intro_tuple = parse_semver_tag(intro_tag)
            if intro_tuple and (max_version is None or intro_tuple > max_version):
                max_version = intro_tuple
                max_version_tag = intro_tag

        return max_version_tag

    def _build_draft_spec(self, workflow_name: str, resolution: ResolutionResult, min_comfyui_version: str | None = None) -> dict[str, Any]:
        nodes_section: dict[str, dict[str, Any]] = {}
        for resolved_node in resolution.nodes_resolved:
            package_id = resolved_node.package_id or resolved_node.node_type
            version = resolved_node.versions[0] if resolved_node.versions else None
            node_data = {
                "name": resolved_node.package_data.display_name if resolved_node.package_data else package_id,
                "registry_id": package_id,
                "version": version,
                "source": "registry",
            }
            nodes_section[package_id] = {k: v for k, v in node_data.items() if v is not None}

        models_section: list[dict[str, Any]] = []
        for model in resolution.models_resolved:
            entry = self._model_to_draft_entry(model)
            models_section.append(entry)

        for unresolved_ref in resolution.models_unresolved:
            models_section.append(
                {
                    "filename": unresolved_ref.widget_value,
                    "category": unresolved_ref.property_directory or "models",
                    "criticality": "required",
                    "status": "unresolved",
                    "nodes": [
                        {
                            "node_id": unresolved_ref.node_id,
                            "node_type": unresolved_ref.node_type,
                            "widget_index": unresolved_ref.widget_index,
                            "widget_value": unresolved_ref.widget_value,
                        }
                    ],
                    "sources": [],
                }
            )

        comfygit_section: dict[str, Any] = {
            "schema_version": 2,
            "nodes": nodes_section,
            "workflows": {
                workflow_name: {
                    "path": f"workflows/{workflow_name}.json",
                    "models": models_section,
                }
            },
        }

        if min_comfyui_version:
            comfygit_section["comfyui_version"] = min_comfyui_version

        return {"tool": {"comfygit": comfygit_section}}

    @staticmethod
    def _model_to_draft_entry(model: ResolvedModel) -> dict[str, Any]:
        ref = model.reference
        resolved = model.resolved_model
        filename = resolved.filename if resolved is not None else ref.widget_value
        category = "models"
        if resolved is not None:
            normalized_path = resolved.relative_path.replace("\\", "/")
            category = normalized_path.split("/", 1)[0] if "/" in normalized_path else "models"
        elif ref.property_directory:
            category = ref.property_directory

        entry = {
            "filename": filename,
            "category": category,
            "criticality": "optional" if model.is_optional else "required",
            "status": "resolved" if resolved is not None else "unresolved",
            "nodes": [
                {
                    "node_id": ref.node_id,
                    "node_type": ref.node_type,
                    "widget_index": ref.widget_index,
                    "widget_value": ref.widget_value,
                }
            ],
            "sources": [model.model_source] if model.model_source else [],
        }

        if resolved is not None:
            entry["hash"] = resolved.hash
            entry["relative_path"] = resolved.relative_path
        if model.target_path is not None:
            entry["relative_path"] = model.target_path.as_posix()

        return entry

    def _build_unresolved_items(self, resolution: ResolutionResult) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []

        for node in resolution.nodes_version_gated:
            items.append(
                {
                    "type": "node_version_gated",
                    "name": node.type,
                    "suggestion": resolution.node_guidance.get(
                        node.type,
                        "Requires a newer ComfyUI version.",
                    ),
                    "next_action": "Upgrade ComfyUI to a compatible version.",
                }
            )

        for node in resolution.nodes_uninstallable:
            items.append(
                {
                    "type": "node_uninstallable",
                    "name": node.node_type,
                    "suggestion": "Mapping exists but has no installable package version.",
                    "next_action": "Resolve manually with a custom mapping.",
                }
            )

        for node in resolution.nodes_unresolved:
            items.append(
                {
                    "type": "node_unresolved",
                    "name": node.type,
                    "suggestion": "No package mapping found in registry.",
                    "next_action": "Add a custom mapping or install manually.",
                }
            )

        for candidates in resolution.nodes_ambiguous:
            node_name = candidates[0].node_type if candidates else "unknown"
            items.append(
                {
                    "type": "node_ambiguous",
                    "name": node_name,
                    "suggestion": f"{len(candidates)} installable package matches found.",
                    "next_action": "Choose a package mapping explicitly.",
                }
            )

        for ref in resolution.models_unresolved:
            items.append(
                {
                    "type": "model_unresolved",
                    "name": ref.widget_value,
                    "suggestion": "Model not found in index and no embedded source URL.",
                    "next_action": "Provide source URL or place model in local index.",
                }
            )

        for candidates in resolution.models_ambiguous:
            model_name = candidates[0].reference.widget_value if candidates else "unknown"
            items.append(
                {
                    "type": "model_ambiguous",
                    "name": model_name,
                    "suggestion": f"{len(candidates)} model matches found.",
                    "next_action": "Select the correct model source.",
                }
            )

        return items

    def _collect_confidence_levels(self, resolution: ResolutionResult) -> list[str]:
        levels: list[str] = []

        for node in resolution.nodes_resolved:
            levels.append(self._node_match_confidence(node.match_type))

        for model in resolution.models_resolved:
            levels.append(self._model_match_confidence(model))

        return levels

    @staticmethod
    def _node_match_confidence(match_type: str) -> str:
        if match_type in {"exact", "properties", "properties_upgraded"}:
            return "high"
        if match_type == "type_only":
            return "medium"
        if match_type == "fuzzy":
            return "low"
        return "medium"

    @staticmethod
    def _model_match_confidence(model: ResolvedModel) -> str:
        if model.match_type in {"download_intent", "property_download_intent"} and model.model_source:
            return "high"
        if model.match_type == "exact" and model.model_source:
            return "high"
        if model.match_type == "fuzzy":
            return "low"
        if model.match_type == "filename" and model.model_source:
            return "medium"
        if model.resolved_model is not None and model.resolved_model.hash:
            return "medium"
        return "low"

    @staticmethod
    def _derive_overall_confidence(
        confidence_levels: list[str],
        unresolved_items: list[dict[str, str]],
    ) -> str:
        if unresolved_items:
            return "incomplete"
        if "low" in confidence_levels:
            return "low"
        if "medium" in confidence_levels:
            return "medium"
        return "high"
