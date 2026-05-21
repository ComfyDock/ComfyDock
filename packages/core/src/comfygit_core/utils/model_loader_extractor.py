"""Extract folder-backed ComfyUI model loader widgets from source."""
from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..logging.logging_config import get_logger
from .comfyui_ops import get_comfyui_version
from .git import git_rev_parse

logger = get_logger(__name__)


@dataclass(frozen=True)
class ExtractedModelLoaderWidget:
    """One folder-backed model selector widget exposed by a ComfyUI node."""

    widget_name: str
    directories: list[str]
    widget_index: int | None
    source_file: str
    source: str = "generated"


def _extract_string_constant(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _dotted_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _folder_key_from_filename_list(node: ast.AST | None) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if _dotted_name(node.func) != "folder_paths.get_filename_list":
        return None
    if not node.args:
        return None
    return _extract_string_constant(node.args[0])


def _find_folder_key(node: ast.AST | None) -> str | None:
    if node is None:
        return None

    direct = _folder_key_from_filename_list(node)
    if direct:
        return direct

    for child in ast.iter_child_nodes(node):
        found = _find_folder_key(child)
        if found:
            return found

    return None


def _is_combo_input_call(node: ast.Call) -> bool:
    return _dotted_name(node.func).endswith(".Combo.Input")


def _extract_schema_node_id(class_node: ast.ClassDef) -> str | None:
    class_string_constants: dict[str, str] = {}
    for item in class_node.body:
        if isinstance(item, ast.Assign):
            value = _extract_string_constant(item.value)
            if not value:
                continue
            for target in item.targets:
                if isinstance(target, ast.Name):
                    class_string_constants[target.id] = value
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            value = _extract_string_constant(item.value)
            if value:
                class_string_constants[item.target.id] = value

    for item in class_node.body:
        if not isinstance(item, ast.FunctionDef) or item.name != "define_schema":
            continue
        for node in ast.walk(item):
            if not isinstance(node, ast.Call):
                continue
            if not _dotted_name(node.func).endswith(".Schema"):
                continue
            for keyword in node.keywords:
                if keyword.arg != "node_id":
                    continue
                node_id = _extract_string_constant(keyword.value)
                if node_id:
                    return node_id
                if isinstance(keyword.value, ast.Attribute):
                    owner = keyword.value.value
                    if isinstance(owner, ast.Name) and owner.id == "cls":
                        return class_string_constants.get(keyword.value.attr)
    return None


def _extract_schema_widgets(
    class_node: ast.ClassDef,
    source_file: str,
) -> list[ExtractedModelLoaderWidget]:
    widgets: list[ExtractedModelLoaderWidget] = []

    for item in class_node.body:
        if not isinstance(item, ast.FunctionDef) or item.name != "define_schema":
            continue
        for node in ast.walk(item):
            if not isinstance(node, ast.Call) or not _is_combo_input_call(node):
                continue
            if not node.args:
                continue
            widget_name = _extract_string_constant(node.args[0])
            if not widget_name:
                continue

            folder_key = None
            for keyword in node.keywords:
                if keyword.arg == "options":
                    folder_key = _find_folder_key(keyword.value)
                    break
            if not folder_key:
                folder_key = _find_folder_key(node)
            if not folder_key:
                continue

            widgets.append(
                ExtractedModelLoaderWidget(
                    widget_name=widget_name,
                    directories=[folder_key],
                    widget_index=None,
                    source_file=source_file,
                )
            )

    if len(widgets) == 1:
        widget = widgets[0]
        widgets[0] = ExtractedModelLoaderWidget(
            widget_name=widget.widget_name,
            directories=widget.directories,
            widget_index=0,
            source_file=widget.source_file,
            source=widget.source,
        )

    return widgets


def _extract_input_types_widgets(
    class_node: ast.ClassDef,
    source_file: str,
) -> list[ExtractedModelLoaderWidget]:
    widgets: list[ExtractedModelLoaderWidget] = []

    for item in class_node.body:
        if not isinstance(item, ast.FunctionDef) or item.name != "INPUT_TYPES":
            continue
        for node in ast.walk(item):
            if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
                continue

            for section_key, section_value in zip(node.value.keys, node.value.values, strict=False):
                section_name = _extract_string_constant(section_key)
                if section_name not in {"required", "optional"}:
                    continue
                if not isinstance(section_value, ast.Dict):
                    continue

                for input_key, input_value in zip(section_value.keys, section_value.values, strict=False):
                    widget_name = _extract_string_constant(input_key)
                    if not widget_name:
                        continue
                    folder_key = _find_folder_key(input_value)
                    if not folder_key:
                        continue
                    widgets.append(
                        ExtractedModelLoaderWidget(
                            widget_name=widget_name,
                            directories=[folder_key],
                            widget_index=None,
                            source_file=source_file,
                        )
                    )

    if len(widgets) == 1:
        widget = widgets[0]
        widgets[0] = ExtractedModelLoaderWidget(
            widget_name=widget.widget_name,
            directories=widget.directories,
            widget_index=0,
            source_file=widget.source_file,
            source=widget.source,
        )

    return widgets


def _extract_node_class_mappings(tree: ast.AST) -> dict[str, str]:
    mappings: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "NODE_CLASS_MAPPINGS" for target in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values, strict=False):
            node_type = _extract_string_constant(key)
            class_name = _dotted_name(value)
            if node_type and class_name:
                mappings[class_name] = node_type
    return mappings


def _extract_from_file(file_path: Path, comfyui_path: Path) -> dict[str, list[ExtractedModelLoaderWidget]]:
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except Exception as exc:
        logger.debug(f"Failed to parse model loader metadata from {file_path}: {exc}")
        return {}

    source_file = file_path.relative_to(comfyui_path).as_posix()
    node_class_mappings = _extract_node_class_mappings(tree)
    by_node: dict[str, list[ExtractedModelLoaderWidget]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        widgets = _extract_schema_widgets(node, source_file)
        node_type = _extract_schema_node_id(node)

        if not widgets:
            widgets = _extract_input_types_widgets(node, source_file)
            node_type = node_class_mappings.get(node.name)

        if not widgets or not node_type:
            continue

        by_node.setdefault(node_type, []).extend(widgets)

    return by_node


def _discover_source_files(comfyui_path: Path) -> list[Path]:
    files: list[Path] = []

    nodes_py = comfyui_path / "nodes.py"
    if nodes_py.exists():
        files.append(nodes_py)

    for dirname in ("comfy_extras", "comfy_api_nodes"):
        directory = comfyui_path / dirname
        if not directory.exists():
            continue
        files.extend(
            sorted(
                path
                for path in directory.iterdir()
                if path.is_file()
                and path.suffix == ".py"
                and not path.name.startswith("__")
                and not path.name.startswith("test_")
            )
        )

    return files


def _merge_duplicate_widgets(
    widgets: list[ExtractedModelLoaderWidget],
) -> list[ExtractedModelLoaderWidget]:
    merged: dict[tuple[str, int | None], ExtractedModelLoaderWidget] = {}
    for widget in widgets:
        key = (widget.widget_name, widget.widget_index)
        existing = merged.get(key)
        if not existing:
            merged[key] = widget
            continue

        directories = list(existing.directories)
        for directory in widget.directories:
            if directory not in directories:
                directories.append(directory)
        merged[key] = ExtractedModelLoaderWidget(
            widget_name=existing.widget_name,
            directories=directories,
            widget_index=existing.widget_index,
            source_file=existing.source_file,
            source=existing.source,
        )

    return list(merged.values())


def extract_comfyui_model_loaders(comfyui_path: Path, output_path: Path) -> dict[str, Any]:
    """Extract built-in ComfyUI model loader metadata and save it to JSON."""
    if not (comfyui_path / "nodes.py").exists():
        raise ValueError(f"Invalid ComfyUI path: {comfyui_path}")

    logger.info(f"Extracting model loader metadata from ComfyUI at {comfyui_path}")

    model_loaders: dict[str, list[ExtractedModelLoaderWidget]] = {}
    for file_path in _discover_source_files(comfyui_path):
        for node_type, widgets in _extract_from_file(file_path, comfyui_path).items():
            model_loaders.setdefault(node_type, []).extend(widgets)

    serializable_loaders = {
        node_type: [asdict(widget) for widget in _merge_duplicate_widgets(widgets)]
        for node_type, widgets in sorted(model_loaders.items())
    }

    widget_count = sum(len(widgets) for widgets in serializable_loaders.values())
    version = get_comfyui_version(comfyui_path)
    commit_sha = git_rev_parse(comfyui_path, "HEAD")

    output: dict[str, Any] = {
        "metadata": {
            "extraction_date": datetime.now().isoformat(),
            "comfyui_path": str(comfyui_path),
            "comfyui_version": version,
            "comfyui_commit_sha": commit_sha[:7] if commit_sha else None,
            "total_model_loaders": len(serializable_loaders),
            "total_model_widgets": widget_count,
        },
        "model_loaders": serializable_loaders,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(
        f"Extracted {len(serializable_loaders)} model loaders "
        f"({widget_count} widgets) to {output_path}"
    )
    return output
