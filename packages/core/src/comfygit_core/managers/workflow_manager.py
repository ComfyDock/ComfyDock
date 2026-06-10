"""Auto workflow tracking - all workflows in ComfyUI are automatically managed."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from comfygit_core.models.shared import ModelWithLocation
from comfygit_core.repositories.node_mappings_repository import NodeMappingsRepository
from comfygit_core.resolvers.global_node_resolver import GlobalNodeResolver

from ..logging.logging_config import get_logger
from ..models.protocols import ModelResolutionStrategy, NodeResolutionStrategy
from ..models.workflow import (
    BatchDownloadCallbacks,
    DetailedWorkflowStatus,
    DownloadResult,
    ResolutionResult,
    ResolvedModel,
    ScoredMatch,
    WorkflowAnalysisStatus,
    WorkflowNodeWidgetRef,
    WorkflowSyncStatus,
)
from ..resolvers.model_resolver import ModelResolver
from ..services.model_downloader import ModelDownloader
from ..services.workflow_analysis_cache import WorkflowAnalysisCache
from ..services.workflow_file_store import WorkflowFileStore, normalize_workflow_filename
from ..services.workflow_manifest_reconciler import WorkflowManifestReconciler
from ..services.workflow_manual_model_policy import WorkflowManualModelPolicy
from ..services.workflow_model_dependency_service import WorkflowModelDependencyService
from ..services.workflow_model_download_coordinator import WorkflowModelDownloadCoordinator
from ..services.workflow_model_path_policy import WorkflowModelPathPolicy
from ..services.workflow_node_package_policy import WorkflowNodePackagePolicy
from ..services.workflow_resolution_context_builder import (
    WorkflowResolutionContextBuilder,
)
from ..services.workflow_resolution_fixer import WorkflowResolutionFixer
from ..services.workflow_resolution_service import (
    WorkflowResolutionService,
)
from ..services.workflow_state_cleanup import WorkflowStateCleanup

if TYPE_CHECKING:
    from ..caching.workflow_cache import WorkflowCacheRepository
    from ..models.workflow import (
        NodeResolutionContext,
        ResolvedNodePackage,
        ScoredPackageMatch,
        WorkflowDependencies,
        WorkflowNode,
    )
    from ..repositories.comfyui_builtin_versions_repository import (
        ComfyUIBuiltinVersionsRepository,
    )
    from ..repositories.model_repository import ModelRepository
    from .pyproject_manager import PyprojectManager

logger = get_logger(__name__)

class WorkflowManager:
    """Manages all workflows automatically - no explicit tracking needed.

    Architectural note: repositories are injected by Environment/Workspace
    instead of discovered lazily to keep dependencies explicit and testable.
    """

    def __init__(
        self,
        comfyui_path: Path,
        cec_path: Path,
        pyproject: PyprojectManager,
        model_repository: ModelRepository,
        node_mapping_repository: NodeMappingsRepository,
        model_downloader: ModelDownloader,
        workflow_cache: WorkflowCacheRepository,
        environment_name: str,
        builtin_versions_repository: ComfyUIBuiltinVersionsRepository | None,
    ):
        self.comfyui_path = comfyui_path
        self.cec_path = cec_path
        self.pyproject = pyproject
        self.model_repository = model_repository
        self.node_mapping_repository = node_mapping_repository
        self.workflow_cache = workflow_cache
        self.environment_name = environment_name
        # Keep this dependency explicit: Environment provides a workspace-owned
        # repository so WorkflowManager does not reach through other services.
        self.builtin_versions_repository = builtin_versions_repository

        self.workflow_file_store = WorkflowFileStore(
            comfyui_path,
            cec_path,
            environment_name=environment_name,
            workflow_cache=workflow_cache,
        )
        # Compatibility attributes for existing package-local tests and callers.
        self.comfyui_workflows = self.workflow_file_store.comfyui_workflows
        self.cec_workflows = self.workflow_file_store.cec_workflows
        self.workflow_state_cleanup = WorkflowStateCleanup(
            manifest=self.pyproject.manifest,
            workflows=self.pyproject.workflows,
            workflow_file_store=self.workflow_file_store,
            cec_path=self.cec_path,
        )
        pyproject_path = getattr(self.pyproject, "path", None)
        self.workflow_analysis_cache = WorkflowAnalysisCache(
            workflow_file_store=self.workflow_file_store,
            workflow_cache=workflow_cache,
            environment_name=environment_name,
            cec_path=cec_path,
            pyproject_path=pyproject_path if isinstance(pyproject_path, Path) else None,
            builtin_versions_repository=builtin_versions_repository,
        )

        # Create repository and inject into resolver
        self.global_node_resolver = GlobalNodeResolver(self.node_mapping_repository)
        self.model_resolver = ModelResolver(
            model_repository=self.model_repository,
            cec_path=self.cec_path
        )
        self.workflow_resolution_service = WorkflowResolutionService(
            self.global_node_resolver,
            self.model_resolver,
        )
        self.node_package_policy = WorkflowNodePackagePolicy(
            pyproject=self.pyproject,
            global_node_resolver=self.global_node_resolver,
            node_mapping_repository=self.node_mapping_repository,
        )
        self.manual_model_policy = WorkflowManualModelPolicy()
        self.workflow_resolution_context_builder = WorkflowResolutionContextBuilder(
            pyproject=self.pyproject,
            model_repository=self.model_repository,
            cec_path=self.cec_path,
            builtin_versions_repository=self.builtin_versions_repository,
            normalize_package_id=self.node_package_policy.normalize_package_id,
        )
        self.workflow_model_path_policy = self._create_workflow_model_path_policy()
        self.manifest_reconciler = self._create_manifest_reconciler()
        self._workflow_model_dependencies = WorkflowModelDependencyService(
            workflows=self.pyproject.workflows,
            models=self.pyproject.models,
            model_repository=self.model_repository,
        )

        # Use injected model downloader from workspace
        self.downloader = model_downloader
        self._workflow_model_downloads = WorkflowModelDownloadCoordinator(
            downloader=self.downloader,
            model_sources=self.model_repository,
            dependencies=self._workflow_model_dependencies,
        )
        self.workflow_resolution_fixer = WorkflowResolutionFixer(
            nodes=self.pyproject.nodes,
            workflows=self.pyproject.workflows,
            models=self.pyproject.models,
            search_packages=lambda *args, **kwargs: self.global_node_resolver.search_packages(
                *args,
                **kwargs,
            ),
            search_models=lambda query, node_type=None, limit=9: self.search_models(
                query,
                node_type,
                limit,
            ),
            downloader=self.downloader,
            consensus_custom_node_map=lambda workflow_name: self._get_consensus_custom_node_map(
                workflow_name,
            ),
            normalize_package_id=lambda package_id: self._normalize_package_id(
                package_id,
            ),
            write_single_node_resolution=lambda workflow_name, package_id: self._write_single_node_resolution(
                workflow_name,
                package_id,
            ),
            write_model_resolution_grouped=lambda workflow_name, resolved, refs: self._write_model_resolution_grouped(
                workflow_name,
                resolved,
                refs,
            ),
            update_workflow_model_paths=lambda result: self.update_workflow_model_paths(
                result,
            ),
        )

    def refresh_runtime_metadata_context(self) -> None:
        """Reload resolver state derived from local ComfyUI metadata files."""
        self.model_resolver = ModelResolver(
            model_repository=self.model_repository,
            cec_path=self.cec_path,
        )
        self.workflow_resolution_service = WorkflowResolutionService(
            self.global_node_resolver,
            self.model_resolver,
        )
        self.workflow_model_path_policy = self._create_workflow_model_path_policy()
        self.manifest_reconciler = self._create_manifest_reconciler()

    def _create_workflow_model_path_policy(self) -> WorkflowModelPathPolicy:
        """Create workflow model path policy from current runtime metadata."""
        return WorkflowModelPathPolicy(
            model_repository=self.model_repository,
            model_config=self.model_resolver.model_config,
            workflow_file_store=self.workflow_file_store,
            workflow_cache=self.workflow_cache,
            environment_name=self.environment_name,
        )

    def _get_workflow_model_path_policy(self) -> WorkflowModelPathPolicy:
        """Return model path policy matching the current runtime metadata."""
        if self.workflow_model_path_policy.model_config is not self.model_resolver.model_config:
            self.workflow_model_path_policy = self._create_workflow_model_path_policy()
            self.manifest_reconciler = self._create_manifest_reconciler()
        return self.workflow_model_path_policy

    def _create_manifest_reconciler(self) -> WorkflowManifestReconciler:
        """Create manifest reconciler from explicit workflow policy services."""
        return WorkflowManifestReconciler(
            pyproject=self.pyproject,
            model_repository=self.model_repository,
            node_package_policy=self.node_package_policy,
            model_path_policy=self.workflow_model_path_policy,
            manual_model_policy=self.manual_model_policy,
        )

    def _normalize_model_relative_path(self, relative_path: str) -> str:
        """Normalize and validate a path relative to the configured models directory."""
        return self.manual_model_policy.normalize_model_relative_path(relative_path)

    def _category_for_indexed_model(self, model: ModelWithLocation) -> str:
        """Return the manifest category for an indexed model location."""
        return self.manual_model_policy.category_for_indexed_model(model)

    def _is_manual_workflow_model(self, model) -> bool:
        """Return whether a workflow model was manually declared outside graph analysis."""
        return self.manual_model_policy.is_manual_workflow_model(model)

    def _manual_workflow_model_key(self, model) -> tuple[str, str] | None:
        return self.manual_model_policy.manual_workflow_model_key(model)

    def _source_urls_for_model_hash(self, model_hash: str) -> list[str]:
        """Return source URLs currently known in the workspace model index."""
        try:
            sources = self.model_repository.get_sources(model_hash)
        except Exception as exc:
            logger.debug(f"Unable to load sources for model {model_hash}: {exc}")
            return []

        urls: list[str] = []
        seen: set[str] = set()
        for source in sources or []:
            if not isinstance(source, dict):
                continue
            url = source.get("url") or source.get("source_url")
            if isinstance(url, str) and url and url not in seen:
                urls.append(url)
                seen.add(url)
        return urls

    def _resolve_indexed_model_for_workflow_dependency(
        self,
        model_hash: str | None = None,
        relative_path: str | None = None,
    ) -> ModelWithLocation:
        """Resolve an existing indexed model for a manual workflow dependency."""
        if not model_hash and not relative_path:
            raise ValueError("Provide model_hash or relative_path")

        if relative_path:
            normalized_path = self._normalize_model_relative_path(relative_path)
            model = self.model_repository.find_by_exact_path(normalized_path)
            if not model:
                raise ValueError(f"Model is not indexed at path: {normalized_path}")
            if model_hash and model.hash != model_hash:
                raise ValueError(
                    f"Indexed model at {normalized_path} has hash {model.hash}, not {model_hash}"
                )
            return model

        assert model_hash is not None
        matches = self.model_repository.find_model_by_hash(model_hash)
        if not matches:
            raise ValueError(f"Model is not indexed with hash: {model_hash}")
        unique_hashes = {m.hash for m in matches}
        if len(unique_hashes) > 1:
            raise ValueError(f"Model hash prefix is ambiguous: {model_hash}")
        if len(matches) > 1:
            raise ValueError(
                "Model has multiple indexed locations; provide relative_path to choose one"
            )
        return matches[0]

    def _upsert_manual_workflow_model(self, workflow_name: str, manual_model) -> None:
        manual_key = self._manual_workflow_model_key(manual_model)
        models = self.pyproject.workflows.get_workflow_models(workflow_name)

        for idx, existing in enumerate(models):
            if not self._is_manual_workflow_model(existing):
                continue
            if self._manual_workflow_model_key(existing) == manual_key:
                models[idx] = manual_model
                self.pyproject.workflows.set_workflow_models(workflow_name, models)
                return

        models.append(manual_model)
        self.pyproject.workflows.set_workflow_models(workflow_name, models)

    def add_existing_model_to_workflow(
        self,
        workflow_name: str,
        model_hash: str | None = None,
        relative_path: str | None = None,
        criticality: str = "required",
    ):
        """Attach an already-indexed local model as a manual workflow dependency."""
        if criticality not in ("required", "flexible", "optional"):
            raise ValueError(f"Invalid criticality: {criticality}")

        from comfygit_core.models.manifest import ManifestModel, ManifestWorkflowModel

        model = self._resolve_indexed_model_for_workflow_dependency(
            model_hash=model_hash,
            relative_path=relative_path,
        )
        normalized_path = self._normalize_model_relative_path(model.relative_path)
        sources = self._source_urls_for_model_hash(model.hash)

        global_model = ManifestModel(
            hash=model.hash,
            filename=model.filename,
            size=model.file_size,
            relative_path=normalized_path,
            category=self._category_for_indexed_model(model),
            sources=sources,
        )
        self.pyproject.models.add_model(global_model)

        workflow_model = ManifestWorkflowModel(
            hash=model.hash,
            filename=model.filename,
            category=global_model.category,
            criticality=criticality,
            status="resolved",
            nodes=[],
            sources=[],
            relative_path=normalized_path,
            declared_by="manual",
        )
        self._upsert_manual_workflow_model(workflow_name, workflow_model)
        return workflow_model

    def remove_manual_model_from_workflow(
        self,
        workflow_name: str,
        model_hash: str | None = None,
        relative_path: str | None = None,
    ) -> bool:
        """Remove a manually declared workflow model dependency."""
        if not model_hash and not relative_path:
            raise ValueError("Provide model_hash or relative_path")

        target_path = (
            self._normalize_model_relative_path(relative_path)
            if relative_path
            else None
        )
        models = self.pyproject.workflows.get_workflow_models(workflow_name)
        kept = []
        removed = False

        for model in models:
            if not self._is_manual_workflow_model(model):
                kept.append(model)
                continue

            model_path = (
                self._normalize_model_relative_path(model.relative_path)
                if model.relative_path
                else None
            )
            path_matches = bool(target_path and model_path == target_path)
            hash_matches = bool(model_hash and model.hash == model_hash)
            if path_matches or hash_matches:
                removed = True
                continue
            kept.append(model)

        if removed:
            self.pyproject.workflows.set_workflow_models(workflow_name, kept)
        return removed

    def _normalize_package_id(self, package_id: str) -> str:
        """Normalize package IDs for manifest storage."""
        return self.node_package_policy.normalize_package_id(package_id)

    def _get_consensus_custom_node_map(self, workflow_name: str) -> dict[str, str | bool]:
        """Return unambiguous custom node mappings learned from other workflows."""
        return self.workflow_resolution_context_builder.consensus_custom_node_map(
            workflow_name
        )


    def _write_model_resolution_grouped(
        self,
        workflow_name: str,
        resolved: ResolvedModel,
        all_refs: list[WorkflowNodeWidgetRef]
    ) -> None:
        """Write model resolution for multiple node references (deduplicated).

        This is the deduplication-aware version of _write_single_model_resolution().
        When the same model appears in multiple nodes, all refs are written together
        in a single ManifestWorkflowModel entry.

        Args:
            workflow_name: Workflow being resolved
            resolved: ResolvedModel with resolution result
            all_refs: ALL node references for this model (deduplicated group)
        """
        invalidate_cache = self.manifest_reconciler.write_model_resolution_grouped(
            workflow_name,
            resolved,
            all_refs,
        )
        if invalidate_cache:
            self.workflow_cache.invalidate(
                env_name=self.environment_name,
                workflow_name=workflow_name
            )

    def _write_single_node_resolution(
        self,
        workflow_name: str,
        node_package_id: str
    ) -> None:
        """Write a single node resolution immediately (progressive mode).

        Updates workflow.nodes section in pyproject.toml for ONE node.
        This enables Ctrl+C safety and auto-resume.

        Args:
            workflow_name: Workflow being resolved
            node_package_id: Package ID to add to workflow.nodes
        """
        self.manifest_reconciler.write_single_node_resolution(
            workflow_name,
            node_package_id,
        )

    def get_workflow_path(self, name: str) -> Path:
        """Check if workflow exists in ComfyUI directory and return path.

        Args:
            name: Workflow name

        Returns:
            Path to workflow file if it exists

        Raises:
            FileNotFoundError
        """
        return self.workflow_file_store.get_workflow_path(name)

    def get_workflow_sync_status(self) -> WorkflowSyncStatus:
        """Get file-level sync status between ComfyUI and .cec.

        Returns:
            WorkflowSyncStatus with categorized workflow lists
        """
        return self.workflow_file_store.get_workflow_sync_status()

    def _workflows_differ(self, name: str) -> bool:
        """Check if workflow differs between ComfyUI and .cec.

        Args:
            name: Workflow name

        Returns:
            True if workflows differ or .cec copy doesn't exist
        """
        return self.workflow_file_store.workflows_differ(name)

    def cleanup_orphaned_workflow_entries(self, config: dict | None = None) -> int:
        """Remove manifest workflow entries whose editable workflow file is gone."""
        return self.workflow_state_cleanup.cleanup_orphaned_workflow_entries(config=config)

    def cleanup_orphaned_workflow_api_prompts(self, config: dict | None = None) -> int:
        """Remove workflow API prompt files not referenced by remaining contracts."""
        return self.workflow_state_cleanup.cleanup_orphaned_workflow_api_prompts(config=config)

    def cleanup_orphaned_workflow_state(self, config: dict | None = None) -> dict[str, int]:
        """Clean manifest workflow orphans and unreferenced workflow API artifacts."""
        return self.workflow_state_cleanup.cleanup(config=config).to_dict()

    def copy_all_workflows(self) -> dict[str, Path | str | None]:
        """Copy ALL workflows from ComfyUI to .cec for commit.

        Returns:
            Dictionary of workflow names to Path
        """
        return self.workflow_file_store.copy_all_workflows()

    def capture_workflow(self, name: str) -> Path:
        """Capture one saved ComfyUI workflow into tracked working state.

        This copies the saved workflow JSON into `.cec/workflows` and ensures
        the pyproject-backed manifest has a workflow entry/path. It does not
        commit or perform dependency resolution.
        """
        workflow_name = normalize_workflow_filename(name)
        tracked_path = self.workflow_file_store.copy_workflow(workflow_name)
        self.pyproject.manifest.ensure_workflow(workflow_name)
        return tracked_path

    def restore_from_cec(self, name: str) -> bool:
        """Restore a workflow from .cec to ComfyUI directory.

        Args:
            name: Workflow name

        Returns:
            True if successful, False if workflow not found
        """
        return self.workflow_file_store.restore_from_cec(name)

    def restore_all_from_cec(self, preserve_uncommitted: bool = False) -> dict[str, str]:
        """Restore all workflows from .cec to ComfyUI.

        Args:
            preserve_uncommitted: If True, don't delete workflows not in .cec.
                                 This enables git-like behavior where uncommitted
                                 changes are preserved during branch switches.
                                 If False, force ComfyUI to match .cec exactly
                                 (current behavior for rollback operations).

        Returns:
            Dictionary of workflow names to restore status
        """
        return self.workflow_file_store.restore_all_from_cec(
            preserve_uncommitted=preserve_uncommitted,
        )

    def analyze_single_workflow_status(
        self,
        name: str,
        sync_state: str,
        installed_nodes: set[str] | None = None
    ) -> WorkflowAnalysisStatus:
        """Analyze a single workflow for dependencies and resolution status.

        This is read-only - no side effects, no copying, just analysis.

        Args:
            name: Workflow name
            sync_state: Sync state ("new", "modified", "deleted", "synced")
            installed_nodes: Pre-loaded set of installed node IDs (avoids re-reading pyproject)

        Returns:
            WorkflowAnalysisStatus with complete dependency and resolution info
        """
        # Analyze and resolve workflow (cached)
        dependencies, resolution = self.analyze_and_resolve_workflow(name)

        # Calculate uninstalled nodes from current resolution
        if installed_nodes is None:
            installed_nodes = set(self.pyproject.nodes.get_existing().keys())

        resolved_packages = {r.package_id for r in resolution.nodes_resolved if r.package_id}
        uninstalled_nodes = list(resolved_packages - installed_nodes)

        return WorkflowAnalysisStatus(
            name=name,
            sync_state=sync_state,
            dependencies=dependencies,
            resolution=resolution,
            uninstalled_nodes=uninstalled_nodes
        )

    def get_workflow_status(self) -> DetailedWorkflowStatus:
        """Get detailed workflow status with full dependency analysis.

        Analyzes ALL workflows in ComfyUI directory, checking dependencies
        and resolution status. This is read-only - no copying to .cec.

        Returns:
            DetailedWorkflowStatus with sync status and analysis for each workflow
        """
        sync_status = self.get_workflow_sync_status()
        installed_nodes = set(self.pyproject.nodes.get_existing().keys())

        all_workflow_names = sync_status.new + sync_status.modified + sync_status.synced
        analyzed: list[WorkflowAnalysisStatus] = []

        for name in all_workflow_names:
            if name in sync_status.new:
                state = "new"
            elif name in sync_status.modified:
                state = "modified"
            else:
                state = "synced"

            try:
                analysis = self.analyze_single_workflow_status(name, state, installed_nodes)
                analyzed.append(analysis)
            except Exception as e:
                logger.error(f"Failed to analyze workflow {name}: {e}")

        return DetailedWorkflowStatus(
            sync_status=sync_status,
            analyzed_workflows=analyzed
        )

    def analyze_and_resolve_workflow(self, name: str) -> tuple[WorkflowDependencies, ResolutionResult]:
        """Analyze and resolve workflow with full caching.

        This is the preferred method for performance - caches BOTH analysis and resolution.

        Args:
            name: Workflow name

        Returns:
            Tuple of (dependencies, resolution)

        Raises:
            FileNotFoundError if workflow not found
        """
        return self.workflow_analysis_cache.analyze_and_resolve_workflow(
            name,
            self.resolve_dependencies,
        )

    def analyze_and_resolve_workflow_json(
        self,
        workflow_data: Mapping[str, object],
        *,
        workflow_name: str = "unsaved",
    ) -> tuple[WorkflowDependencies, ResolutionResult]:
        """Analyze and resolve workflow JSON that has not necessarily been saved."""
        from ..analyzers.workflow_dependency_parser import WorkflowDependencyParser
        from ..models.workflow import Workflow

        workflow = Workflow.from_json(dict(workflow_data))
        parser = WorkflowDependencyParser(
            workflow=workflow,
            workflow_name=workflow_name,
            cec_path=self.cec_path,
            builtin_versions_repository=self.builtin_versions_repository,
        )
        dependencies = parser.analyze_dependencies()
        return dependencies, self.resolve_dependencies(dependencies)

    def resolve_dependencies(self, analysis: WorkflowDependencies) -> ResolutionResult:
        """Attempt automatic resolution of workflow dependencies.

        Takes the provided analysis and tries to resolve:
        - Missing nodes → node packages from registry/GitHub using GlobalNodeResolver
        - Model references → actual model files in index

        Returns ResolutionResult showing what was resolved and what remains ambiguous.
        Does NOT modify pyproject.toml - that happens in fix_workflow().

        Args:
            analysis: Workflow dependencies from analyze_and_resolve_workflow()

        Returns:
            ResolutionResult with resolved and unresolved dependencies
        """
        context = self.workflow_resolution_context_builder.build_runtime_context(
            analysis,
            auto_select_ambiguous=True,  # TODO: Make configurable
        )

        resolution_service = getattr(self, "workflow_resolution_service", None)
        if resolution_service is None:
            resolution_service = WorkflowResolutionService(
                self.global_node_resolver,
                self.model_resolver,
            )

        resolution = resolution_service.resolve(analysis, context)

        # Environment-specific post-processing that requires filesystem/model index state.
        self._get_workflow_model_path_policy().annotate_resolution(resolution)

        return resolution

    def get_package_aliases(self) -> Mapping[str, str]:
        """Return global node package alias metadata used during workflow resolution."""
        repository = getattr(self.global_node_resolver, "repository", None)
        global_mappings = getattr(repository, "global_mappings", None)
        aliases = getattr(global_mappings, "package_aliases", None)
        return aliases if isinstance(aliases, dict) else {}

    def search_node_packages(
        self,
        query: str,
        *,
        include_registry: bool = True,
        limit: int = 10,
    ) -> list[ScoredPackageMatch]:
        """Search node packages using current manifest nodes for installed-package context."""
        return self.global_node_resolver.search_packages(
            query,
            self.pyproject.nodes.get_existing(),
            include_registry,
            limit,
        )

    def resolve_node_packages(
        self,
        node: WorkflowNode,
        context: NodeResolutionContext,
    ) -> list[ResolvedNodePackage] | None:
        """Resolve one workflow node type through the configured node resolver."""
        return self.global_node_resolver.resolve_single_node_with_context(
            node,
            context,
        )

    def fix_resolution(
        self,
        resolution: ResolutionResult,
        node_strategy: NodeResolutionStrategy | None = None,
        model_strategy: ModelResolutionStrategy | None = None
    ) -> ResolutionResult:
        """Fix remaining issues using strategies with progressive writes.

        Takes ResolutionResult from resolve_dependencies() and uses strategies to resolve ambiguities.
        ALL user choices are written immediately (progressive mode):
        - Each model resolution writes to pyproject + workflow JSON
        - Each node mapping writes to per-workflow custom_node_map
        - Ctrl+C preserves partial progress

        Args:
            resolution: Result from resolve_dependencies()
            node_strategy: Strategy for handling unresolved/ambiguous nodes
            model_strategy: Strategy for handling ambiguous/missing models

        Returns:
            Updated ResolutionResult with fixes applied
        """
        return self.workflow_resolution_fixer.fix_resolution(
            resolution,
            node_strategy,
            model_strategy,
        )

    def apply_resolution(
        self,
        resolution: ResolutionResult,
        config: dict | None = None
    ) -> None:
        """Apply resolutions with smart defaults and reconciliation.

        Auto-applies sensible criticality defaults, etc.

        Args:
            resolution: Result with auto-resolved dependencies from resolve_dependencies()
            config: Optional in-memory config for batched writes. If None, loads and saves immediately.
        """
        is_batch = config is not None
        if not is_batch:
            with self.pyproject.manifest.edit() as edit:
                self.manifest_reconciler.apply_resolution(resolution, config=edit.config)
                self.cleanup_orphaned_workflow_state(config=edit.config)
                self.pyproject.models.cleanup_orphans(config=edit.config)
                edit.mark_changed()
        else:
            assert config is not None
            self.manifest_reconciler.apply_resolution(resolution, config=config)
            self.cleanup_orphaned_workflow_state(config=config)
            self.pyproject.models.cleanup_orphans(config=config)

        # Phase 3: Update workflow JSON with resolved paths
        self.update_workflow_model_paths(resolution)

    def resolution_changes_manifest(
        self,
        resolution: ResolutionResult,
        *,
        config: dict,
    ) -> bool:
        """Return whether resolution metadata needs manifest writeback."""
        return self.manifest_reconciler.resolution_changes_manifest(
            resolution,
            config=config,
        )

    def update_workflow_model_paths(
        self,
        resolution: ResolutionResult
    ) -> int:
        """Update workflow JSON files with resolved builtin model loader paths."""
        return self._get_workflow_model_path_policy().update_workflow_model_paths(resolution)

    def _get_default_criticality(self, category: str) -> str:
        """Determine smart default criticality based on model category.

        Args:
            category: Model category (checkpoints, loras, etc.)

        Returns:
            Criticality level: "required", "flexible", or "optional"
        """
        return self._get_workflow_model_path_policy().default_criticality(category)

    def _get_category_for_node_ref(self, node_ref: WorkflowNodeWidgetRef) -> str:
        """Get model category from node type.

        Args:
            node_type: ComfyUI node type

        Returns:
            Model category string
        """
        return self._get_workflow_model_path_policy().category_for_node_ref(node_ref)

    def _check_path_needs_sync(
        self,
        resolved: ResolvedModel
    ) -> bool:
        """Check if a resolved model's path differs from workflow JSON.

        Args:
            resolved: ResolvedModel with reference and resolved_model

        Returns:
            True if workflow path differs from expected resolved path
        """
        return self._get_workflow_model_path_policy().path_needs_sync(resolved)

    def _check_category_mismatch(
        self,
        resolved: ResolvedModel,
    ) -> tuple[bool, list[str], str | None]:
        """Check if model is in wrong category directory for its loader node.

        This is a functional issue (not cosmetic like path sync) - ComfyUI cannot
        load a model that's in the wrong directory for the node type.

        When a model exists in multiple locations (e.g., copied from checkpoints/
        to loras/), this checks if ANY location satisfies the requirement.
        Only flags mismatch if NO location is in an expected directory.

        Args:
            resolved: ResolvedModel with reference and resolved_model

        Returns:
            Tuple of (has_mismatch, expected_categories, actual_category)
        """
        return self._get_workflow_model_path_policy().category_mismatch(resolved)

    def _strip_base_directory_for_node(self, node_type: str, relative_path: str) -> str:
        """Strip base directory prefix from path for BUILTIN ComfyUI node loaders.

        ⚠️ IMPORTANT: This function should ONLY be called for builtin node types that
        are in the node_directory_mappings. Custom nodes should skip path updates entirely.

        ComfyUI builtin node loaders automatically prepend their base directories:
        - CheckpointLoaderSimple prepends "checkpoints/"
        - LoraLoader prepends "loras/"
        - VAELoader prepends "vae/"

        The widget value should NOT include the base directory to avoid path doubling.

        See: docs/knowledge/comfyui-node-loader-base-directories.md for detailed explanation.

        Args:
            node_type: BUILTIN ComfyUI node type (e.g., "CheckpointLoaderSimple")
            relative_path: Full path relative to models/ (e.g., "checkpoints/SD1.5/model.safetensors")

        Returns:
            Path without base directory prefix (e.g., "SD1.5/model.safetensors")

        Examples:
            >>> _strip_base_directory_for_node("CheckpointLoaderSimple", "checkpoints/sd15/model.ckpt")
            "sd15/model.ckpt"

            >>> _strip_base_directory_for_node("LoraLoader", "loras/style.safetensors")
            "style.safetensors"

            >>> _strip_base_directory_for_node("CheckpointLoaderSimple", "checkpoints/a/b/c/model.ckpt")
            "a/b/c/model.ckpt"  # Subdirectories preserved
        """
        return self._get_workflow_model_path_policy().strip_base_directory_for_node(
            node_type,
            relative_path,
        )

    def search_models(
        self,
        search_term: str,
        node_type: str | None = None,
        limit: int = 9
    ) -> list[ScoredMatch]:
        """Search for models using SQL + fuzzy matching.

        Combines fast SQL LIKE search with difflib scoring for ranked results.

        Args:
            search_term: Search term (filename, partial name, etc.)
            node_type: Optional node type to filter by category
            limit: Maximum number of results to return

        Returns:
            List of ScoredMatch objects sorted by relevance (highest first)
        """
        from difflib import SequenceMatcher

        # If node_type provided, filter by category
        if node_type:
            # Use model_config from model_resolver (includes dynamic folder mappings from cec_path)
            directories = self.model_resolver.model_config.get_directories_for_node(node_type)

            if directories:
                # Get models from all relevant categories
                candidates = []
                for directory in directories:
                    models = self.model_repository.get_by_category(directory)
                    candidates.extend(models)
            else:
                # Unknown node type - search all models
                candidates = self.model_repository.search(search_term)
        else:
            # No node type - search all models
            candidates = self.model_repository.search(search_term)

        if not candidates:
            return []

        # Score candidates using fuzzy matching
        scored = []
        search_lower = search_term.lower()
        search_stem = Path(search_term).stem.lower()

        for model in candidates:
            filename_lower = model.filename.lower()
            filename_stem = Path(model.filename).stem.lower()

            # Calculate scores for both full filename and stem
            full_score = SequenceMatcher(None, search_lower, filename_lower).ratio()
            stem_score = SequenceMatcher(None, search_stem, filename_stem).ratio()

            # Use best score
            score = max(full_score, stem_score)

            # Boost exact substring matches
            if search_lower in filename_lower:
                score = min(1.0, score + 0.15)

            if score > 0.3:  # Minimum 30% similarity threshold
                confidence = "high" if score > 0.8 else "good" if score > 0.6 else "possible"
                scored.append(ScoredMatch(
                    model=model,
                    score=score,
                    confidence=confidence
                ))

        # Sort by score descending
        scored.sort(key=lambda x: x.score, reverse=True)

        return scored[:limit]

    def update_model_criticality(
        self,
        workflow_name: str,
        model_identifier: str,
        new_criticality: str
    ) -> bool:
        """Update criticality for a model in a workflow.

        Allows changing model criticality after initial resolution without
        re-resolving the entire workflow.

        Args:
            workflow_name: Workflow to update
            model_identifier: Filename or hash to match
            new_criticality: "required", "flexible", or "optional"

        Returns:
            True if model was found and updated, False otherwise

        Raises:
            ValueError: If new_criticality is not valid
        """
        return self._workflow_model_dependencies.update_criticality(
            workflow_name,
            model_identifier,
            new_criticality,
        )

    def mark_model_download_resolved_by_reference(
        self,
        workflow_name: str,
        reference: WorkflowNodeWidgetRef,
        model_hash: str,
    ) -> None:
        """Mark a workflow download intent as resolved by widget reference."""
        self._workflow_model_dependencies.mark_download_resolved_by_reference(
            workflow_name,
            reference,
            model_hash,
        )

    def mark_model_download_resolved_by_filename(
        self,
        workflow_name: str,
        *,
        filename: str,
        model_hash: str,
    ) -> bool:
        """Mark a workflow download intent as resolved by filename."""
        return self._workflow_model_dependencies.mark_download_resolved_by_filename(
            workflow_name,
            filename=filename,
            model_hash=model_hash,
        )

    def execute_pending_downloads(
        self,
        result: ResolutionResult,
        callbacks: BatchDownloadCallbacks | None = None
    ) -> list[DownloadResult]:
        """Execute batch downloads for all download intents in result.

        All user-facing output is delivered via callbacks.

        Args:
            result: Resolution result containing download intents
            callbacks: Optional callbacks for progress/status (provided by CLI)

        Returns:
            List of DownloadResult objects
        """
        return self._workflow_model_downloads.execute_pending_downloads(
            result,
            callbacks,
        )
