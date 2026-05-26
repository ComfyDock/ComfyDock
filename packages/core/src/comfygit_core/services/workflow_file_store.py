"""Workflow file storage and sync helpers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Protocol

from ..logging.logging_config import get_logger
from ..models.workflow import WorkflowSyncStatus
from ..utils.workflow_hash import normalize_workflow

logger = get_logger(__name__)


class WorkflowCacheInvalidator(Protocol):
    """Minimal cache invalidation protocol used by workflow file operations."""

    def invalidate(self, *, env_name: str, workflow_name: str) -> None:
        """Invalidate cached workflow analysis for one environment workflow."""


class WorkflowFileStore:
    """Owns workflow JSON files in ComfyUI and tracked `.cec` storage."""

    def __init__(
        self,
        comfyui_path: Path,
        cec_path: Path,
        *,
        environment_name: str,
        workflow_cache: WorkflowCacheInvalidator | None = None,
    ) -> None:
        self.comfyui_path = comfyui_path
        self.cec_path = cec_path
        self.environment_name = environment_name
        self.workflow_cache = workflow_cache

        self.comfyui_workflows = comfyui_path / "user" / "default" / "workflows"
        self.cec_workflows = cec_path / "workflows"

        self.comfyui_workflows.mkdir(parents=True, exist_ok=True)
        self.cec_workflows.mkdir(parents=True, exist_ok=True)

    def workflow_path(self, name: str) -> Path:
        """Return the expected ComfyUI workflow path without checking existence."""
        return self.comfyui_workflows / f"{name}.json"

    def get_workflow_path(self, name: str) -> Path:
        """Return an existing ComfyUI workflow path."""
        workflow_path = self.workflow_path(name)
        if workflow_path.exists():
            return workflow_path
        raise FileNotFoundError(f"Workflow '{name}' not found in ComfyUI directory")

    def get_workflow_sync_status(self) -> WorkflowSyncStatus:
        """Get file-level sync status between ComfyUI and `.cec`."""
        comfyui_workflows = set()
        if self.comfyui_workflows.exists():
            for workflow_file in self.comfyui_workflows.glob("*.json"):
                comfyui_workflows.add(workflow_file.stem)

        cec_workflows = set()
        if self.cec_workflows.exists():
            for workflow_file in self.cec_workflows.glob("*.json"):
                cec_workflows.add(workflow_file.stem)

        new_workflows = []
        modified_workflows = []
        deleted_workflows = []
        synced_workflows = []

        for name in comfyui_workflows:
            if name not in cec_workflows:
                new_workflows.append(name)
            elif self.workflows_differ(name):
                modified_workflows.append(name)
            else:
                synced_workflows.append(name)

        for name in cec_workflows:
            if name not in comfyui_workflows:
                deleted_workflows.append(name)

        return WorkflowSyncStatus(
            new=sorted(new_workflows),
            modified=sorted(modified_workflows),
            deleted=sorted(deleted_workflows),
            synced=sorted(synced_workflows),
        )

    def workflows_differ(self, name: str) -> bool:
        """Return whether a workflow differs between ComfyUI and `.cec`."""
        # TODO: This will fail if workflow is in a subdirectory in ComfyUI.
        comfyui_file = self.comfyui_workflows / f"{name}.json"
        cec_file = self.cec_workflows / f"{name}.json"

        if not cec_file.exists():
            return True

        if not comfyui_file.exists():
            return False

        try:
            with open(comfyui_file, encoding="utf-8") as f:
                comfyui_content = json.load(f)
            with open(cec_file, encoding="utf-8") as f:
                cec_content = json.load(f)

            return normalize_workflow(comfyui_content) != normalize_workflow(cec_content)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Error comparing workflows '{name}': {e}")
            return True

    def copy_all_workflows(self) -> dict[str, Path | str | None]:
        """Copy all ComfyUI workflow files into tracked `.cec` storage."""
        results: dict[str, Path | str | None] = {}

        if not self.comfyui_workflows.exists():
            logger.info("No ComfyUI workflows directory found")
            return results

        for workflow_file in self.comfyui_workflows.glob("*.json"):
            name = workflow_file.stem
            source = self.comfyui_workflows / f"{name}.json"
            dest = self.cec_workflows / f"{name}.json"
            was_modified = self.workflows_differ(name)

            try:
                shutil.copy2(source, dest)
                results[name] = dest
                logger.debug(f"Copied workflow '{name}' to .cec")

                if was_modified:
                    self._invalidate(name)
                    logger.debug(f"Invalidated cache for modified workflow '{name}'")
            except Exception as e:
                results[name] = None
                logger.error(f"Failed to copy workflow '{name}': {e}")

        if self.cec_workflows.exists():
            comfyui_names = {f.stem for f in self.comfyui_workflows.glob("*.json")}
            for cec_file in self.cec_workflows.glob("*.json"):
                name = cec_file.stem
                if name in comfyui_names:
                    continue
                try:
                    cec_file.unlink()
                    results[name] = "deleted"
                    self._invalidate(name)
                    logger.debug(
                        f"Deleted workflow '{name}' from .cec (no longer in ComfyUI)"
                    )
                except Exception as e:
                    logger.error(f"Failed to delete workflow '{name}': {e}")

        return results

    def restore_from_cec(self, name: str) -> bool:
        """Restore one tracked workflow from `.cec` into ComfyUI."""
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
        """Restore tracked `.cec` workflows into ComfyUI."""
        results: dict[str, str] = {}

        if self.cec_workflows.exists():
            uncommitted_workflows = set()
            if preserve_uncommitted:
                status = self.get_workflow_sync_status()
                uncommitted_workflows = set(status.new + status.modified)

            for workflow_file in self.cec_workflows.glob("*.json"):
                name = workflow_file.stem

                if preserve_uncommitted and name in uncommitted_workflows:
                    results[name] = "preserved"
                    logger.debug(f"Preserved uncommitted changes to workflow '{name}'")
                    continue

                if self.restore_from_cec(name):
                    results[name] = "restored"
                else:
                    results[name] = "failed"

        if not preserve_uncommitted and self.comfyui_workflows.exists():
            if self.cec_workflows.exists():
                cec_names = {f.stem for f in self.cec_workflows.glob("*.json")}
            else:
                cec_names = set()

            for comfyui_file in self.comfyui_workflows.glob("*.json"):
                name = comfyui_file.stem
                if name in cec_names:
                    continue
                try:
                    comfyui_file.unlink()
                    results[name] = "removed"
                    logger.debug(
                        f"Removed workflow '{name}' from ComfyUI (not in .cec)"
                    )
                except Exception as e:
                    logger.error(f"Failed to remove workflow '{name}': {e}")

        return results

    def _invalidate(self, workflow_name: str) -> None:
        if self.workflow_cache is None:
            return
        self.workflow_cache.invalidate(
            env_name=self.environment_name,
            workflow_name=workflow_name,
        )
