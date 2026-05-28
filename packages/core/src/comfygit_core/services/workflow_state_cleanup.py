"""Workflow manifest and contract artifact cleanup."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, cast

from ..logging.logging_config import get_logger
from .workflow_file_store import WorkflowFileStore

logger = get_logger(__name__)


class ManifestEditProtocol(Protocol):
    """Manifest edit operations needed by workflow cleanup."""

    config: Any

    def mark_changed(self) -> None:
        """Mark the edit transaction dirty."""
        ...


class ManifestEditorProtocol(Protocol):
    """Manifest transaction entry point used by workflow cleanup."""

    def edit(self) -> AbstractContextManager[ManifestEditProtocol, Any]:
        """Open a manifest edit transaction."""
        ...

    def snapshot(self, force_reload: bool = False) -> object:
        """Return a typed manifest snapshot."""
        ...


class WorkflowManifestProtocol(Protocol):
    """Workflow manifest mutations needed by workflow cleanup."""

    def remove_workflows(self, workflow_names: list[str], config: dict | None = None) -> int:
        """Remove workflow entries from the manifest."""
        ...


@dataclass(frozen=True)
class WorkflowCleanupResult:
    """Counts for workflow state removed during cleanup."""

    workflow_entries: int = 0
    api_prompts: int = 0

    def to_dict(self) -> dict[str, int]:
        """Return the legacy dictionary shape used by existing callers."""
        return {
            "workflow_entries": self.workflow_entries,
            "api_prompts": self.api_prompts,
        }


class WorkflowStateCleanup:
    """Prunes workflow manifest entries and unreferenced API prompt artifacts."""

    def __init__(
        self,
        *,
        manifest: ManifestEditorProtocol,
        workflows: WorkflowManifestProtocol,
        workflow_file_store: WorkflowFileStore,
        cec_path: Path,
    ) -> None:
        self.manifest = manifest
        self.workflows = workflows
        self.workflow_file_store = workflow_file_store
        self.cec_path = cec_path

    def cleanup(self, config: dict | None = None) -> WorkflowCleanupResult:
        """Clean manifest workflow orphans and unreferenced workflow API artifacts."""
        if config is None:
            with self.manifest.edit() as edit:
                removed_workflows = self._cleanup_orphaned_workflow_entries_in_config(edit.config)
                removed_api_prompts = self.cleanup_orphaned_workflow_api_prompts(
                    config=edit.config
                )
                if removed_workflows > 0:
                    edit.mark_changed()
                return WorkflowCleanupResult(
                    workflow_entries=removed_workflows,
                    api_prompts=removed_api_prompts,
                )

        removed_workflows = self.cleanup_orphaned_workflow_entries(config=config)
        removed_api_prompts = self.cleanup_orphaned_workflow_api_prompts(config=config)
        return WorkflowCleanupResult(
            workflow_entries=removed_workflows,
            api_prompts=removed_api_prompts,
        )

    def cleanup_orphaned_workflow_entries(self, config: dict | None = None) -> int:
        """Remove manifest workflow entries whose editable workflow file is gone."""
        if config is None:
            with self.manifest.edit() as edit:
                removed_count = self._cleanup_orphaned_workflow_entries_in_config(edit.config)
                if removed_count > 0:
                    edit.mark_changed()
                return removed_count

        return self._cleanup_orphaned_workflow_entries_in_config(config)

    def cleanup_orphaned_workflow_api_prompts(self, config: dict | None = None) -> int:
        """Remove workflow API prompt files not referenced by remaining contracts."""
        workflow_api_dir = self.cec_path / "workflow_api"
        if not workflow_api_dir.exists():
            return 0

        if config is not None:
            referenced = self._referenced_workflow_api_prompt_files(config)
        else:
            referenced = self._referenced_workflow_api_prompt_files_from_snapshot()

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
                self._remove_empty_parent_dirs(api_file.parent, stop_at=workflow_api_dir)
            except OSError as e:
                logger.warning(
                    f"Failed to remove unreferenced workflow API prompt '{rel_path}': {e}"
                )

        return removed_count

    def _cleanup_orphaned_workflow_entries_in_config(self, config: dict) -> int:
        workflows = self._workflow_entries_from_config(config)

        workflows_in_pyproject = set(workflows.keys())
        workflows_in_comfyui = set()
        if self.workflow_file_store.comfyui_workflows.exists():
            workflows_in_comfyui = {
                f.stem for f in self.workflow_file_store.comfyui_workflows.glob("*.json")
            }

        orphaned_workflows = sorted(workflows_in_pyproject - workflows_in_comfyui)
        if not orphaned_workflows:
            return 0

        removed_count = self.workflows.remove_workflows(
            orphaned_workflows,
            config=config,
        )
        if removed_count > 0:
            logger.info(
                f"Cleaned up {removed_count} deleted workflow(s) from pyproject.toml"
            )

        return removed_count

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

    def _referenced_workflow_api_prompt_files_from_snapshot(self) -> set[str]:
        workflows = getattr(self.manifest.snapshot(), "workflows", {})

        referenced: set[str] = set()
        for workflow in workflows.values():
            contract = workflow.execution_contract
            if contract is None:
                continue

            ref = self._normalize_workflow_api_prompt_ref(contract.api_prompt_file)
            if ref:
                referenced.add(ref)

        return referenced

    @staticmethod
    def _remove_empty_parent_dirs(parent: Path, *, stop_at: Path) -> None:
        while parent != stop_at:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
