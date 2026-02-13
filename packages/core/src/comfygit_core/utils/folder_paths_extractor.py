"""Dynamic extraction of ComfyUI folder_paths at environment creation."""
from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path

from ..logging.logging_config import get_logger
from .comfyui_ops import get_comfyui_version
from .git import git_rev_parse

logger = get_logger(__name__)


def _extract_string_constant(node: ast.AST | None) -> str | None:
    """Extract string literals from Python 3.10+ AST nodes."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_directory_name(node: ast.expr) -> str | None:
    """
    Extract the directory name from an os.path.join call.

    Handles patterns like:
    - os.path.join(models_dir, "checkpoints") -> "checkpoints"
    - os.path.join(models_dir, "text_encoders") -> "text_encoders"
    """
    if isinstance(node, ast.Call):
        # Check if it's os.path.join
        if isinstance(node.func, ast.Attribute) and node.func.attr == "join":
            # Get the last argument (the folder name)
            if node.args:
                last_arg = node.args[-1]
                return _extract_string_constant(last_arg)
    return None


def _extract_folder_mappings_from_ast(content: str) -> dict[str, list[str]]:
    """
    Extract folder_names_and_paths mappings using AST parsing.

    Parses assignments like:
    folder_names_and_paths["text_encoders"] = ([os.path.join(models_dir, "text_encoders"),
                                                 os.path.join(models_dir, "clip")], extensions)

    Returns:
        Dict mapping folder_name -> list of directory names
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        logger.warning(f"Failed to parse folder_paths.py: {e}")
        return {}

    mappings: dict[str, list[str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            # Look for folder_names_and_paths["key"] = ...
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    # Check if subscripting folder_names_and_paths
                    if isinstance(target.value, ast.Name) and target.value.id == "folder_names_and_paths":
                        # Get the key
                        key = _extract_string_constant(target.slice)

                        if key and isinstance(node.value, ast.Tuple) and len(node.value.elts) >= 1:
                            # First element of tuple is the list of paths
                            paths_list = node.value.elts[0]
                            if isinstance(paths_list, ast.List):
                                directories = []
                                for path_node in paths_list.elts:
                                    dir_name = _extract_directory_name(path_node)
                                    if dir_name:
                                        directories.append(dir_name)

                                if directories:
                                    mappings[key] = directories

    return mappings


def _extract_legacy_aliases_from_ast(content: str) -> dict[str, str]:
    """
    Extract legacy aliases from map_legacy function.

    Parses:
    def map_legacy(folder_name: str) -> str:
        legacy = {"unet": "diffusion_models", "clip": "text_encoders"}
        return legacy.get(folder_name, folder_name)

    Returns:
        Dict mapping old_name -> new_name
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return {}

    aliases: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "map_legacy":
            # Look for dict assignment inside the function
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id == "legacy":
                            if isinstance(stmt.value, ast.Dict):
                                for key, value in zip(stmt.value.keys, stmt.value.values, strict=False):
                                    key_str = _extract_string_constant(key)
                                    value_str = _extract_string_constant(value)

                                    if key_str and value_str:
                                        aliases[key_str] = value_str

    return aliases


def extract_folder_paths(comfyui_path: Path, output_path: Path) -> dict:
    """
    Extract folder_names_and_paths from ComfyUI installation and save to JSON.

    Parses folder_paths.py to get:
    1. folder_names_and_paths dict: {folder_name: [directories]}
    2. map_legacy function: {old_name: new_name} mappings

    Args:
        comfyui_path: Path to ComfyUI directory
        output_path: Where to save JSON

    Returns:
        dict: Extracted structure with metadata and mappings:
        {
            "metadata": {...},
            "folder_mappings": {
                "text_encoders": ["text_encoders", "clip"],
                "diffusion_models": ["unet", "diffusion_models"],
                ...
            },
            "legacy_aliases": {
                "clip": "text_encoders",
                "unet": "diffusion_models"
            }
        }

    Raises:
        ValueError: If ComfyUI path is invalid (no folder_paths.py)
    """
    folder_paths_file = comfyui_path / "folder_paths.py"

    # Validate path
    if not folder_paths_file.exists():
        raise ValueError(f"Invalid ComfyUI path: {comfyui_path} (no folder_paths.py)")

    logger.info(f"Extracting folder_paths from ComfyUI at {comfyui_path}")

    # Read file content
    with open(folder_paths_file, encoding='utf-8') as f:
        content = f.read()

    # Extract mappings
    folder_mappings = _extract_folder_mappings_from_ast(content)
    legacy_aliases = _extract_legacy_aliases_from_ast(content)

    # Get version info
    version = get_comfyui_version(comfyui_path)
    commit_sha = git_rev_parse(comfyui_path, "HEAD")

    # Build output structure
    output = {
        'metadata': {
            'extraction_date': datetime.now().isoformat(),
            'comfyui_path': str(comfyui_path),
            'comfyui_version': version,
            'comfyui_commit_sha': commit_sha[:7] if commit_sha else None,
            'total_folder_types': len(folder_mappings),
        },
        'folder_mappings': folder_mappings,
        'legacy_aliases': legacy_aliases,
    }

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save to file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"Extracted {len(folder_mappings)} folder mappings to {output_path}")

    return output
