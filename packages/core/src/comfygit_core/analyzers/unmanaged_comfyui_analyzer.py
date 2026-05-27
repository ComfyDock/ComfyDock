"""Read-only scanner for unmanaged ComfyUI installations."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import TOMLKitError

from ..configs.model_config import ModelConfig, ModelLoaderWidgetMapping
from ..models.unmanaged_import import (
    NodeRegistryLookup,
    UnmanagedComfyUIImportPreview,
    UnmanagedCustomNodeScan,
    UnmanagedModelReferenceScan,
    UnmanagedWorkflowScan,
)

IGNORED_CUSTOM_NODE_DIRS = {"__pycache__"}

WORKFLOW_SOURCE_DIRS = (
    Path("user") / "default" / "workflows",
    Path("workflows"),
)


@dataclass(frozen=True)
class CustomNodePyprojectMetadata:
    project_name: str | None = None
    version: str | None = None
    repository: str | None = None
    display_name: str | None = None
    publisher_id: str | None = None


def detect_unmanaged_comfyui_path(source_path: str | Path | None = None) -> Path:
    """Return the current ComfyUI root, validating the expected directory shape."""
    candidates: list[Path] = []
    if source_path:
        candidates.append(Path(source_path).expanduser())
    else:
        candidates.extend([Path.cwd(), Path(sys.argv[0]).expanduser().parent])

    for candidate in candidates:
        path = candidate.resolve()
        if _looks_like_comfyui_root(path):
            return path

    checked = ", ".join(str(candidate) for candidate in candidates)
    raise ValueError(
        f"Could not find the current ComfyUI root from {checked}. Expected "
        "main.py, custom_nodes/, or user/default/workflows/."
    )


def scan_unmanaged_comfyui(
    source_path: str | Path | None = None,
    node_registry_lookup: NodeRegistryLookup | None = None,
    ignored_custom_node_names: Iterable[str] = (),
) -> UnmanagedComfyUIImportPreview:
    """Scan the unmanaged ComfyUI install without mutating it."""
    comfyui_path = detect_unmanaged_comfyui_path(source_path)
    warnings: list[str] = []

    workflows, model_references, models_scanned = _scan_workflows(comfyui_path, warnings)
    custom_nodes = _scan_custom_nodes(
        comfyui_path,
        warnings,
        node_registry_lookup,
        ignored_custom_node_names=ignored_custom_node_names,
    )
    version, commit = _detect_comfyui_version(comfyui_path)

    if not workflows:
        warnings.append("No saved workflow JSON files were found.")
    if not custom_nodes:
        warnings.append("No custom-node directories were found.")

    return UnmanagedComfyUIImportPreview(
        source_path=str(comfyui_path),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        comfyui_version=version,
        comfyui_commit=commit,
        workflows=workflows,
        model_references=model_references,
        models_scanned=models_scanned,
        custom_nodes=custom_nodes,
        warnings=warnings,
    )


def _looks_like_comfyui_root(path: Path) -> bool:
    return (
        (path / "main.py").exists()
        or (path / "custom_nodes").is_dir()
        or (path / "user" / "default" / "workflows").is_dir()
    )


def _scan_workflows(
    comfyui_path: Path,
    warnings: list[str],
) -> tuple[list[UnmanagedWorkflowScan], list[UnmanagedModelReferenceScan], bool]:
    seen: set[str] = set()
    workflows: list[UnmanagedWorkflowScan] = []
    model_references: list[UnmanagedModelReferenceScan] = []
    models_scanned = True
    model_config = _load_model_config_for_unmanaged_comfyui(comfyui_path)

    for relative_dir in WORKFLOW_SOURCE_DIRS:
        workflow_dir = comfyui_path / relative_dir
        if not workflow_dir.is_dir():
            continue
        for path in sorted(workflow_dir.glob("*.json")):
            if path.name in seen:
                continue
            seen.add(path.name)
            refs, scanned = _scan_workflow_model_references(path, model_config)
            if not scanned:
                models_scanned = False
                warnings.append(f"Could not scan model references for workflow '{path.stem}'.")
            model_references.extend(refs)
            workflows.append(
                UnmanagedWorkflowScan(
                    name=path.stem,
                    path=str(path),
                    models_required=len(refs),
                    models_optional=0,
                )
            )

    return workflows, model_references, models_scanned


def _load_model_config_for_unmanaged_comfyui(comfyui_path: Path) -> ModelConfig:
    """Build model-loader policy from the unmanaged ComfyUI checkout when possible."""
    from ..utils.folder_paths_extractor import extract_folder_paths
    from ..utils.model_loader_extractor import extract_comfyui_model_loaders

    with tempfile.TemporaryDirectory(prefix="comfygit-unmanaged-model-config-") as temp_dir:
        cec_path = Path(temp_dir)

        try:
            extract_folder_paths(comfyui_path, cec_path / "comfyui_folder_paths.json")
        except Exception:
            pass

        try:
            extract_comfyui_model_loaders(comfyui_path, cec_path / "comfyui_model_loaders.json")
        except Exception:
            pass

        if (cec_path / "comfyui_folder_paths.json").exists() or (cec_path / "comfyui_model_loaders.json").exists():
            return ModelConfig.load(cec_path=cec_path)

    return ModelConfig.load()


def _scan_workflow_model_references(
    path: Path,
    model_config: ModelConfig,
) -> tuple[list[UnmanagedModelReferenceScan], bool]:
    """Return model references from a saved workflow without resolving availability."""
    try:
        from comfygit_core.workflow import WorkflowDependencyParser

        dependencies = WorkflowDependencyParser(
            path,
            workflow_name=path.stem,
            model_config=model_config,
            version_agnostic=True,
        ).analyze_dependencies()
    except Exception:
        return _scan_workflow_model_references_from_json(path, model_config)

    if not dependencies.found_models:
        return _scan_workflow_model_references_from_json(path, model_config)

    refs: list[UnmanagedModelReferenceScan] = []
    seen: set[tuple[str, str | None, str | None, int | None, str | None]] = set()
    for ref in dependencies.found_models:
        widget_value = _string_value(getattr(ref, "widget_value", None))
        if not widget_value:
            continue
        normalized_ref = _normalize_model_reference(
            widget_value,
            _string_value(getattr(ref, "property_directory", None)),
            model_config,
        )
        if normalized_ref is None:
            continue
        node_type = _string_value(getattr(ref, "node_type", None))
        widget_index = getattr(ref, "widget_index", None)
        widget_index = widget_index if isinstance(widget_index, int) else None
        source_url = _string_value(getattr(ref, "property_url", None))
        key = (
            normalized_ref.filename,
            normalized_ref.category,
            node_type,
            widget_index,
            normalized_ref.relative_path,
        )
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            UnmanagedModelReferenceScan(
                filename=normalized_ref.filename,
                workflow=path.stem,
                category=normalized_ref.category,
                relative_path=normalized_ref.relative_path,
                widget_value=normalized_ref.widget_value,
                node_type=node_type,
                widget_index=widget_index,
                source_url=source_url,
            )
        )

    return refs, True


def _scan_workflow_model_references_from_json(
    path: Path,
    model_config: ModelConfig,
) -> tuple[list[UnmanagedModelReferenceScan], bool]:
    """Fallback scanner for older core installs or partial workflow metadata."""
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [], False

    refs: list[UnmanagedModelReferenceScan] = []
    ref_index: dict[tuple[str, str | None, str | None, str | None], int] = {}

    def add_ref(widget_value: str, category: str | None, node_type: str | None, source_url: str | None = None) -> None:
        normalized_ref = _normalize_model_reference(widget_value, category, model_config)
        if normalized_ref is None:
            return
        key = (
            normalized_ref.filename,
            normalized_ref.category,
            node_type,
            normalized_ref.relative_path,
        )
        if key in ref_index:
            existing_index = ref_index[key]
            existing = refs[existing_index]
            if source_url and not existing.source_url:
                refs[existing_index] = UnmanagedModelReferenceScan(
                    filename=existing.filename,
                    workflow=existing.workflow,
                    category=existing.category,
                    relative_path=existing.relative_path,
                    widget_value=existing.widget_value,
                    node_type=existing.node_type,
                    widget_index=existing.widget_index,
                    source_url=source_url,
                )
            return
        ref_index[key] = len(refs)
        refs.append(
            UnmanagedModelReferenceScan(
                filename=normalized_ref.filename,
                workflow=path.stem,
                category=normalized_ref.category,
                relative_path=normalized_ref.relative_path,
                widget_value=normalized_ref.widget_value,
                node_type=node_type,
                source_url=source_url,
            )
        )

    def walk(value: Any, *, key: str | None = None, node_type: str | None = None) -> None:
        if isinstance(value, dict):
            current_node_type = _string_value(value.get("type")) or _string_value(value.get("class_type")) or node_type
            widgets_values = value.get("widgets_values") or value.get("widget_values")
            if current_node_type and isinstance(widgets_values, list):
                mappings = model_config.get_model_loader_widgets(current_node_type)
                for mapping in mappings:
                    widget_index = _fallback_widget_index(mapping, mappings, widgets_values)
                    if widget_index is None:
                        continue
                    if widget_index >= len(widgets_values):
                        continue
                    widget_value = widgets_values[widget_index]
                    category = mapping.directories[0] if mapping.directories else None
                    if isinstance(widget_value, str) and _looks_like_model_value(widget_value, model_config):
                        add_ref(widget_value, category, current_node_type)

            property_models = value.get("models")
            if key == "properties" and isinstance(property_models, list):
                for model_entry in property_models:
                    if not isinstance(model_entry, dict):
                        continue
                    name = _string_value(model_entry.get("name"))
                    if name and _looks_like_model_value(name, model_config):
                        add_ref(
                            name,
                            _string_value(model_entry.get("directory"))
                            or _category_for_model_path(name, model_config),
                            current_node_type,
                            _string_value(model_entry.get("url")),
                        )
            for child_key, child_value in value.items():
                walk(child_value, key=str(child_key), node_type=current_node_type)
            return

        if isinstance(value, list):
            for item in value:
                walk(item, key=key, node_type=node_type)
            return

        if isinstance(value, str) and key:
            category = _category_for_model_input_key(node_type, key, model_config) or _category_for_model_path(
                value,
                model_config,
            )
            if category and _looks_like_model_value(value, model_config):
                add_ref(value, category, node_type)

    walk(data)
    return refs, True


def _fallback_widget_index(
    mapping: ModelLoaderWidgetMapping,
    mappings: list[ModelLoaderWidgetMapping],
    widgets_values: list[Any],
) -> int | None:
    if mapping.widget_index is not None:
        return mapping.widget_index
    if len(mappings) == 1 and len(widgets_values) == 1:
        return 0
    return None


def _category_for_model_path(value: str, model_config: ModelConfig) -> str | None:
    normalized = _normalize_model_path_value(value)
    first_part = normalized.split("/", 1)[0].lower()
    for directory in model_config.standard_directories:
        if first_part == directory.lower():
            return directory
    return None


def _category_for_model_input_key(node_type: str | None, key: str, model_config: ModelConfig) -> str | None:
    if not node_type:
        return None

    mappings = model_config.get_model_loader_widgets(node_type)
    if not mappings:
        return None

    normalized_key = key.lower().replace("-", "_")
    for mapping in mappings:
        widget_name = mapping.widget_name
        if widget_name and widget_name.lower().replace("-", "_") == normalized_key:
            return mapping.directories[0] if mapping.directories else None

    first_dirs = {
        mapping.directories[0]
        for mapping in mappings
        if mapping.directories
    }
    if len(first_dirs) == 1:
        return next(iter(first_dirs))

    return None


@dataclass(frozen=True)
class NormalizedModelReference:
    filename: str
    category: str | None
    relative_path: str | None
    widget_value: str


def _normalize_model_path_value(value: str) -> str:
    return value.strip().replace("\\", "/").strip("/")


def _normalize_model_reference(
    widget_value: str,
    category: str | None,
    model_config: ModelConfig,
) -> NormalizedModelReference | None:
    normalized_value = _normalize_model_path_value(widget_value)
    if not normalized_value:
        return None

    path_category = _category_for_model_path(normalized_value, model_config)
    resolved_category = path_category or category
    filename = normalized_value.rsplit("/", 1)[-1]
    if not filename:
        return None

    relative_path = None
    if path_category:
        relative_path = normalized_value
    elif resolved_category:
        relative_path = f"{resolved_category}/{normalized_value}"

    return NormalizedModelReference(
        filename=filename,
        category=resolved_category,
        relative_path=relative_path,
        widget_value=normalized_value,
    )


def _looks_like_model_value(value: str, model_config: ModelConfig) -> bool:
    stripped = value.strip()
    if not stripped or stripped.startswith(("http://", "https://")):
        return False
    return (
        model_config.is_model_file(Path(stripped))
        or "/" in stripped
        or "\\" in stripped
    )


def _scan_custom_nodes(
    comfyui_path: Path,
    warnings: list[str],
    node_registry_lookup: NodeRegistryLookup | None = None,
    *,
    ignored_custom_node_names: Iterable[str] = (),
) -> list[UnmanagedCustomNodeScan]:
    custom_nodes_dir = comfyui_path / "custom_nodes"
    if not custom_nodes_dir.is_dir():
        return []

    nodes: list[UnmanagedCustomNodeScan] = []
    ignored_names = set(IGNORED_CUSTOM_NODE_DIRS)
    ignored_names.update(ignored_custom_node_names)
    for path in sorted(custom_nodes_dir.iterdir(), key=lambda item: item.name.lower()):
        if not _is_importable_custom_node(path, ignored_names):
            continue

        metadata = _read_node_pyproject_metadata(path)
        is_git_checkout = _is_git_checkout(path)
        repository = _git_output(path, "remote", "get-url", "origin") if is_git_checkout else None
        commit = _git_output(path, "rev-parse", "HEAD") if is_git_checkout else None
        branch = _git_output(path, "branch", "--show-current") if is_git_checkout else None
        registry_id = None
        version = metadata.version if metadata else None
        install_spec = None
        provenance_detail = None
        source_type = "git" if repository else "local"
        warning = None
        requires_review = False

        if repository:
            install_spec = _git_install_spec(repository, commit)
            provenance_detail = "independent Git checkout"
        else:
            registry_match = _resolve_registry_provenance(
                path,
                metadata,
                node_registry_lookup,
            )
            if registry_match:
                registry_id, matched_version, package_repository = registry_match
                source_type = "registry"
                version = matched_version
                repository = package_repository
                install_spec = f"{registry_id}@{matched_version}"
                provenance_detail = "pyproject metadata matched registry package version"
            elif metadata and metadata.repository:
                source_type = "git"
                repository = metadata.repository
                install_spec = metadata.repository
                provenance_detail = "repository URL from node pyproject metadata"
                if metadata.version:
                    requires_review = True
                    warning = (
                        "Found repository metadata but no matching registry package version; "
                        "the imported environment will use the Git source and may not pin the exact local revision."
                    )
                    warnings.append(
                        f"Custom node '{path.name}' declares version {metadata.version} but no matching "
                        "registry version was found; importing from its Git repository."
                    )

        if source_type == "local":
            requires_review = True
            warning = "No Git remote detected; copied as a local development node."
            warnings.append(f"Custom node '{path.name}' has no Git remote and will need manual provenance review.")

        nodes.append(
            UnmanagedCustomNodeScan(
                name=path.name,
                path=str(path),
                source_type=source_type,
                registry_id=registry_id,
                version=version,
                install_spec=install_spec,
                repository=repository,
                branch=branch,
                pinned_commit=commit,
                warning=warning,
                provenance_detail=provenance_detail,
                requires_review=requires_review,
            )
        )

    return nodes


def _is_importable_custom_node(path: Path, ignored_names: set[str]) -> bool:
    if path.name in ignored_names:
        return False
    if path.name.startswith(".") or path.name.endswith(".disabled"):
        return False
    return path.is_dir()


def _read_node_pyproject_metadata(path: Path) -> CustomNodePyprojectMetadata | None:
    pyproject_path = path / "pyproject.toml"
    if not pyproject_path.is_file():
        return None

    try:
        data = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, TOMLKitError):
        return None

    project = data.get("project") if isinstance(data, dict) else None
    project = project if isinstance(project, dict) else {}
    urls = project.get("urls")
    urls = urls if isinstance(urls, dict) else {}
    tool = data.get("tool") if isinstance(data, dict) else None
    tool = tool if isinstance(tool, dict) else {}
    comfy = tool.get("comfy")
    comfy = comfy if isinstance(comfy, dict) else {}

    return CustomNodePyprojectMetadata(
        project_name=_string_value(project.get("name")),
        version=_string_value(project.get("version")),
        repository=_url_value(urls, "Repository", "repository", "Source", "Homepage", "homepage"),
        display_name=_string_value(comfy.get("DisplayName")),
        publisher_id=_string_value(comfy.get("PublisherId")),
    )


def _resolve_registry_provenance(
    path: Path,
    metadata: CustomNodePyprojectMetadata | None,
    node_registry_lookup: NodeRegistryLookup | None,
) -> tuple[str, str, str | None] | None:
    if not metadata or not metadata.version or not node_registry_lookup:
        return None

    packages = _candidate_registry_packages(path, metadata, node_registry_lookup)
    for package in packages:
        version = _matching_registry_version(package, metadata.version)
        if version:
            package_id = _string_value(getattr(package, "id", None))
            if package_id:
                return package_id, version, _string_value(getattr(package, "repository", None))
    return None


def _candidate_registry_packages(
    path: Path,
    metadata: CustomNodePyprojectMetadata,
    node_registry_lookup: NodeRegistryLookup,
) -> list[Any]:
    packages: list[Any] = []
    seen: set[str] = set()

    def add_package(package: Any | None) -> None:
        package_id = _string_value(getattr(package, "id", None))
        if not package or not package_id or package_id in seen:
            return
        packages.append(package)
        seen.add(package_id)

    for candidate in _node_package_id_candidates(path, metadata):
        add_package(node_registry_lookup.get_package(candidate))

    if metadata.repository:
        add_package(node_registry_lookup.resolve_github_url(metadata.repository))

    return packages


def _node_package_id_candidates(path: Path, metadata: CustomNodePyprojectMetadata) -> list[str]:
    raw_values = [
        metadata.project_name,
        metadata.display_name,
        path.name,
    ]
    candidates: list[str] = []
    seen: set[str] = set()

    for value in raw_values:
        normalized = _string_value(value)
        if not normalized:
            continue
        variants = {
            normalized,
            normalized.lower(),
            normalized.replace("_", "-"),
            normalized.lower().replace("_", "-"),
            normalized.replace(" ", "-"),
            normalized.lower().replace(" ", "-"),
        }
        for variant in variants:
            variant = variant.strip("-_ ")
            if variant and variant not in seen:
                candidates.append(variant)
                seen.add(variant)

    return candidates


def _matching_registry_version(package: Any, local_version: str) -> str | None:
    versions = getattr(package, "versions", None)
    if not isinstance(versions, dict):
        return None

    for version_key, version_info in versions.items():
        registry_version = _string_value(getattr(version_info, "version", None)) or str(version_key)
        if not _versions_match(registry_version, local_version) and not _versions_match(str(version_key), local_version):
            continue
        if getattr(version_info, "deprecated", False):
            continue
        if not _string_value(getattr(version_info, "download_url", None)):
            continue
        return registry_version
    return None


def _versions_match(registry_version: str, local_version: str) -> bool:
    return registry_version == local_version or registry_version.lstrip("v") == local_version.lstrip("v")


def _git_install_spec(repository: str, commit: str | None) -> str:
    return f"{repository}@{commit}" if commit else repository


def _string_value(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def _url_value(values: dict[str, Any], *keys: str) -> str | None:
    lower_lookup = {key.lower(): value for key, value in values.items() if isinstance(key, str)}
    for key in keys:
        value = lower_lookup.get(key.lower())
        parsed = _string_value(value)
        if parsed:
            return parsed
    return None


def _detect_comfyui_version(comfyui_path: Path) -> tuple[str | None, str | None]:
    version = (
        _read_comfyui_version_py(comfyui_path)
        or _read_project_version(comfyui_path)
        or _git_output(comfyui_path, "describe", "--tags", "--exact-match", "HEAD")
    )
    commit = _git_output(comfyui_path, "rev-parse", "HEAD")
    return version, commit


def _read_comfyui_version_py(comfyui_path: Path) -> str | None:
    version_path = comfyui_path / "comfyui_version.py"
    if not version_path.is_file():
        return None
    try:
        content = version_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    match = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", content, flags=re.MULTILINE)
    return _string_value(match.group(1)) if match else None


def _read_project_version(path: Path) -> str | None:
    pyproject_path = path / "pyproject.toml"
    if not pyproject_path.is_file():
        return None
    try:
        data = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, TOMLKitError):
        return None

    project = data.get("project") if isinstance(data, dict) else None
    if not isinstance(project, dict):
        return None
    return _string_value(project.get("version"))


def _is_git_checkout(path: Path) -> bool:
    root = _git_output(path, "rev-parse", "--show-toplevel")
    if not root:
        return False
    try:
        return Path(root).resolve() == path.resolve()
    except OSError:
        return False


def _git_output(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None
