"""Generic workspace inventory and model reclaim planning."""

from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from ..models.resource_inventory import (
    EnvironmentDependency,
    EnvironmentInventory,
    ModelDeletionPlan,
    ModelInventoryEntry,
    ModelSource,
    StorageSummary,
    WorkspaceInventory,
)
from ..models.shared import ModelLocation, ModelWithLocation
from ..services.huggingface_url import parse_huggingface_url
from ..utils.environment_cleanup import is_environment_complete
from ..utils.redaction import redact_sensitive_mapping, redact_url

if TYPE_CHECKING:
    from ..core.environment import Environment
    from ..core.workspace import Workspace


_IMMUTABLE_REVISION = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)
_CRITICALITY_ORDER = {"optional": 0, "flexible": 1, "required": 2}


def _directory_size(path: Path) -> int:
    """Return logical file bytes without following directory symlinks."""
    if not path.exists() or path.is_symlink():
        return 0
    total = 0
    for root, directories, files in os.walk(path, followlinks=False):
        directories[:] = [name for name in directories if not (Path(root) / name).is_symlink()]
        for name in files:
            candidate = Path(root) / name
            try:
                if not candidate.is_symlink():
                    total += candidate.stat().st_size
            except OSError:
                continue
    return total


def _source_from_index(source) -> ModelSource:
    metadata = redact_sensitive_mapping(dict(source.metadata))
    parsed = parse_huggingface_url(source.url) if source.type == "huggingface" else None
    revision = parsed.revision if parsed else None
    resolved_revision = metadata.get("resolved_revision")
    if resolved_revision and not _IMMUTABLE_REVISION.fullmatch(str(resolved_revision)):
        resolved_revision = None
    if not resolved_revision and revision and _IMMUTABLE_REVISION.fullmatch(revision):
        resolved_revision = revision
    return ModelSource(
        type=source.type,
        url=redact_url(source.url),
        repo_id=parsed.repo_id if parsed else metadata.get("repo_id"),
        repo_type=metadata.get("repo_type", "model")
        if source.type == "huggingface"
        else metadata.get("repo_type"),
        revision=revision or metadata.get("revision"),
        resolved_revision=str(resolved_revision) if resolved_revision else None,
        path_in_repo=parsed.path_in_repo if parsed else metadata.get("path_in_repo"),
        metadata=metadata,
    )


def _source_from_manifest_url(url: str) -> ModelSource:
    parsed = parse_huggingface_url(url)
    source_type = "huggingface" if parsed.kind != "unknown" else "custom"
    revision = parsed.revision if source_type == "huggingface" else None
    resolved_revision = revision if revision and _IMMUTABLE_REVISION.fullmatch(revision) else None
    return ModelSource(
        type=source_type,
        url=redact_url(url),
        repo_id=parsed.repo_id if source_type == "huggingface" else None,
        repo_type="model" if source_type == "huggingface" else None,
        revision=revision,
        resolved_revision=resolved_revision,
        path_in_repo=parsed.path_in_repo if source_type == "huggingface" else None,
        metadata={"origin": "manifest"},
    )


def _strongest_criticality(left: str, right: str) -> str:
    return left if _CRITICALITY_ORDER.get(left, 0) >= _CRITICALITY_ORDER.get(right, 0) else right


class WorkspaceResourceInventoryService:
    """Derive adapter-safe inventory from public workspace/environment truth."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self._shared_cache_bytes: int | None = None
        self._shared_models_bytes: int | None = None

    def get_inventory(self) -> WorkspaceInventory:
        environments = tuple(
            self.get_environment_inventory(environment)
            for environment in self.workspace.list_environments()
        )
        references, manifest_sources = self._manifest_resource_maps()
        models = self._model_inventory(references, manifest_sources)
        return WorkspaceInventory(
            workspace_path=str(self.workspace.path),
            models_directory=str(self.workspace.get_models_directory()),
            models=models,
            environments=environments,
        )

    def get_environment_inventory(self, environment: Environment) -> EnvironmentInventory:
        snapshot = environment.get_manifest_snapshot()
        manifest_path = environment.get_manifest_path()
        manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

        model_dependencies: dict[tuple[str, str | None], EnvironmentDependency] = {}
        for workflow_name, workflow in snapshot.workflows.items():
            for model in workflow.models:
                identifier = model.hash or model.relative_path or model.filename
                key = (identifier, model.relative_path)
                existing = model_dependencies.get(key)
                workflow_names = set(existing.workflow_names if existing else ())
                workflow_names.add(workflow_name)
                model_dependencies[key] = EnvironmentDependency(
                    kind="model",
                    identifier=identifier,
                    criticality=(
                        _strongest_criticality(existing.criticality, model.criticality)
                        if existing
                        else model.criticality
                    ),
                    workflow_names=tuple(sorted(workflow_names)),
                    content_hash=model.hash,
                    relative_path=model.relative_path,
                    source=model.sources[0] if model.sources else None,
                )

        node_dependencies = tuple(
            EnvironmentDependency(
                kind="custom_node",
                identifier=identifier,
                criticality=node.criticality,
                source=node.repository or node.download_url,
                version=node.version,
                pinned_commit=node.pinned_commit,
            )
            for identifier, node in sorted(snapshot.nodes.items())
        )

        workspace_paths = environment.workspace_paths
        if self._shared_cache_bytes is None:
            self._shared_cache_bytes = _directory_size(workspace_paths.cache) + _directory_size(
                environment.workspace.get_external_uv_cache() or (workspace_paths.root / "uv_cache")
            )
        if self._shared_models_bytes is None:
            self._shared_models_bytes = _directory_size(environment.global_models_path)
        storage = StorageSummary(
            environment_bytes=_directory_size(environment.path),
            venv_bytes=_directory_size(environment.venv_path),
            comfyui_bytes=_directory_size(environment.comfyui_path),
            input_bytes=_directory_size(workspace_paths.input / environment.name),
            output_bytes=_directory_size(workspace_paths.output / environment.name),
            shared_cache_bytes=self._shared_cache_bytes,
            shared_models_bytes=self._shared_models_bytes,
        )
        return EnvironmentInventory(
            name=environment.name,
            path=str(environment.path),
            manifest_path=str(manifest_path),
            manifest_sha256=manifest_sha256,
            complete=is_environment_complete(environment.cec_path),
            comfyui_revision=snapshot.comfyui_version,
            python_version=snapshot.python_version,
            model_dependencies=tuple(
                sorted(
                    model_dependencies.values(),
                    key=lambda item: (item.identifier, item.relative_path or ""),
                )
            ),
            custom_node_dependencies=node_dependencies,
            storage=storage,
        )

    def get_model_inventory(self) -> tuple[ModelInventoryEntry, ...]:
        references, manifest_sources = self._manifest_resource_maps()
        return self._model_inventory(references, manifest_sources)

    def plan_model_deletion(
        self,
        identifier: str,
        *,
        location_id: int | None = None,
        all_locations: bool = False,
    ) -> ModelDeletionPlan:
        if location_id is not None and all_locations:
            raise ValueError("Choose one location or all locations, not both")
        entry = self._resolve_inventory_entry(identifier, self.get_model_inventory())

        selection_explicit = location_id is not None or all_locations
        if location_id is not None:
            targets = tuple(location for location in entry.locations if location.id == location_id)
            if not targets:
                raise KeyError(f"Model location not found: {location_id}")
        else:
            targets = entry.locations
        target_ids = {location.id for location in targets}
        remaining = tuple(location for location in entry.locations if location.id not in target_ids)

        blockers: list[str] = []
        warnings: list[str] = []
        if not selection_explicit:
            blockers.append("explicit_location_selection_required")
        if not targets:
            blockers.append("no_locations_selected")
        if any(not self._location_path_safe(location) for location in targets):
            blockers.append("selected_location_outside_indexed_base")
        changed_locations = [
            location for location in targets if self._location_changed(entry, location)
        ]
        if changed_locations:
            blockers.append("selected_location_changed")

        recovery_complete = entry.has_strong_hash and entry.has_recovery_source
        present_remaining = tuple(
            location for location in remaining if self._location_present(location)
        )
        if not present_remaining and not recovery_complete:
            blockers.append("final_copy_lacks_recovery_proof")
        if len(present_remaining) != len(remaining):
            warnings.append("remaining_index_contains_missing_locations")
        if entry.referencing_environments:
            blockers.append("referenced_by_environments")
        if any(
            source.type == "huggingface" and not source.has_immutable_revision
            for source in entry.sources
        ):
            warnings.append("huggingface_revision_not_immutable")
        warnings.append("potential_reclaim_bytes_is_an_estimate")

        return ModelDeletionPlan(
            model=entry,
            target_locations=targets,
            remaining_locations=remaining,
            potential_reclaim_bytes=self._potential_reclaim_bytes(targets),
            selection_explicit=selection_explicit,
            delete_all_locations=all_locations,
            recovery_complete=recovery_complete,
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _resolve_inventory_entry(
        identifier: str,
        entries: tuple[ModelInventoryEntry, ...],
    ) -> ModelInventoryEntry:
        normalized = identifier.strip()
        hash_query = normalized.lower()
        matches: list[ModelInventoryEntry] = []
        for entry in entries:
            hash_match = any(
                value and value.lower().startswith(hash_query)
                for value in (entry.short_hash, entry.blake3_hash, entry.sha256_hash)
            )
            path_match = any(
                normalized
                in {
                    location.filename,
                    location.relative_path,
                    location.full_path or "",
                }
                for location in entry.locations
            )
            if hash_match or path_match:
                matches.append(entry)
        if not matches:
            raise KeyError(f"Model not found in workspace inventory: {identifier}")
        if len(matches) > 1:
            raise ValueError(
                f"Multiple models found matching '{identifier}': {len(matches)} different models"
            )
        return matches[0]

    def _model_inventory(
        self,
        references: dict[str, set[str]],
        manifest_sources: dict[str, set[str]],
    ) -> tuple[ModelInventoryEntry, ...]:
        indexed = self.workspace.model_repository.get_all_models(base_directory=None)
        by_hash: dict[str, ModelWithLocation] = {}
        for model in indexed:
            by_hash.setdefault(model.hash, model)
        entries: list[ModelInventoryEntry] = []
        for model_hash, model in by_hash.items():
            sources = {
                (source.type, source.url): source
                for source in (
                    _source_from_manifest_url(url)
                    for url in manifest_sources.get(model_hash, set())
                )
            }
            for source in self.workspace.get_model_sources(model_hash):
                parsed_source = _source_from_index(source)
                sources[(parsed_source.type, parsed_source.url)] = parsed_source
            entries.append(
                ModelInventoryEntry(
                    short_hash=model.hash,
                    file_size=model.file_size,
                    category=model.category,
                    blake3_hash=model.blake3_hash,
                    sha256_hash=model.sha256_hash,
                    locations=tuple(self.workspace.get_model_locations(model_hash)),
                    sources=tuple(sorted(sources.values(), key=lambda item: (item.type, item.url))),
                    referencing_environments=tuple(sorted(references.get(model_hash, set()))),
                )
            )
        return tuple(sorted(entries, key=lambda item: (item.category, item.short_hash)))

    def _manifest_resource_maps(self) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        references: dict[str, set[str]] = defaultdict(set)
        sources: dict[str, set[str]] = defaultdict(set)
        for environment in self.workspace.list_environments():
            snapshot = environment.get_manifest_snapshot()
            for model_hash, model in snapshot.models.items():
                references[model_hash].add(environment.name)
                sources[model_hash].update(model.sources)
            for workflow in snapshot.workflows.values():
                for model in workflow.models:
                    if model.hash:
                        references[model.hash].add(environment.name)
                        sources[model.hash].update(model.sources)
        return references, sources

    @staticmethod
    def _location_changed(entry: ModelInventoryEntry, location: ModelLocation) -> bool:
        if not location.full_path:
            return True
        path = Path(location.full_path)
        try:
            stat = path.stat()
        except OSError:
            return False
        return stat.st_size != entry.file_size or abs(stat.st_mtime - location.mtime) > 1.0

    @staticmethod
    def _location_present(location: ModelLocation) -> bool:
        if not location.full_path:
            return False
        path = Path(location.full_path)
        return path.exists() or path.is_symlink()

    @staticmethod
    def _location_path_safe(location: ModelLocation) -> bool:
        if not location.base_directory or not location.relative_path:
            return False
        base = Path(location.base_directory).expanduser().resolve(strict=False)
        target_parent = (base / location.relative_path).parent.resolve(strict=False)
        try:
            target_parent.relative_to(base)
        except ValueError:
            return False
        return True

    @staticmethod
    def _potential_reclaim_bytes(locations: tuple[ModelLocation, ...]) -> int:
        selected_inodes: dict[tuple[int, int], tuple[int, int]] = {}
        for location in locations:
            if not location.full_path:
                continue
            path = Path(location.full_path)
            try:
                stat = path.lstat()
            except OSError:
                continue
            key = (stat.st_dev, stat.st_ino)
            count, blocks = selected_inodes.get(key, (0, stat.st_blocks * 512))
            selected_inodes[key] = (count + 1, blocks if count else stat.st_blocks * 512)

        potential = 0
        for location in locations:
            if not location.full_path:
                continue
            path = Path(location.full_path)
            try:
                stat = path.lstat()
            except OSError:
                continue
            key = (stat.st_dev, stat.st_ino)
            selected_count, blocks = selected_inodes[key]
            if selected_count >= stat.st_nlink:
                potential += blocks
                selected_inodes[key] = (0, 0)
        return potential
