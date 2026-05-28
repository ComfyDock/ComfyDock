"""Create managed environments from unmanaged ComfyUI installations."""

from __future__ import annotations

import platform
import re
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import cast

from ..analyzers.unmanaged_comfyui_analyzer import scan_unmanaged_comfyui
from ..models.unmanaged_import import (
    NodeRegistryLookup,
    UnmanagedComfyUIImportResult,
    UnmanagedDevelopmentNodeLink,
    UnmanagedImportCallbacks,
)

BARE_COMFYUI_RELEASE_RE = re.compile(r"^\d+(?:\.\d+)+(?:[-+][A-Za-z0-9._-]+)?$")


def import_unmanaged_comfyui_environment(
    workspace,
    *,
    name: str,
    source_path: str | Path | None = None,
    torch_backend: str = "auto",
    callbacks: UnmanagedImportCallbacks | None = None,
    ignored_custom_node_names: Iterable[str] = (),
    development_node_links: Iterable[UnmanagedDevelopmentNodeLink] = (),
    node_registry_lookup: NodeRegistryLookup | None = None,
) -> UnmanagedComfyUIImportResult:
    """Create a managed environment from an existing unmanaged ComfyUI install."""
    resolved_registry_lookup = node_registry_lookup or _get_node_registry_lookup(workspace)
    preview = scan_unmanaged_comfyui(
        source_path,
        node_registry_lookup=resolved_registry_lookup,
        ignored_custom_node_names=ignored_custom_node_names,
    )
    warnings = list(preview.warnings)

    _phase(callbacks, "clone_comfyui", f"Creating managed environment '{name}'...")
    create_kwargs: dict[str, object] = {
        "name": name,
        "python_version": preview.python_version,
        "comfyui_version": _comfyui_create_version(preview.comfyui_version),
        "torch_backend": torch_backend,
    }
    if callbacks:
        create_kwargs["progress"] = _EnvironmentCreateProgressAdapter(callbacks)
    env = workspace.create_environment(**create_kwargs)
    _link_development_nodes(env, development_node_links, warnings, callbacks)

    workflows_copied = 0
    custom_nodes_copied = 0

    _phase(callbacks, "copy_workflows", "Copying saved workflows...")
    for workflow in preview.workflows:
        src = Path(workflow.path)
        dst = env.comfyui_path / "user" / "default" / "workflows" / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        workflows_copied += 1
        if callbacks:
            callbacks.on_workflow_copied(src.stem)

    _copy_workflows_to_manifest(env, warnings, callbacks)

    _phase(callbacks, "sync_nodes", "Copying custom nodes...")
    target_custom_nodes = env.comfyui_path / "custom_nodes"
    target_custom_nodes.mkdir(parents=True, exist_ok=True)

    for node in preview.custom_nodes:
        src = Path(node.path)
        dst = target_custom_nodes / src.name
        try:
            if node.install_spec:
                try:
                    env.add_node(
                        node.install_spec,
                        no_test=True,
                        force=True,
                    )
                    custom_nodes_copied += 1
                    if callbacks:
                        callbacks.on_node_installed(src.name)
                    continue
                except Exception as exc:
                    message = (
                        f"Could not install custom node '{src.name}' from "
                        f"{node.source_type} provenance ({node.install_spec}): {exc}. "
                        "Falling back to a copied development node."
                    )
                    warnings.append(message)
                    _warn(callbacks, message)

            if dst.exists() or dst.is_symlink():
                warnings.append(f"Skipped custom node '{src.name}' because it already exists in the managed environment.")
                continue

            shutil.copytree(src, dst, symlinks=True, ignore=_copy_ignore)
            custom_nodes_copied += 1
            if callbacks:
                callbacks.on_node_installed(src.name)

            try:
                env.link_development_node(
                    src.name,
                    dst,
                    name=src.name,
                    replace_existing=True,
                    force=True,
                )
            except Exception as exc:  # best-effort manifest seeding
                message = f"Copied custom node '{src.name}' but could not register it in the manifest: {exc}"
                warnings.append(message)
                _warn(callbacks, message)
        except Exception as exc:
            message = f"Skipped custom node '{src.name}': {exc}"
            warnings.append(message)
            _warn(callbacks, message)

    _phase(callbacks, "resolve_models", "Resolving copied workflows...")
    for workflow in preview.workflows:
        try:
            env.invalidate_workflow_resolution_cache(workflow.name)
            env.resolve_workflow(workflow.name, fix=False)
        except Exception as exc:  # keep import usable; status will surface issues
            message = f"Copied workflow '{workflow.name}' but could not resolve it automatically: {exc}"
            warnings.append(message)
            _warn(callbacks, message)

    _phase(callbacks, "finalize", "Finalizing imported environment...")
    return UnmanagedComfyUIImportResult(
        environment_name=env.name,
        workflows_copied=workflows_copied,
        custom_nodes_copied=custom_nodes_copied,
        warnings=warnings,
    )


def _get_node_registry_lookup(workspace) -> NodeRegistryLookup | None:
    return getattr(workspace, "node_mapping_repository", None)


def _link_development_nodes(
    env,
    development_node_links: Iterable[UnmanagedDevelopmentNodeLink],
    warnings: list[str],
    callbacks: UnmanagedImportCallbacks | None,
) -> None:
    for link in development_node_links:
        try:
            env.link_development_node(
                link.identifier,
                link.source_path,
                name=link.name,
                replace_existing=True,
                force=True,
            )
        except Exception as exc:
            message = f"Could not register development node '{link.identifier}' in the imported environment: {exc}"
            warnings.append(message)
            _warn(callbacks, message)


def _copy_workflows_to_manifest(
    env,
    warnings: list[str],
    callbacks: UnmanagedImportCallbacks | None,
) -> None:
    try:
        copy_method = getattr(env, "copy_workflows_to_manifest", None)
        if callable(copy_method):
            results = cast(dict[str, Path | str | None], copy_method())
        else:
            results = _copy_workflows_to_cec_directly(env)
    except Exception as exc:
        message = f"Copied workflows into ComfyUI but could not track them in the managed manifest: {exc}"
        warnings.append(message)
        _warn(callbacks, message)
        return

    failed = [name for name, result in results.items() if result is None]
    for name in failed:
        message = f"Could not track workflow '{name}' in the managed manifest."
        warnings.append(message)
        _warn(callbacks, message)


def _copy_workflows_to_cec_directly(env) -> dict[str, Path | None]:
    comfyui_path = env.comfyui_path
    cec_path = env.cec_path
    source_dir = comfyui_path / "user" / "default" / "workflows"
    dest_dir = cec_path / "workflows"
    dest_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Path | None] = {}
    for source in source_dir.glob("*.json"):
        dest = dest_dir / source.name
        try:
            shutil.copy2(source, dest)
            results[source.stem] = dest
        except Exception:
            results[source.stem] = None
    return results


def _comfyui_create_version(version: str | None) -> str | None:
    """Return a ComfyUI Git ref suitable for core environment creation."""
    if not version:
        return None
    if BARE_COMFYUI_RELEASE_RE.match(version):
        return f"v{version}"
    return version


def _copy_ignore(directory: str, names: list[str]) -> set[str]:
    ignored = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
    if platform.system() == "Windows":
        ignored.add(".venv")
    return {name for name in names if name in ignored or name.endswith(".pyc")}


def _phase(callbacks: UnmanagedImportCallbacks | None, phase: str, message: str) -> None:
    if callbacks:
        callbacks.on_phase(phase, message)


def _warn(callbacks: UnmanagedImportCallbacks | None, message: str) -> None:
    if callbacks:
        callbacks.on_error(message)


class _EnvironmentCreateProgressAdapter:
    """Bridge core environment creation progress into unmanaged-import callbacks."""

    def __init__(self, callbacks: UnmanagedImportCallbacks):
        self.callbacks = callbacks

    def on_phase(self, phase: str, description: str, progress_pct: int) -> None:
        self.callbacks.on_phase(phase, description)

    def on_phase_complete(self, phase: str, success: bool, error: str | None = None) -> None:
        if not success and error:
            self.callbacks.on_error(f"{phase} failed: {error}")

    def on_log(self, message: str) -> None:
        on_log = getattr(self.callbacks, "on_log", None)
        if callable(on_log):
            on_log(message)
