"""Auto workflow tracking - all workflows in ComfyUI are automatically managed."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

from comfygit_core.models.shared import ModelWithLocation
from comfygit_core.repositories.node_mappings_repository import NodeMappingsRepository
from comfygit_core.resolvers.global_node_resolver import GlobalNodeResolver

from ..analyzers.workflow_dependency_parser import WorkflowDependencyParser
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
    Workflow,
    WorkflowAnalysisStatus,
    WorkflowNode,
    WorkflowNodeWidgetRef,
    WorkflowSyncStatus,
)
from ..repositories.workflow_repository import WorkflowRepository
from ..resolvers.model_resolver import ModelResolver
from ..services.model_downloader import ModelDownloader
from ..services.workflow_resolution_service import (
    ResolutionContext,
    WorkflowResolutionService,
)
from ..utils.git import is_git_url
from ..utils.node_identity import resolve_installed_node_alias
from ..utils.workflow_hash import normalize_workflow

if TYPE_CHECKING:
    from ..caching.workflow_cache import WorkflowCacheRepository
    from ..models.workflow import ResolvedNodePackage, WorkflowDependencies
    from ..repositories.comfyui_builtin_versions_repository import (
        ComfyUIBuiltinVersionsRepository,
    )
    from ..repositories.model_repository import ModelRepository
    from .pyproject_manager import PyprojectManager

logger = get_logger(__name__)

CATEGORY_CRITICALITY_DEFAULTS = {
    "checkpoints": "flexible",
    "vae": "flexible",
    "text_encoders": "flexible",
    "loras": "flexible",
    "controlnet": "required",
    "clip_vision": "required",
    "style_models": "flexible",
    "embeddings": "flexible",
    "upscale_models": "flexible",
}


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

        self.comfyui_workflows = comfyui_path / "user" / "default" / "workflows"
        self.cec_workflows = cec_path / "workflows"

        # Ensure directories exist
        self.comfyui_workflows.mkdir(parents=True, exist_ok=True)
        self.cec_workflows.mkdir(parents=True, exist_ok=True)

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

        # Use injected model downloader from workspace
        self.downloader = model_downloader

    @staticmethod
    def _normalize_model_relative_path(relative_path: str) -> str:
        """Normalize and validate a path relative to the configured models directory."""
        normalized = relative_path.replace("\\", "/").strip()
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Model path must be relative to the models directory: {relative_path}")
        return path.as_posix()

    @staticmethod
    def _category_for_indexed_model(model: ModelWithLocation) -> str:
        """Return the manifest category for an indexed model location."""
        if model.category and model.category != "unknown":
            return model.category
        parts = PurePosixPath(model.relative_path.replace("\\", "/")).parts
        if len(parts) > 1 and parts[0]:
            return parts[0]
        return model.category or "unknown"

    @staticmethod
    def _is_manual_workflow_model(model) -> bool:
        """Return whether a workflow model was manually declared outside graph analysis."""
        return getattr(model, "declared_by", None) == "manual" or not getattr(model, "nodes", None)

    @classmethod
    def _manual_workflow_model_key(cls, model) -> tuple[str, str] | None:
        relative_path = getattr(model, "relative_path", None)
        if relative_path:
            return ("path", cls._normalize_model_relative_path(relative_path))
        model_hash = getattr(model, "hash", None)
        if model_hash:
            return ("hash", str(model_hash))
        return None

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
        """Normalize GitHub URLs to registry IDs if they exist in the registry.

        This prevents duplicate entries when users manually enter GitHub URLs
        for packages that exist in the registry.

        Args:
            package_id: Package ID (registry ID or GitHub URL)

        Returns:
            Normalized package ID (registry ID if URL matches, otherwise unchanged)
        """
        installed_id = resolve_installed_node_alias(
            package_id,
            self.pyproject.nodes.get_existing(),
        )
        if installed_id:
            return installed_id

        # Check if it's a GitHub URL
        if is_git_url(package_id):
            # Try to resolve to registry package
            if registry_pkg := self.global_node_resolver.resolve_github_url(package_id):
                return self.node_mapping_repository.canonicalize_package_id(registry_pkg.id) or registry_pkg.id

        # Canonicalize legacy IDs directly
        return self.node_mapping_repository.canonicalize_package_id(package_id) or package_id

    def _get_consensus_custom_node_map(self, workflow_name: str) -> dict[str, str | bool]:
        """Return unambiguous custom node mappings learned from other workflows."""
        workflows = self.pyproject.workflows.get_all_with_resolutions()
        installed_nodes = self.pyproject.nodes.get_existing()
        candidates: dict[str, set[str | bool]] = {}

        for other_name, workflow_data in workflows.items():
            if other_name == workflow_name:
                continue

            custom_map = workflow_data.get("custom_node_map", {})
            if not isinstance(custom_map, Mapping):
                continue

            for node_type, package_id in custom_map.items():
                if isinstance(package_id, bool):
                    normalized: str | bool = package_id
                elif isinstance(package_id, str):
                    normalized = self._normalize_package_id(package_id)
                    if not resolve_installed_node_alias(normalized, installed_nodes):
                        continue
                else:
                    continue

                candidates.setdefault(str(node_type), set()).add(normalized)

        return {
            node_type: next(iter(package_ids))
            for node_type, package_ids in candidates.items()
            if len(package_ids) == 1
        }


    def _write_single_model_resolution(
        self,
        workflow_name: str,
        resolved: ResolvedModel
    ) -> None:
        """Write a single model resolution immediately (progressive mode).

        Builds ManifestWorkflowModel from resolved model and writes to both:
        1. Global models table (if resolved)
        2. Workflow models list (unified)

        Supports download intents (status=unresolved, sources=[URL], relative_path=path).

        Args:
            workflow_name: Workflow being resolved
            resolved: ResolvedModel with reference + resolved model + flags
        """
        from comfygit_core.models.manifest import ManifestModel, ManifestWorkflowModel

        model_ref = resolved.reference
        model = resolved.resolved_model

        # Determine category and criticality
        category = self._get_category_for_node_ref(model_ref)

        # Override criticality if marked optional
        if resolved.is_optional:
            criticality = "optional"
        else:
            criticality = self._get_default_criticality(category)

        # NEW: Handle download intent case (both from pyproject and from node properties)
        if resolved.match_type in ("download_intent", "property_download_intent"):
            manifest_model = ManifestWorkflowModel(
                filename=model_ref.widget_value,
                category=category,
                criticality=criticality,
                status="unresolved",  # No hash yet
                nodes=[model_ref],
                sources=[resolved.model_source] if resolved.model_source else [],  # URL
                relative_path=resolved.target_path.as_posix() if resolved.target_path else None  # Target path
            )
            self.pyproject.workflows.add_workflow_model(workflow_name, manifest_model)

            # Invalidate cache so download intent is detected on next resolution
            self.workflow_cache.invalidate(
                env_name=self.environment_name,
                workflow_name=workflow_name
            )

            return

        # Build manifest model
        if model is None:
            # Model without hash - always unresolved (even if optional)
            # Optional means "workflow works without it", not "resolved"
            manifest_model = ManifestWorkflowModel(
                filename=model_ref.widget_value,
                category=category,
                criticality=criticality,
                status="unresolved",
                nodes=[model_ref],
                sources=[]
            )
        else:
            # Resolved model - fetch sources from repository
            sources = []
            if model.hash:
                sources_from_repo = self.model_repository.get_sources(model.hash)
                sources = [s['url'] for s in sources_from_repo]

            manifest_model = ManifestWorkflowModel(
                hash=model.hash,
                filename=model.filename,
                category=category,
                criticality=criticality,
                status="resolved",
                nodes=[model_ref],
                sources=sources
            )

            # Add to global table with sources
            global_model = ManifestModel(
                hash=model.hash,
                filename=model.filename,
                size=model.file_size,
                relative_path=model.relative_path,
                category=category,
                sources=sources
            )
            self.pyproject.models.add_model(global_model)

        # Progressive write to workflow
        self.pyproject.workflows.add_workflow_model(workflow_name, manifest_model)

        # NOTE: Workflow JSON path update moved to batch operation at end of fix_resolution()
        # Progressive JSON updates fail when cache has stale node IDs (node lookup mismatch)
        # Batch update is more efficient and ensures consistent node IDs within same parse session

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
        from comfygit_core.models.manifest import ManifestModel, ManifestWorkflowModel

        # Use primary ref for category determination
        primary_ref = resolved.reference
        model = resolved.resolved_model

        # Determine category and criticality
        category = self._get_category_for_node_ref(primary_ref)

        # Override criticality if marked optional
        if resolved.is_optional:
            criticality = "optional"
        else:
            criticality = self._get_default_criticality(category)

        # Handle download intent case (both from pyproject and from node properties)
        if resolved.match_type in ("download_intent", "property_download_intent"):
            manifest_model = ManifestWorkflowModel(
                filename=primary_ref.widget_value,
                category=category,
                criticality=criticality,
                status="unresolved",
                nodes=all_refs,  # ALL REFS!
                sources=[resolved.model_source] if resolved.model_source else [],
                relative_path=resolved.target_path.as_posix() if resolved.target_path else None
            )
            self.pyproject.workflows.add_workflow_model(workflow_name, manifest_model)

            # Invalidate cache
            self.workflow_cache.invalidate(
                env_name=self.environment_name,
                workflow_name=workflow_name
            )
            return

        # Build manifest model
        if model is None:
            # Model without hash - unresolved
            manifest_model = ManifestWorkflowModel(
                filename=primary_ref.widget_value,
                category=category,
                criticality=criticality,
                status="unresolved",
                nodes=all_refs,  # ALL REFS!
                sources=[]
            )
        else:
            # Resolved model - fetch sources from repository
            sources = []
            if model.hash:
                sources_from_repo = self.model_repository.get_sources(model.hash)
                sources = [s['url'] for s in sources_from_repo]

            manifest_model = ManifestWorkflowModel(
                hash=model.hash,
                filename=model.filename,
                category=category,
                criticality=criticality,
                status="resolved",
                nodes=all_refs,  # ALL REFS!
                sources=sources
            )

            # Add to global table with sources
            global_model = ManifestModel(
                hash=model.hash,
                filename=model.filename,
                size=model.file_size,
                relative_path=model.relative_path,
                category=category,
                sources=sources
            )
            self.pyproject.models.add_model(global_model)

        # Progressive write to workflow
        self.pyproject.workflows.add_workflow_model(workflow_name, manifest_model)

        # Log grouped write
        if len(all_refs) > 1:
            node_ids = ", ".join(f"#{ref.node_id}" for ref in all_refs)
            logger.debug(f"Wrote grouped model resolution for nodes: {node_ids}")

    def _update_single_workflow_node_path(
        self,
        workflow_name: str,
        model_ref: WorkflowNodeWidgetRef,
        model: ModelWithLocation
    ) -> None:
        """Update a single node's widget value in workflow JSON.

        Args:
            workflow_name: Workflow name
            model_ref: Node widget reference
            model: Resolved model with path
        """
        workflow_path = self.comfyui_workflows / f"{workflow_name}.json"
        if not workflow_path.exists():
            return

        workflow = WorkflowRepository.load(workflow_path)

        if model_ref.node_id in workflow.nodes:
            node = workflow.nodes[model_ref.node_id]
            if model_ref.widget_index < len(node.widgets_values):
                display_path = self._strip_base_directory_for_node(
                    model_ref.node_type,
                    model.relative_path
                )
                node.widgets_values[model_ref.widget_index] = display_path
                WorkflowRepository.save(workflow, workflow_path)

                # Invalidate cache since workflow content changed
                self.workflow_cache.invalidate(
                    env_name=self.environment_name,
                    workflow_name=workflow_name
                )

                logger.debug(f"Updated workflow JSON node {model_ref.node_id}")

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
        node_package_id = self._normalize_package_id(node_package_id)

        # Get existing workflow node packages from pyproject
        workflows_config = self.pyproject.workflows.get_all_with_resolutions()
        workflow_config = workflows_config.get(workflow_name, {})
        existing_nodes = set(workflow_config.get('nodes', []))

        # Add new package (set handles deduplication)
        existing_nodes.add(node_package_id)

        # Write back to pyproject
        self.pyproject.workflows.set_node_packs(workflow_name, existing_nodes)
        logger.debug(f"Added {node_package_id} to workflow '{workflow_name}' nodes")

    def get_workflow_path(self, name: str) -> Path:
        """Check if workflow exists in ComfyUI directory and return path.

        Args:
            name: Workflow name

        Returns:
            Path to workflow file if it exists

        Raises:
            FileNotFoundError
        """
        workflow_path = self.comfyui_workflows / f"{name}.json"
        if workflow_path.exists():
            return workflow_path
        else:
            raise FileNotFoundError(f"Workflow '{name}' not found in ComfyUI directory")

    def get_workflow_sync_status(self) -> WorkflowSyncStatus:
        """Get file-level sync status between ComfyUI and .cec.

        Returns:
            WorkflowSyncStatus with categorized workflow lists
        """
        # Get all workflows from ComfyUI
        comfyui_workflows = set()
        if self.comfyui_workflows.exists():
            for workflow_file in self.comfyui_workflows.glob("*.json"):
                comfyui_workflows.add(workflow_file.stem)

        # Get all workflows from .cec
        cec_workflows = set()
        if self.cec_workflows.exists():
            for workflow_file in self.cec_workflows.glob("*.json"):
                cec_workflows.add(workflow_file.stem)

        # Categorize workflows
        new_workflows = []
        modified_workflows = []
        deleted_workflows = []
        synced_workflows = []

        # Check each ComfyUI workflow
        for name in comfyui_workflows:
            if name not in cec_workflows:
                new_workflows.append(name)
            else:
                # Compare contents to detect modifications
                if self._workflows_differ(name):
                    modified_workflows.append(name)
                else:
                    synced_workflows.append(name)

        # Check for deleted workflows (in .cec but not ComfyUI)
        for name in cec_workflows:
            if name not in comfyui_workflows:
                deleted_workflows.append(name)

        return WorkflowSyncStatus(
            new=sorted(new_workflows),
            modified=sorted(modified_workflows),
            deleted=sorted(deleted_workflows),
            synced=sorted(synced_workflows),
        )

    def _workflows_differ(self, name: str) -> bool:
        """Check if workflow differs between ComfyUI and .cec.

        Args:
            name: Workflow name

        Returns:
            True if workflows differ or .cec copy doesn't exist
        """
        # TODO: This will fail if workflow is in a subdirectory in ComfyUI
        comfyui_file = self.comfyui_workflows / f"{name}.json"
        cec_file = self.cec_workflows / f"{name}.json"

        if not cec_file.exists():
            return True

        if not comfyui_file.exists():
            return False

        try:
            # Compare file contents, ignoring volatile metadata fields
            with open(comfyui_file, encoding='utf-8') as f:
                comfyui_content = json.load(f)
            with open(cec_file, encoding='utf-8') as f:
                cec_content = json.load(f)

            # Normalize by removing volatile fields that change between saves
            comfyui_normalized = normalize_workflow(comfyui_content)
            cec_normalized = normalize_workflow(cec_content)

            return comfyui_normalized != cec_normalized
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Error comparing workflows '{name}': {e}")
            return True

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
            config = self.pyproject.load()

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
        if config is None:
            config = self.pyproject.load()

        workflow_api_dir = self.cec_path / "workflow_api"
        if not workflow_api_dir.exists():
            return 0

        referenced = self._referenced_workflow_api_prompt_files(config)
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

    def copy_all_workflows(self) -> dict[str, Path | None]:
        """Copy ALL workflows from ComfyUI to .cec for commit.

        Returns:
            Dictionary of workflow names to Path
        """
        results = {}

        if not self.comfyui_workflows.exists():
            logger.info("No ComfyUI workflows directory found")
            return results

        # Copy every workflow from ComfyUI to .cec
        for workflow_file in self.comfyui_workflows.glob("*.json"):
            name = workflow_file.stem
            source = self.comfyui_workflows / f"{name}.json"
            dest = self.cec_workflows / f"{name}.json"

            # Check if workflow was actually modified (not just UI changes)
            was_modified = self._workflows_differ(name)

            try:
                shutil.copy2(source, dest)
                results[name] = dest
                logger.debug(f"Copied workflow '{name}' to .cec")

                # Invalidate cache for truly modified workflows
                if was_modified:
                    self.workflow_cache.invalidate(
                        env_name=self.environment_name,
                        workflow_name=name
                    )
                    logger.debug(f"Invalidated cache for modified workflow '{name}'")

            except Exception as e:
                results[name] = None
                logger.error(f"Failed to copy workflow '{name}': {e}")

        # Remove workflows from .cec that no longer exist in ComfyUI
        if self.cec_workflows.exists():
            comfyui_names = {f.stem for f in self.comfyui_workflows.glob("*.json")}
            for cec_file in self.cec_workflows.glob("*.json"):
                name = cec_file.stem
                if name not in comfyui_names:
                    try:
                        cec_file.unlink()
                        results[name] = "deleted"

                        # Invalidate cache for deleted workflows
                        self.workflow_cache.invalidate(
                            env_name=self.environment_name,
                            workflow_name=name
                        )
                        logger.debug(
                            f"Deleted workflow '{name}' from .cec (no longer in ComfyUI)"
                        )
                    except Exception as e:
                        logger.error(f"Failed to delete workflow '{name}': {e}")

        return results

    def restore_from_cec(self, name: str) -> bool:
        """Restore a workflow from .cec to ComfyUI directory.

        Args:
            name: Workflow name

        Returns:
            True if successful, False if workflow not found
        """
        source = self.cec_workflows / f"{name}.json"
        dest = self.comfyui_workflows / f"{name}.json"

        if not source.exists():
            return False

        try:
            shutil.copy2(source, dest)
            logger.info(f"Restored workflow '{name}' to ComfyUI")
            return True
        except Exception as e:
            logger.error(f"Failed to restore workflow '{name}': {e}")
            return False

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
        results = {}

        # Phase 1: Restore workflows that exist in .cec
        if self.cec_workflows.exists():
            # Get uncommitted workflows if we need to preserve them
            uncommitted_workflows = set()
            if preserve_uncommitted:
                status = self.get_workflow_sync_status()
                uncommitted_workflows = set(status.new + status.modified)

            # Copy workflows from .cec to ComfyUI (skip uncommitted if preserving)
            for workflow_file in self.cec_workflows.glob("*.json"):
                name = workflow_file.stem

                # Skip if this workflow has uncommitted changes and we're preserving
                if preserve_uncommitted and name in uncommitted_workflows:
                    results[name] = "preserved"
                    logger.debug(f"Preserved uncommitted changes to workflow '{name}'")
                    continue

                if self.restore_from_cec(name):
                    results[name] = "restored"
                else:
                    results[name] = "failed"

        # Phase 2: Cleanup (ALWAYS run, even if .cec/workflows/ doesn't exist!)
        # This ensures git semantics: switching to branch without workflows deletes them
        if not preserve_uncommitted and self.comfyui_workflows.exists():
            # Determine what workflows SHOULD exist
            if self.cec_workflows.exists():
                cec_names = {f.stem for f in self.cec_workflows.glob("*.json")}
            else:
                # No .cec/workflows/ directory = no workflows should exist
                # This happens when switching to branches that never had workflows committed
                cec_names = set()

            # Remove workflows that shouldn't exist
            for comfyui_file in self.comfyui_workflows.glob("*.json"):
                name = comfyui_file.stem
                if name not in cec_names:
                    try:
                        comfyui_file.unlink()
                        results[name] = "removed"
                        logger.debug(
                            f"Removed workflow '{name}' from ComfyUI (not in .cec)"
                        )
                    except Exception as e:
                        logger.error(f"Failed to remove workflow '{name}': {e}")

        return results

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
        workflow_path = self.get_workflow_path(name)

        # Check cache first
        cached = self.workflow_cache.get(
            env_name=self.environment_name,
            workflow_name=name,
            workflow_path=workflow_path,
            pyproject_path=self.pyproject.path
        )

        if cached is not None:
            logger.debug(f"Cache HIT for workflow '{name}'")
            return cached.dependencies

        logger.debug(f"Cache MISS for workflow '{name}' - running full analysis")

        # Cache miss - run full analysis
        parser = WorkflowDependencyParser(
            workflow_path,
            cec_path=self.cec_path,
            builtin_versions_repository=self.builtin_versions_repository,
        )
        deps = parser.analyze_dependencies()

        # Store in cache (no resolution yet)
        self.workflow_cache.set(
            env_name=self.environment_name,
            workflow_name=name,
            workflow_path=workflow_path,
            dependencies=deps,
            resolution=None,
            pyproject_path=self.pyproject.path
        )

        return deps

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
        workflow_path = self.get_workflow_path(name)

        # Check cache
        cached = self.workflow_cache.get(
            env_name=self.environment_name,
            workflow_name=name,
            workflow_path=workflow_path,
            pyproject_path=self.pyproject.path
        )

        if cached and not cached.needs_reresolution and cached.resolution:
            # Full cache hit - both analysis and resolution valid
            logger.debug(f"Cache HIT (full) for workflow '{name}'")
            return (cached.dependencies, cached.resolution)

        if cached and cached.needs_reresolution:
            # Partial hit - workflow content valid but resolution stale
            logger.debug(f"Cache PARTIAL HIT for workflow '{name}' - re-resolving")
            dependencies = cached.dependencies
        else:
            # Full miss - analyze workflow
            logger.debug(f"Cache MISS for workflow '{name}' - full analysis + resolution")
            parser = WorkflowDependencyParser(
                workflow_path,
                cec_path=self.cec_path,
                builtin_versions_repository=self.builtin_versions_repository,
            )
            dependencies = parser.analyze_dependencies()

        # Resolve (either from cache miss or stale resolution)
        resolution = self.resolve_workflow(dependencies)

        # Cache both analysis and resolution
        self.workflow_cache.set(
            env_name=self.environment_name,
            workflow_name=name,
            workflow_path=workflow_path,
            dependencies=dependencies,
            resolution=resolution,
            pyproject_path=self.pyproject.path
        )

        return (dependencies, resolution)

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
        workflow_name = analysis.workflow_name
        previous_resolutions = {}
        workflow_models = self.pyproject.workflows.get_workflow_models(workflow_name)
        for manifest_model in workflow_models:
            for ref in manifest_model.nodes:
                previous_resolutions[ref] = manifest_model

        global_models_dict = {}
        try:
            all_global_models = self.pyproject.models.get_all()
            for model in all_global_models:
                global_models_dict[model.hash] = model
        except Exception as e:
            logger.warning(f"Failed to load global models table: {e}")

        current_custom_map = self.pyproject.workflows.get_custom_node_map(workflow_name)
        consensus_custom_map = self._get_consensus_custom_node_map(workflow_name)

        context = ResolutionContext(
            installed_packages=self.pyproject.nodes.get_existing(),
            custom_node_mappings={**consensus_custom_map, **current_custom_map},
            previous_model_resolutions=previous_resolutions,
            global_models=global_models_dict,
            cec_path=getattr(self, "cec_path", None),
            builtin_versions_repository=self.builtin_versions_repository,
            workflow_name=workflow_name,
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
        for resolved_model in resolution.models_resolved:
            if resolved_model.resolved_model:
                resolved_model.needs_path_sync = self._check_path_needs_sync(resolved_model)
                has_mismatch, expected, actual = self._check_category_mismatch(resolved_model)
                resolved_model.has_category_mismatch = has_mismatch
                resolved_model.expected_categories = expected
                resolved_model.actual_category = actual

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
            for (widget_value, node_type), group in model_groups.items():
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
        from comfygit_core.models.manifest import ManifestModel, ManifestWorkflowModel

        is_batch = config is not None
        if not is_batch:
            config = self.pyproject.load()

        workflow_name = resolution.workflow_name

        # Phase 1: Reconcile nodes (unchanged)
        target_node_pack_ids = set()
        target_node_types = set()

        for pkg in resolution.nodes_resolved:
            if pkg.is_optional:
                target_node_types.add(pkg.node_type)
            elif pkg.package_id is not None:
                normalized_id = self._normalize_package_id(pkg.package_id)
                target_node_pack_ids.add(normalized_id)
                target_node_types.add(pkg.node_type)

        for node in resolution.nodes_unresolved:
            target_node_types.add(node.type)
        for node in resolution.nodes_version_gated:
            target_node_types.add(node.type)
        for pkg in resolution.nodes_uninstallable:
            target_node_types.add(pkg.node_type)
        for packages in resolution.nodes_ambiguous:
            if packages:
                target_node_types.add(packages[0].node_type)

        if target_node_pack_ids:
            self.pyproject.workflows.set_node_packs(workflow_name, target_node_pack_ids, config=config)
        else:
            self.pyproject.workflows.set_node_packs(workflow_name, None, config=config)

        # Reconcile custom_node_map
        existing_custom_map = self.pyproject.workflows.get_custom_node_map(workflow_name, config=config)
        for node_type in list(existing_custom_map.keys()):
            if node_type not in target_node_types:
                self.pyproject.workflows.remove_custom_node_mapping(workflow_name, node_type, config=config)

        existing_workflow_models = self.pyproject.workflows.get_workflow_models(workflow_name, config=config)
        manual_workflow_models = [
            model for model in existing_workflow_models
            if self._is_manual_workflow_model(model)
        ]

        # Phase 2: Build ManifestWorkflowModel entries with smart defaults
        manifest_models: list[ManifestWorkflowModel] = []

        # Group resolved models by hash
        hash_to_refs: dict[str, list[WorkflowNodeWidgetRef]] = {}
        for resolved in resolution.models_resolved:
            if resolved.resolved_model:
                model_hash = resolved.resolved_model.hash
                if model_hash not in hash_to_refs:
                    hash_to_refs[model_hash] = []
                hash_to_refs[model_hash].append(resolved.reference)
            elif resolved.match_type in ("download_intent", "property_download_intent"):
                # Download intent (from pyproject or node properties) - preserve it in manifest
                category = self._get_category_for_node_ref(resolved.reference)
                manifest_model = ManifestWorkflowModel(
                    filename=resolved.reference.widget_value,
                    category=category,
                    criticality="flexible",
                    status="unresolved",
                    nodes=[resolved.reference],
                    sources=[resolved.model_source] if resolved.model_source else [],
                    relative_path=resolved.target_path.as_posix() if resolved.target_path else None
                )
                manifest_models.append(manifest_model)
            elif resolved.is_optional:
                # Type C: Optional unresolved (user marked as optional, no model data)
                category = self._get_category_for_node_ref(resolved.reference)
                manifest_model = ManifestWorkflowModel(
                    filename=resolved.reference.widget_value,
                    category=category,
                    criticality="optional",
                    status="unresolved",
                    nodes=[resolved.reference],
                    sources=[]
                )
                manifest_models.append(manifest_model)

        # Create manifest entries for resolved models
        for model_hash, refs in hash_to_refs.items():
            # Get model from first resolved entry
            model = next(
                (r.resolved_model for r in resolution.models_resolved if r.resolved_model and r.resolved_model.hash == model_hash),
                None
            )
            if not model:
                continue

            # Determine criticality with smart defaults
            criticality = self._get_default_criticality(model.category)

            # Fetch sources from repository to enrich global table
            sources_from_repo = self.model_repository.get_sources(model.hash)
            sources = [s['url'] for s in sources_from_repo]

            # Workflow model: lightweight reference (no sources - hash is the key)
            manifest_model = ManifestWorkflowModel(
                hash=model.hash,
                filename=model.filename,
                category=model.category,
                criticality=criticality,
                status="resolved",
                nodes=refs,
                sources=[]  # Empty - sources stored in global table only
            )
            manifest_models.append(manifest_model)

            # Global table: enrich with sources from SQLite
            global_model = ManifestModel(
                hash=model.hash,
                filename=model.filename,
                size=model.file_size,
                relative_path=model.relative_path,
                category=model.category,
                sources=sources  # From SQLite - authoritative source
            )
            self.pyproject.models.add_model(global_model, config=config)

        existing_by_filename = {m.filename: m for m in existing_workflow_models}

        # Add unresolved models
        for ref in resolution.models_unresolved:
            category = self._get_category_for_node_ref(ref)
            criticality = self._get_default_criticality(category)

            # Check if this model already has a download intent from a previous session
            existing = existing_by_filename.get(ref.widget_value)
            sources = []
            relative_path = None
            if existing and existing.status == "unresolved" and existing.sources:
                # Preserve download intent from previous session
                sources = existing.sources
                relative_path = existing.relative_path
                logger.debug(f"Preserving download intent for '{ref.widget_value}': sources={sources}, path={relative_path}")

            manifest_model = ManifestWorkflowModel(
                filename=ref.widget_value,
                category=category,
                criticality=criticality,
                status="unresolved",
                nodes=[ref],
                sources=sources,
                relative_path=relative_path
            )
            manifest_models.append(manifest_model)

        existing_keys = {
            self._manual_workflow_model_key(model)
            for model in manifest_models
            if self._manual_workflow_model_key(model) is not None
        }
        for manual_model in manual_workflow_models:
            manual_key = self._manual_workflow_model_key(manual_model)
            if manual_key is None or manual_key in existing_keys:
                continue
            manifest_models.append(manual_model)
            existing_keys.add(manual_key)

        # Write all models to workflow
        self.pyproject.workflows.set_workflow_models(workflow_name, manifest_models, config=config)

        # Clean up workflows deleted from ComfyUI, including their now-unreferenced
        # workflow API prompt artifacts.
        self.cleanup_orphaned_workflow_state(config=config)

        # Clean up orphaned models (must run AFTER workflow sections are removed)
        self.pyproject.models.cleanup_orphans(config=config)

        # Save if not in batch mode
        if not is_batch:
            self.pyproject.save(config)

        # Phase 3: Update workflow JSON with resolved paths
        self.update_workflow_model_paths(resolution)

    def update_workflow_model_paths(
        self,
        resolution: ResolutionResult
    ) -> int:
        """Update workflow JSON files with resolved and stripped model paths.

        IMPORTANT: Only updates paths for BUILTIN ComfyUI nodes. Custom nodes are
        skipped to preserve their original widget values and avoid breaking validation.

        This strips the base directory prefix (e.g., 'checkpoints/') from model paths
        because ComfyUI builtin node loaders automatically prepend their base directories.

        See: docs/knowledge/comfyui-node-loader-base-directories.md for detailed explanation.

        Args:
            resolution: Resolution result with ref→model mapping

        Returns:
            Number of builtin model path widget values updated.

        Raises:
            FileNotFoundError if workflow not found
        """
        workflow_name = resolution.workflow_name

        # Load workflow from ComfyUI directory
        workflow_path = self.get_workflow_path(workflow_name)

        workflow = WorkflowRepository.load(workflow_path)

        updated_count = 0
        skipped_count = 0

        # Update each resolved model's path in the workflow
        for resolved in resolution.models_resolved:
            ref = resolved.reference
            model = resolved.resolved_model

            # Skip if model is None (Type 1 optional unresolved)
            if model is None:
                continue

            node_id = ref.node_id
            widget_idx = ref.widget_index

            # Skip custom nodes - they have undefined path behavior
            if not self.model_resolver.model_config.is_model_loader_node(ref.node_type):
                logger.debug(
                    f"Skipping path update for custom node '{ref.node_type}' "
                    f"(node_id={node_id}, widget={widget_idx}). "
                    f"Custom nodes manage their own model paths."
                )
                skipped_count += 1
                continue

            # Update the node's widget value with resolved path
            if node_id in workflow.nodes:
                node = workflow.nodes[node_id]
                if widget_idx < len(node.widgets_values):
                    old_path = node.widgets_values[widget_idx]
                    # Strip base directory prefix for ComfyUI BUILTIN node loaders
                    # e.g., "checkpoints/sd15/model.ckpt" → "sd15/model.ckpt"
                    display_path = self._strip_base_directory_for_node(ref.node_type, model.relative_path)
                    if old_path == display_path:
                        continue
                    node.widgets_values[widget_idx] = display_path
                    logger.debug(f"Updated node {node_id} widget {widget_idx}: {old_path} → {display_path}")
                    updated_count += 1

        # Only save if we actually updated something
        if updated_count > 0:
            WorkflowRepository.save(workflow, workflow_path)

            # Invalidate cache since workflow content changed
            self.workflow_cache.invalidate(
                env_name=self.environment_name,
                workflow_name=workflow_name
            )

            logger.info(
                f"Updated workflow JSON: {workflow_path} "
                f"({updated_count} builtin nodes updated, {skipped_count} custom nodes preserved)"
            )
        else:
            logger.debug(f"No path updates needed for workflow '{workflow_name}'")

        # Note: We intentionally do NOT update .cec here
        # The .cec copy represents "committed state" and should only be updated during commit
        # This ensures workflow status correctly shows as "new" or "modified" until committed
        return updated_count

    def _get_default_criticality(self, category: str) -> str:
        """Determine smart default criticality based on model category.

        Args:
            category: Model category (checkpoints, loras, etc.)

        Returns:
            Criticality level: "required", "flexible", or "optional"
        """
        return CATEGORY_CRITICALITY_DEFAULTS.get(category, "required")

    def _get_category_for_node_ref(self, node_ref: WorkflowNodeWidgetRef) -> str:
        """Get model category from node type.

        Args:
            node_type: ComfyUI node type

        Returns:
            Model category string
        """
        # First see if node type is explicitly mapped to a category.
        node_type = node_ref.node_type
        directories = self.model_resolver.model_config.get_directories_for_node(node_type)
        if directories:
            logger.debug(f"Found directory mapping for node type '{node_type}': {directories}")
            return directories[0]  # Use first directory as category

        # Next check if widget value path can be converted to category:
        from ..utils.model_categories import get_model_category
        category = get_model_category(node_ref.widget_value)
        logger.debug(f"Found directory mapping for widget value '{node_ref.widget_value}': {category}")
        return category

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
        ref = resolved.reference
        model = resolved.resolved_model

        # Only check builtin nodes (custom nodes manage their own paths)
        if not self.model_resolver.model_config.is_model_loader_node(ref.node_type):
            return False

        # Can't sync if model didn't resolve
        if not model:
            return False

        # Get expected path after stripping base directory (already normalized to forward slashes)
        expected_path = self._strip_base_directory_for_node(
            ref.node_type,
            model.relative_path
        )

        # Normalize current path for comparison (handles Windows backslashes)
        current_path = ref.widget_value.replace('\\', '/')

        # If paths differ, check if current path exists with same hash (duplicate models)
        if current_path != expected_path:
            # Try to find the current path in model repository
            # For builtin loaders, we need to reconstruct the full path
            all_models = self.model_repository.get_all_models()

            # Try exact match with current path
            current_matches = self.model_resolver._try_exact_match(current_path, all_models)

            # If not found, try reconstructing the path (for builtin loaders)
            if not current_matches and self.model_resolver.model_config.is_model_loader_node(ref.node_type):
                reconstructed_paths = self.model_resolver.model_config.reconstruct_model_path(
                    ref.node_type, current_path
                )
                for path in reconstructed_paths:
                    current_matches = self.model_resolver._try_exact_match(path, all_models)
                    if current_matches:
                        break

            # If current path exists and has same hash as resolved model, no sync needed
            if current_matches and current_matches[0].hash == model.hash:
                return False

        # Return True if paths differ and current path is invalid or has different hash
        return current_path != expected_path

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
        ref = resolved.reference
        model = resolved.resolved_model

        # Skip if no resolved model (nothing to check)
        if not model:
            return (False, [], None)

        # Skip custom nodes - we don't know what paths they scan
        if not self.model_resolver.model_config.is_model_loader_node(ref.node_type):
            return (False, [], None)

        # Get expected directories for this node type
        expected_dirs = self.model_resolver.model_config.get_directories_for_node(ref.node_type)
        if not expected_dirs:
            return (False, [], None)

        # Extract actual category from resolved model path (first path component)
        path_parts = model.relative_path.replace('\\', '/').split('/')
        actual_category = path_parts[0] if path_parts else None

        # If resolved location is in expected directory, no mismatch
        if actual_category in expected_dirs:
            return (False, expected_dirs, actual_category)

        # Resolved location is wrong, but check if model exists in ANY valid location
        # This handles the case where user copied (not moved) the model
        all_locations = self.model_repository.get_locations(model.hash)
        for location in all_locations:
            loc_path_parts = location['relative_path'].replace('\\', '/').split('/')
            loc_category = loc_path_parts[0] if loc_path_parts else None
            if loc_category in expected_dirs:
                # Model exists in a valid location - no functional mismatch
                return (False, expected_dirs, actual_category)

        # No location in expected directory - this is a real mismatch
        return (True, expected_dirs, actual_category)

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
        # Normalize to forward slashes for cross-platform compatibility (Windows uses backslashes)
        relative_path = relative_path.replace('\\', '/')

        # Use model_config from model_resolver (includes dynamic folder mappings from cec_path)
        base_dirs = self.model_resolver.model_config.get_directories_for_node(node_type)

        # Warn if called for custom node (should be skipped in caller)
        if not base_dirs:
            logger.warning(
                f"_strip_base_directory_for_node called for unknown/custom node type: {node_type}. "
                f"Custom nodes should skip path updates entirely. Returning path unchanged."
            )
            return relative_path

        for base_dir in base_dirs:
            prefix = base_dir + "/"
            if relative_path.startswith(prefix):
                # Strip the base directory but preserve subdirectories
                return relative_path[len(prefix):]

        # Path doesn't have expected prefix - return unchanged
        return relative_path

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
        for idx, model in matches:
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
