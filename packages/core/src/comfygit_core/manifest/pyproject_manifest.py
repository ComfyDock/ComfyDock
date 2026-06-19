"""Pyproject-backed manifest domain operations."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import tomlkit

from ..models.manifest import EnvironmentManifestSnapshot
from ..models.shared import NodeInfo
from .store import PyprojectDocument

if TYPE_CHECKING:
    from ..managers.pyproject_manager import PyprojectManager


@dataclass(frozen=True)
class ComfyUIManifestVersion:
    """ComfyUI version metadata declared in the manifest."""

    version: str | None = None
    version_type: str | None = None


def _dependency_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [str(item) for item in value]
    except TypeError:
        return [str(value)]


def _ensure_table(config: dict, *path: str) -> dict[str, Any]:
    current: dict[str, Any] = config
    for key in path:
        child = current.get(key)
        if not isinstance(child, dict):
            child = tomlkit.table()
            current[key] = child
        current = cast(dict[str, Any], child)
    return current


def _set_comfygit_scalar(config: dict, key: str, value: object) -> None:
    """Set a scalar on [tool.comfygit] before child tables.

    TOML requires scalar values to appear before child tables such as
    [tool.comfygit.nodes.*]. TOMLKit can silently drop scalars appended after
    child tables, so rebuild this table in a valid order.
    """
    tool = _ensure_table(config, "tool")
    comfygit_cfg = _ensure_table(config, "tool", "comfygit")
    rebuilt = tomlkit.table()
    child_items: list[tuple[str, object]] = []

    for existing_key, existing_value in comfygit_cfg.items():
        if existing_key == key:
            continue
        if isinstance(existing_value, dict):
            child_items.append((existing_key, existing_value))
        else:
            rebuilt[existing_key] = existing_value

    rebuilt[key] = value
    for child_key, child_value in child_items:
        rebuilt[child_key] = child_value

    tool["comfygit"] = rebuilt


class ManifestEdit:
    """Batched domain edits against one loaded pyproject manifest document."""

    def __init__(self, manager: PyprojectManager, config: PyprojectDocument):
        self._manager = manager
        self.config = config
        self.changed = False

    def mark_changed(self) -> None:
        """Mark this transaction dirty after direct in-memory edits."""
        self.changed = True

    def remove_dependency_group(self, group: str) -> bool:
        """Remove a dependency group if it exists."""
        dep_groups = self.config.get("dependency-groups", {})
        if not isinstance(dep_groups, dict) or group not in dep_groups:
            return False
        del dep_groups[group]
        if not dep_groups:
            del self.config["dependency-groups"]
        self.changed = True
        return True

    def set_headless(self, enabled: bool = True) -> None:
        """Set the ComfyGit headless materialization marker."""
        _set_comfygit_scalar(self.config, "headless", bool(enabled))
        self.changed = True

    def clear_headless(self) -> bool:
        """Remove the ComfyGit headless materialization marker."""
        comfygit = (
            self.config.get("tool", {})
            .get("comfygit", {})
        )
        if not isinstance(comfygit, dict) or "headless" not in comfygit:
            return False
        del comfygit["headless"]
        self.changed = True
        return True

    def ensure_workflow(self, workflow_name: str) -> bool:
        """Ensure a workflow manifest entry and relative workflow path exist."""
        workflows = _ensure_table(self.config, "tool", "comfygit", "workflows")
        workflow = workflows.get(workflow_name)

        changed = False
        if not isinstance(workflow, dict):
            workflow = tomlkit.table()
            workflows[workflow_name] = workflow
            changed = True

        expected_path = f"workflows/{workflow_name}.json"
        if workflow.get("path") != expected_path:
            workflow["path"] = expected_path
            changed = True

        if changed:
            self.changed = True

        return changed

    def register_node(self, identifier: str, node_info: NodeInfo) -> None:
        """Add or replace one custom-node manifest entry."""
        nodes = _ensure_table(self.config, "tool", "comfygit", "nodes")
        node_table = tomlkit.table()
        for key, value in node_info.__dict__.items():
            if value is not None:
                node_table[key] = value
        nodes[identifier] = node_table
        self.changed = True

    def update_node_git_info(
        self,
        identifier: str,
        *,
        repository: str | None = None,
        branch: str | None = None,
        pinned_commit: str | None = None,
    ) -> bool:
        """Update portable git provenance for one manifest node."""
        nodes = (
            self.config.get("tool", {})
            .get("comfygit", {})
            .get("nodes", {})
        )
        if not isinstance(nodes, dict) or identifier not in nodes:
            return False
        node_data = nodes[identifier]
        if not isinstance(node_data, dict):
            return False

        changed = False
        if repository and node_data.get("repository") != repository:
            node_data["repository"] = repository
            changed = True
        if branch and node_data.get("branch") != branch:
            node_data["branch"] = branch
            changed = True
        if pinned_commit and node_data.get("pinned_commit") != pinned_commit:
            node_data["pinned_commit"] = pinned_commit
            changed = True
        if changed:
            self.changed = True
        return changed

    def add_model_source(self, model_hash: str, url: str) -> bool:
        """Add a source URL to a global manifest model."""
        model_data = self._model_entry(model_hash)
        sources = _dependency_list(model_data.get("sources", []))
        if url in sources:
            return False
        sources.append(url)
        model_data["sources"] = sources
        self.changed = True
        return True

    def remove_model_source(self, model_hash: str, url: str) -> bool:
        """Remove a source URL from a global manifest model."""
        model_data = self._model_entry(model_hash)
        sources = _dependency_list(model_data.get("sources", []))
        if url not in sources:
            return False
        updated = [source for source in sources if source != url]
        model_data["sources"] = updated
        self.changed = True
        return True

    def cleanup_model_orphans(self) -> None:
        """Remove global model entries no longer referenced by workflows."""
        self._manager.models.cleanup_orphans(config=self.config)
        self.changed = True

    def _model_entry(self, model_hash: str) -> dict[str, Any]:
        models = (
            self.config.get("tool", {})
            .get("comfygit", {})
            .get("models", {})
        )
        if not isinstance(models, dict) or model_hash not in models:
            raise KeyError(f"Model hash not found in manifest: {model_hash}")
        model_data = models[model_hash]
        if not isinstance(model_data, dict):
            raise KeyError(f"Model entry is not a table: {model_hash}")
        return cast(dict[str, Any], model_data)


class PyprojectManifest:
    """Domain API for a pyproject-backed ComfyGit environment manifest."""

    def __init__(self, manager: PyprojectManager):
        self._manager = manager

    def snapshot(self, force_reload: bool = False) -> EnvironmentManifestSnapshot:
        """Return a typed read-only projection of the manifest."""
        return EnvironmentManifestSnapshot.from_toml_dict(
            self._manager.load(force_reload=force_reload)
        )

    @contextmanager
    def edit(self) -> Iterator[ManifestEdit]:
        """Batch domain edits into one save."""
        edit = ManifestEdit(self._manager, self._manager.load())
        try:
            yield edit
        except Exception:
            self._manager.reset_lazy_handlers()
            raise
        else:
            if edit.changed:
                self._manager.save(edit.config)

    def is_headless(self) -> bool:
        """Return True when the manifest is marked headless."""
        config = self._manager.load()
        return bool(config.get("tool", {}).get("comfygit", {}).get("headless", False))

    def set_headless(self, enabled: bool = True) -> None:
        """Persist the headless marker."""
        with self.edit() as edit:
            edit.set_headless(enabled)

    def clear_headless(self) -> bool:
        """Remove the headless marker if present."""
        with self.edit() as edit:
            return edit.clear_headless()

    def remove_dependency_group(self, group: str) -> bool:
        """Remove a dependency group if present."""
        with self.edit() as edit:
            return edit.remove_dependency_group(group)

    def ensure_workflow(self, workflow_name: str) -> bool:
        """Ensure a workflow manifest entry and relative workflow path exist."""
        with self.edit() as edit:
            return edit.ensure_workflow(workflow_name)

    def register_node(self, identifier: str, node_info: NodeInfo) -> None:
        """Add or replace one custom-node manifest entry."""
        with self.edit() as edit:
            edit.register_node(identifier, node_info)

    def update_node_git_info(
        self,
        identifier: str,
        *,
        repository: str | None = None,
        branch: str | None = None,
        pinned_commit: str | None = None,
    ) -> bool:
        """Update portable git provenance for one manifest node."""
        with self.edit() as edit:
            return edit.update_node_git_info(
                identifier,
                repository=repository,
                branch=branch,
                pinned_commit=pinned_commit,
            )

    def add_model_source(self, model_hash: str, url: str) -> bool:
        """Add a source URL to a global manifest model."""
        with self.edit() as edit:
            return edit.add_model_source(model_hash, url)

    def remove_model_source(self, model_hash: str, url: str) -> bool:
        """Remove a source URL from a global manifest model."""
        with self.edit() as edit:
            return edit.remove_model_source(model_hash, url)

    def list_project_dependencies(self) -> list[str]:
        """Return standard project dependencies from pyproject.toml."""
        config = self._manager.load()
        return _dependency_list(config.get("project", {}).get("dependencies", []))

    def list_dependency_groups(self) -> dict[str, list[str]]:
        """Return UV dependency groups declared in pyproject.toml."""
        config = self._manager.load()
        dep_groups = config.get("dependency-groups", {})
        if not isinstance(dep_groups, dict):
            return {}
        return {
            str(group): _dependency_list(dependencies)
            for group, dependencies in dep_groups.items()
        }

    def get_python_version(self) -> str | None:
        """Return ComfyGit's declared Python version, if present."""
        config = self._manager.load()
        value = config.get("tool", {}).get("comfygit", {}).get("python_version")
        return str(value) if value is not None else None

    def get_comfyui_version(self) -> ComfyUIManifestVersion:
        """Return ComfyUI version metadata declared in the manifest."""
        config = self._manager.load()
        comfygit = config.get("tool", {}).get("comfygit", {})
        version = comfygit.get("comfyui_version") if isinstance(comfygit, dict) else None
        version_type = (
            comfygit.get("comfyui_version_type")
            if isinstance(comfygit, dict)
            else None
        )
        return ComfyUIManifestVersion(
            version=str(version) if version is not None else None,
            version_type=str(version_type) if version_type is not None else None,
        )
