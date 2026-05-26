"""Auto workflow tracking - all workflows in ComfyUI are automatically managed."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

from comfygit_core.models.shared import ModelWithLocation
from comfygit_core.repositories.node_mappings_repository import NodeMappingsRepository
from comfygit_core.resolvers.global_node_resolver import GlobalNodeResolver

from ..logging.logging_config import get_logger
from ..models.protocols import ModelResolutionStrategy, NodeResolutionStrategy
from ..models.workflow import (
    BatchDownloadCallbacks,
    DetailedWorkflowStatus,
    ModelResolutionContext,
    NodeResolutionContext,
    ResolutionResult,
    ResolvedModel,
    ScoredMatch,
    WorkflowAnalysisStatus,
    WorkflowNode,
    WorkflowNodeWidgetRef,
    WorkflowSyncStatus,
)
from ..resolvers.model_resolver import ModelResolver
from ..services.model_downloader import ModelDownloader
from ..services.workflow_analysis_cache import WorkflowAnalysisCache
from ..services.workflow_file_store import WorkflowFileStore
from ..services.workflow_manifest_reconciler import WorkflowManifestReconciler
from ..services.workflow_manual_model_policy import WorkflowManualModelPolicy
from ..services.workflow_model_path_policy import WorkflowModelPathPolicy
from ..services.workflow_node_package_policy import WorkflowNodePackagePolicy
from ..services.workflow_resolution_context_builder import (
    WorkflowResolutionContextBuilder,
)
from ..services.workflow_resolution_service import (
    WorkflowResolutionService,
)

if TYPE_CHECKING:
    from ..caching.workflow_cache import WorkflowCacheRepository
    from ..models.workflow import ResolvedNodePackage, WorkflowDependencies
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

        # Use injected model downloader from workspace
        self.downloader = model_downloader

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

    @staticmethod
    def _normalize_workflow_api_prompt_ref(value: object) -> str | None:
        if not isinstance(value, str):
            return None

        ref = value.strip()
        if not ref:
            return None

        path = PurePosixPath(ref.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            return None
        if not path.parts or path.parts[0] != "workflow_api":
            return None

        return path.as_posix()

    @staticmethod
    def _workflow_entries_from_config(config: dict) -> Mapping[str, object]:
        workflows = config.get("tool", {}).get("comfygit", {}).get("workflows", {})
        if isinstance(workflows, Mapping):
            return workflows
        return {}

    def _referenced_workflow_api_prompt_files(self, config: dict) -> set[str]:
        workflows = self._workflow_entries_from_config(config)

        referenced: set[str] = set()
        for workflow_data in workflows.values():
            if not isinstance(workflow_data, Mapping):
                continue

            workflow_entry = cast("Mapping[str, object]", workflow_data)
            contract = workflow_entry.get("execution_contract")
            if not isinstance(contract, Mapping):
                continue

            contract_entry = cast("Mapping[str, object]", contract)
            ref = self._normalize_workflow_api_prompt_ref(
                contract_entry.get("api_prompt_file")
            )
            if ref:
                referenced.add(ref)

        return referenced

    def cleanup_orphaned_workflow_entries(self, config: dict | None = None) -> int:
        """Remove manifest workflow entries whose editable workflow file is gone."""
        is_batch = config is not None
        if config is None:
            with self.pyproject.manifest.edit() as edit:
                removed_count = self.cleanup_orphaned_workflow_entries(config=edit.config)
                if removed_count > 0:
                    edit.mark_changed()
                return removed_count

        workflows = self._workflow_entries_from_config(config)

        workflows_in_pyproject = set(workflows.keys())
        workflows_in_comfyui = set()
        if self.comfyui_workflows.exists():
            workflows_in_comfyui = {
                f.stem for f in self.comfyui_workflows.glob("*.json")
            }

        orphaned_workflows = sorted(workflows_in_pyproject - workflows_in_comfyui)
        if not orphaned_workflows:
            return 0

        removed_count = self.pyproject.workflows.remove_workflows(
            orphaned_workflows,
            config=config,
        )
        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} deleted workflow(s) from pyproject.toml")
            if not is_batch:
                self.pyproject.save(config)

        return removed_count

    def cleanup_orphaned_workflow_api_prompts(self, config: dict | None = None) -> int:
        """Remove workflow API prompt files not referenced by remaining contracts."""
        workflow_api_dir = self.cec_path / "workflow_api"
        if not workflow_api_dir.exists():
            return 0

        if config is not None:
            referenced = self._referenced_workflow_api_prompt_files(config)
        else:
            workflows = self.pyproject.get_manifest_snapshot().workflows
            referenced = {
                contract.api_prompt_file
                for workflow in workflows.values()
                if workflow.execution_contract is not None
                for contract in [workflow.execution_contract]
                if contract.api_prompt_file
            }
        removed_count = 0

        for api_file in sorted(workflow_api_dir.rglob("*.json")):
            if not api_file.is_file():
                continue

            rel_path = api_file.relative_to(self.cec_path).as_posix()
            if rel_path in referenced:
                continue

            try:
                api_file.unlink()
                removed_count += 1
                logger.info(
                    f"Removed unreferenced workflow API prompt artifact: {rel_path}"
                )

                parent = api_file.parent
                while parent != workflow_api_dir:
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
            except OSError as e:
                logger.warning(
                    f"Failed to remove unreferenced workflow API prompt '{rel_path}': {e}"
                )

        return removed_count

    def cleanup_orphaned_workflow_state(self, config: dict | None = None) -> dict[str, int]:
        """Clean manifest workflow orphans and unreferenced workflow API artifacts."""
        removed_workflows = self.cleanup_orphaned_workflow_entries(config=config)
        removed_api_prompts = self.cleanup_orphaned_workflow_api_prompts(config=config)
        return {
            "workflow_entries": removed_workflows,
            "api_prompts": removed_api_prompts,
        }

    def copy_all_workflows(self) -> dict[str, Path | str | None]:
        """Copy ALL workflows from ComfyUI to .cec for commit.

        Returns:
            Dictionary of workflow names to Path
        """
        return self.workflow_file_store.copy_all_workflows()

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

    def analyze_workflow(self, name: str) -> WorkflowDependencies:
        """Analyze a single workflow for dependencies - with caching.

        NOTE: For best performance, use analyze_and_resolve_workflow() which
        caches BOTH analysis and resolution.

        Args:
            name: Workflow name

        Returns:
            WorkflowDependencies

        Raises:
            FileNotFoundError if workflow not found
        """
        return self.workflow_analysis_cache.analyze_workflow(name)

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
            self.resolve_workflow,
        )

    def resolve_workflow(self, analysis: WorkflowDependencies) -> ResolutionResult:
        """Attempt automatic resolution of workflow dependencies.

        Takes the provided analysis and tries to resolve:
        - Missing nodes → node packages from registry/GitHub using GlobalNodeResolver
        - Model references → actual model files in index

        Returns ResolutionResult showing what was resolved and what remains ambiguous.
        Does NOT modify pyproject.toml - that happens in fix_workflow().

        Args:
            analysis: Workflow dependencies from analyze_workflow()

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

    def fix_resolution(
        self,
        resolution: ResolutionResult,
        node_strategy: NodeResolutionStrategy | None = None,
        model_strategy: ModelResolutionStrategy | None = None
    ) -> ResolutionResult:
        """Fix remaining issues using strategies with progressive writes.

        Takes ResolutionResult from resolve_workflow() and uses strategies to resolve ambiguities.
        ALL user choices are written immediately (progressive mode):
        - Each model resolution writes to pyproject + workflow JSON
        - Each node mapping writes to per-workflow custom_node_map
        - Ctrl+C preserves partial progress

        Args:
            resolution: Result from resolve_workflow()
            node_strategy: Strategy for handling unresolved/ambiguous nodes
            model_strategy: Strategy for handling ambiguous/missing models

        Returns:
            Updated ResolutionResult with fixes applied
        """
        workflow_name = resolution.workflow_name

        # Start with what was already resolved
        nodes_to_add = list(resolution.nodes_resolved)
        nodes_version_gated = list(resolution.nodes_version_gated)
        nodes_uninstallable = list(resolution.nodes_uninstallable)
        node_guidance = dict(resolution.node_guidance)
        models_to_add = list(resolution.models_resolved)

        remaining_nodes_ambiguous: list[list[ResolvedNodePackage]] = []
        remaining_nodes_unresolved: list[WorkflowNode] = []
        remaining_models_ambiguous: list[list[ResolvedModel]] = []
        remaining_models_unresolved: list[WorkflowNodeWidgetRef] = []

        # ========== NODE RESOLUTION (UNIFIED) ==========

        if not node_strategy:
            # No strategy - keep everything as unresolved
            remaining_nodes_ambiguous = list(resolution.nodes_ambiguous)
            remaining_nodes_unresolved = list(resolution.nodes_unresolved)
        else:
            # Build context with search function
            node_context = NodeResolutionContext(
                installed_packages=self.pyproject.nodes.get_existing(),
                custom_mappings={
                    **self._get_consensus_custom_node_map(workflow_name),
                    **self.pyproject.workflows.get_custom_node_map(workflow_name),
                },
                workflow_name=workflow_name,
                search_fn=self.global_node_resolver.search_packages,
                auto_select_ambiguous=True  # TODO: Make configurable
            )

            # Unified loop: handle both ambiguous and unresolved nodes
            all_unresolved_nodes: list[tuple[str, list[ResolvedNodePackage]]] = []

            # Ambiguous nodes (have candidates)
            for packages in resolution.nodes_ambiguous:
                if packages:
                    node_type = packages[0].node_type
                    all_unresolved_nodes.append((node_type, packages))

            # Missing nodes (no candidates)
            for node in resolution.nodes_unresolved:
                all_unresolved_nodes.append((node.type, []))

            # Resolve each node
            for node_type, candidates in all_unresolved_nodes:
                try:
                    selected = node_strategy.resolve_unknown_node(node_type, candidates, node_context)

                    if selected is None:
                        # User skipped - remains unresolved
                        if candidates:
                            remaining_nodes_ambiguous.append(candidates)
                        else:
                            # Create WorkflowNode for unresolved tracking
                            remaining_nodes_unresolved.append(WorkflowNode(id="", type=node_type))
                        logger.debug(f"Skipped: {node_type}")
                        continue

                    # Handle optional nodes
                    if selected.match_type == 'optional':
                        # PROGRESSIVE: Save optional node mapping
                        if workflow_name:
                            self.pyproject.workflows.set_custom_node_mapping(
                                workflow_name, node_type, None
                            )
                        logger.info(f"Marked node '{node_type}' as optional")
                        continue

                    # Handle resolved nodes
                    nodes_to_add.append(selected)
                    node_id = selected.package_data.id if selected.package_data else selected.package_id

                    if not node_id:
                        logger.warning(f"No package ID for resolved node '{node_type}'")
                        continue

                    normalized_id = self._normalize_package_id(node_id)

                    # PROGRESSIVE: Save user-confirmed node mapping
                    user_intervention_types = ("user_confirmed", "manual", "heuristic")
                    if selected.match_type in user_intervention_types and workflow_name:
                        self.pyproject.workflows.set_custom_node_mapping(
                            workflow_name, node_type, normalized_id
                        )
                        logger.info(f"Saved custom_node_map: {node_type} -> {normalized_id}")

                    # PROGRESSIVE: Write to workflow.nodes immediately
                    if workflow_name:
                        self._write_single_node_resolution(workflow_name, normalized_id)

                    logger.info(f"Resolved node: {node_type} -> {normalized_id}")

                except Exception as e:
                    logger.error(f"Failed to resolve {node_type}: {e}")
                    if candidates:
                        remaining_nodes_ambiguous.append(candidates)
                    else:
                        remaining_nodes_unresolved.append(WorkflowNode(id="", type=node_type))

        # ========== MODEL RESOLUTION (NEW UNIFIED FLOW) ==========

        if not model_strategy:
            # No strategy - keep everything as unresolved
            remaining_models_ambiguous = list(resolution.models_ambiguous)
            remaining_models_unresolved = list(resolution.models_unresolved)
        else:
            # Get global models table for download intent creation
            global_models_dict = {}
            try:
                all_global_models = self.pyproject.models.get_all()
                for model in all_global_models:
                    global_models_dict[model.hash] = model
            except Exception as e:
                logger.warning(f"Failed to load global models table: {e}")

            # Build context with search function and downloader
            model_context = ModelResolutionContext(
                workflow_name=workflow_name,
                global_models=global_models_dict,
                search_fn=self.search_models,
                downloader=self.downloader,
                auto_select_ambiguous=True  # TODO: Make configurable
            )

            # Unified loop: handle both ambiguous and unresolved models
            all_unresolved_models: list[tuple[WorkflowNodeWidgetRef, list[ResolvedModel]]] = []

            # Ambiguous models (have candidates)
            for resolved_model_list in resolution.models_ambiguous:
                if resolved_model_list:
                    model_ref = resolved_model_list[0].reference
                    all_unresolved_models.append((model_ref, resolved_model_list))

            # Missing models (no candidates)
            for model_ref in resolution.models_unresolved:
                all_unresolved_models.append((model_ref, []))

            # DEDUPLICATION: Group by (widget_value, node_type)
            model_groups: dict[tuple[str, str], list[tuple[WorkflowNodeWidgetRef, list[ResolvedModel]]]] = {}

            for model_ref, candidates in all_unresolved_models:
                # Group key: (widget_value, node_type)
                # This ensures same model in same loader type gets resolved once
                key = (model_ref.widget_value, model_ref.node_type)
                if key not in model_groups:
                    model_groups[key] = []
                model_groups[key].append((model_ref, candidates))

            # Resolve each group (one prompt per unique model)
            for (widget_value, _node_type), group in model_groups.items():
                # Extract all refs and candidates
                all_refs_in_group = [ref for ref, _ in group]
                primary_ref, primary_candidates = group[0]

                # Log deduplication for debugging
                if len(all_refs_in_group) > 1:
                    node_ids = ", ".join(f"#{ref.node_id}" for ref in all_refs_in_group)
                    logger.info(f"Deduplicating model '{widget_value}' found in nodes: {node_ids}")

                try:
                    # Prompt user once for this model
                    resolved = model_strategy.resolve_model(primary_ref, primary_candidates, model_context)

                    if resolved is None:
                        # User skipped - remains unresolved for ALL refs
                        for ref in all_refs_in_group:
                            remaining_models_unresolved.append(ref)
                        logger.debug(f"Skipped: {widget_value}")
                        continue

                    # PROGRESSIVE: Write with ALL refs at once
                    if workflow_name:
                        self._write_model_resolution_grouped(workflow_name, resolved, all_refs_in_group)

                    # Add to results for ALL refs (needed for update_workflow_model_paths)
                    for ref in all_refs_in_group:
                        # Create ResolvedModel for each ref pointing to same resolved model
                        ref_resolved = ResolvedModel(
                            workflow=workflow_name,
                            reference=ref,
                            resolved_model=resolved.resolved_model,
                            model_source=resolved.model_source,
                            is_optional=resolved.is_optional,
                            match_type=resolved.match_type,
                            match_confidence=resolved.match_confidence,
                            target_path=resolved.target_path,
                            needs_path_sync=resolved.needs_path_sync
                        )
                        models_to_add.append(ref_resolved)

                    # Log result
                    if resolved.is_optional:
                        logger.info(f"Marked as optional: {widget_value}")
                    elif resolved.resolved_model:
                        logger.info(f"Resolved: {widget_value} → {resolved.resolved_model.filename}")
                    else:
                        logger.info(f"Marked as optional (unresolved): {widget_value}")

                except Exception as e:
                    logger.error(f"Failed to resolve {widget_value}: {e}")
                    for ref in all_refs_in_group:
                        remaining_models_unresolved.append(ref)

        # Build updated result
        result = ResolutionResult(
            workflow_name=workflow_name,
            nodes_resolved=nodes_to_add,
            nodes_version_gated=nodes_version_gated,
            nodes_uninstallable=nodes_uninstallable,
            nodes_unresolved=remaining_nodes_unresolved,
            nodes_ambiguous=remaining_nodes_ambiguous,
            node_guidance=node_guidance,
            models_resolved=models_to_add,
            models_unresolved=remaining_models_unresolved,
            models_ambiguous=remaining_models_ambiguous,
        )

        # Batch update workflow JSON with all resolved model paths
        # This ensures all model paths are synced after interactive resolution
        # Uses consistent node IDs from same parse session (no cache mismatch issues)
        self.update_workflow_model_paths(result)

        return result

    def apply_resolution(
        self,
        resolution: ResolutionResult,
        config: dict | None = None
    ) -> None:
        """Apply resolutions with smart defaults and reconciliation.

        Auto-applies sensible criticality defaults, etc.

        Args:
            resolution: Result with auto-resolved dependencies from resolve_workflow()
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
        # Validate criticality
        if new_criticality not in ("required", "flexible", "optional"):
            raise ValueError(f"Invalid criticality: {new_criticality}")

        # Load workflow models
        models = self.pyproject.workflows.get_workflow_models(workflow_name)

        if not models:
            return False

        # Find matching model(s)
        matches = []
        for i, model in enumerate(models):
            if model.hash == model_identifier or model.filename == model_identifier:
                matches.append((i, model))

        if not matches:
            return False

        # If single match, update directly
        if len(matches) == 1:
            idx, model = matches[0]
            old_criticality = model.criticality
            models[idx].criticality = new_criticality
            self.pyproject.workflows.set_workflow_models(workflow_name, models)
            logger.info(
                f"Updated '{model.filename}' criticality: "
                f"{old_criticality} → {new_criticality}"
            )
            return True

        # Multiple matches - update all and return True
        for idx, _model in matches:
            models[idx].criticality = new_criticality

        self.pyproject.workflows.set_workflow_models(workflow_name, models)
        logger.info(
            f"Updated {len(matches)} model(s) with identifier '{model_identifier}' "
            f"to criticality '{new_criticality}'"
        )
        return True

    def _update_model_hash(
        self,
        workflow_name: str,
        reference: WorkflowNodeWidgetRef,
        new_hash: str
    ) -> None:
        """Update hash for a model after download completes.

        Updates download intent (status=unresolved, sources=[URL]) to resolved state
        by atomically: 1) creating global table entry, 2) updating workflow model.

        Args:
            workflow_name: Workflow containing the model
            reference: Widget reference to identify the model
            new_hash: Hash of downloaded model

        Raises:
            ValueError: If model not found in workflow or repository
        """
        from comfygit_core.models.manifest import ManifestModel

        # Load workflow models
        models = self.pyproject.workflows.get_workflow_models(workflow_name)

        # Find model matching the reference
        for idx, model in enumerate(models):
            if reference in model.nodes:
                # Capture download metadata before clearing
                download_sources = model.sources if model.sources else []

                # STEP 1: Get model from repository (should always exist after download)
                resolved_model = self.model_repository.get_model(new_hash)
                if not resolved_model:
                    raise ValueError(
                        f"Model {new_hash} not found in repository after download. "
                        f"This indicates the model wasn't properly indexed."
                    )

                # STEP 2: Create global table entry FIRST (before clearing workflow model)
                manifest_model = ManifestModel(
                    hash=new_hash,
                    filename=resolved_model.filename,
                    relative_path=resolved_model.relative_path,
                    category=model.category,
                    size=resolved_model.file_size,
                    sources=download_sources
                )
                self.pyproject.models.add_model(manifest_model)

                # STEP 3: Update workflow model (clear transient fields, set hash)
                models[idx].hash = new_hash
                models[idx].status = "resolved"
                models[idx].sources = []
                models[idx].relative_path = None

                # STEP 4: Save workflow models
                self.pyproject.workflows.set_workflow_models(workflow_name, models)

                logger.info(f"Updated model '{model.filename}' with hash {new_hash}")
                return

        raise ValueError(f"Model with reference {reference} not found in workflow '{workflow_name}'")

    def execute_pending_downloads(
        self,
        result: ResolutionResult,
        callbacks: BatchDownloadCallbacks | None = None
    ) -> list:
        """Execute batch downloads for all download intents in result.

        All user-facing output is delivered via callbacks.

        Args:
            result: Resolution result containing download intents
            callbacks: Optional callbacks for progress/status (provided by CLI)

        Returns:
            List of DownloadResult objects
        """
        from ..models.workflow import DownloadResult

        # Collect download intents (both from pyproject and from node properties)
        intents = [
            r for r in result.models_resolved
            if r.match_type in ("download_intent", "property_download_intent")
        ]

        if not intents:
            return []

        # Notify batch start
        if callbacks and callbacks.on_batch_start:
            callbacks.on_batch_start(len(intents))

        results = []
        for idx, resolved in enumerate(intents, 1):
            filename = resolved.reference.widget_value

            # Notify file start
            if callbacks and callbacks.on_file_start:
                callbacks.on_file_start(filename, idx, len(intents))

            # Check if already downloaded (deduplication)
            if resolved.model_source:
                existing = self.model_repository.find_by_source_url(resolved.model_source)
                if existing:
                    # Reuse existing model - update pyproject with hash
                    self._update_model_hash(
                        result.workflow_name,
                        resolved.reference,
                        existing.hash
                    )
                    # Notify success (reused existing)
                    if callbacks and callbacks.on_file_complete:
                        callbacks.on_file_complete(filename, True, None)
                    results.append(DownloadResult(
                        success=True,
                        filename=filename,
                        model=existing,
                        reused=True
                    ))
                    continue

            # Validate required fields
            if not resolved.target_path or not resolved.model_source:
                error_msg = "Download intent missing target_path or model_source"
                if callbacks and callbacks.on_file_complete:
                    callbacks.on_file_complete(filename, False, error_msg)
                results.append(DownloadResult(
                    success=False,
                    filename=filename,
                    error=error_msg
                ))
                continue

            # Download new model
            from ..services.model_downloader import DownloadRequest

            target_path = self.downloader.models_dir / resolved.target_path
            request = DownloadRequest(
                url=resolved.model_source,
                target_path=target_path,
                workflow_name=result.workflow_name
            )

            # Use per-file progress callback if provided
            progress_callback = callbacks.on_file_progress if callbacks else None
            download_result = self.downloader.download(request, progress_callback=progress_callback)

            if download_result.success and download_result.model:
                # Update pyproject with actual hash
                self._update_model_hash(
                    result.workflow_name,
                    resolved.reference,
                    download_result.model.hash
                )
                # Notify success
                if callbacks and callbacks.on_file_complete:
                    callbacks.on_file_complete(filename, True, None)
            else:
                # Notify failure (model remains unresolved with source in pyproject)
                if callbacks and callbacks.on_file_complete:
                    callbacks.on_file_complete(filename, False, download_result.error)

            results.append(DownloadResult(
                success=download_result.success,
                filename=filename,
                model=download_result.model if download_result.success else None,
                error=download_result.error if not download_result.success else None
            ))

        # Notify batch complete
        if callbacks and callbacks.on_batch_complete:
            success_count = sum(1 for r in results if r.success)
            callbacks.on_batch_complete(success_count, len(results))

        return results
