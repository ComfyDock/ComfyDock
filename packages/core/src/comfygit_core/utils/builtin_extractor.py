"""Dynamic extraction of ComfyUI builtin nodes at environment creation."""
from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from pathlib import Path

from ..logging.logging_config import get_logger
from .comfyui_ops import get_comfyui_version
from .git import git_rev_parse

logger = get_logger(__name__)


def _is_valid_node_name(name: str) -> bool:
    """Check if a string is likely to be a valid node name."""
    invalid_patterns = [
        r'^\.py$',
        r'^pip\s+install',
        r'^\s*$',
        r'^__',
        r'^\d+$',
    ]

    for pattern in invalid_patterns:
        if re.match(pattern, name, re.IGNORECASE):
            return False

    if not name or len(name) < 2:
        return False

    return True


def _extract_from_ast(file_path: str) -> list[str]:
    """Extract NODE_CLASS_MAPPINGS using AST parsing."""
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        tree = ast.parse(content, filename=file_path)
        node_names = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "NODE_CLASS_MAPPINGS":
                        if isinstance(node.value, ast.Dict):
                            for key in node.value.keys:
                                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                    name = key.value.strip()
                                    if _is_valid_node_name(name):
                                        node_names.append(name)
                                elif isinstance(key, ast.Str):  # Python 3.7 compatibility
                                    name = key.s.strip()
                                    if _is_valid_node_name(name):
                                        node_names.append(name)

        return node_names
    except Exception:
        return []


def _extract_comfynode_from_ast(file_path: str) -> list[str]:
    """Extract nodes using the new io.ComfyNode pattern."""
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        tree = ast.parse(content, filename=file_path)
        node_names = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    base_name = ""
                    if isinstance(base, ast.Attribute):
                        base_name = base.attr
                    elif isinstance(base, ast.Name):
                        base_name = base.id

                    if "ComfyNode" in base_name:
                        for item in node.body:
                            if isinstance(item, ast.FunctionDef) and item.name == "define_schema":
                                for func_node in ast.walk(item):
                                    if isinstance(func_node, ast.keyword) and func_node.arg == "node_id":
                                        if isinstance(func_node.value, ast.Constant):
                                            name = func_node.value.value
                                            if _is_valid_node_name(str(name)):
                                                node_names.append(name)
                                        elif isinstance(func_node.value, ast.Str):
                                            name = func_node.value.s
                                            if _is_valid_node_name(name):
                                                node_names.append(name)

        return node_names
    except Exception:
        return []


def _extract_from_regex(file_path: str) -> list[str]:
    """Extract NODE_CLASS_MAPPINGS using regex as fallback."""
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        pattern = r'NODE_CLASS_MAPPINGS\s*=\s*\{'
        match = re.search(pattern, content)

        if not match:
            return []

        start_pos = match.end() - 1
        brace_count = 0
        end_pos = start_pos
        in_string = False
        string_char = None

        for i, char in enumerate(content[start_pos:], start_pos):
            if char in ('"', "'") and content[i-1] != '\\':
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None

            if not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = i + 1
                        break

        if end_pos == start_pos:
            return []

        dict_content = content[start_pos:end_pos]

        key_patterns = [
            r'"([^"]+)"\s*:',
            r"'([^']+)'\s*:",
        ]

        node_names = []
        for pattern in key_patterns:
            matches = re.finditer(pattern, dict_content)
            for match in matches:
                name = match.group(1).strip()
                if _is_valid_node_name(name) and name not in node_names:
                    node_names.append(name)

        return node_names

    except Exception:
        return []


def _extract_comfynode_from_regex(file_path: str) -> list[str]:
    """Extract io.ComfyNode nodes using regex as fallback."""
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        node_names = []

        patterns = [
            r'node_id\s*=\s*"([^"]+)"',
            r"node_id\s*=\s*'([^']+)'",
            r'NodeId\s*=\s*"([^"]+)"',
            r"NodeId\s*=\s*'([^']+)'",
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                name = match.group(1).strip()
                if _is_valid_node_name(name) and name not in node_names:
                    node_names.append(name)

        return node_names

    except Exception:
        return []


def _extract_node_names(file_path: str) -> list[str]:
    """Extract node names from a Python file using all patterns."""
    all_nodes = []

    # Traditional NODE_CLASS_MAPPINGS
    node_names = _extract_from_ast(file_path)
    if len(node_names) < 3:
        regex_names = _extract_from_regex(file_path)
        if len(regex_names) > len(node_names):
            node_names = regex_names

    all_nodes.extend(node_names)

    # V3 io.ComfyNode pattern
    comfynode_names = _extract_comfynode_from_ast(file_path)
    all_nodes.extend(comfynode_names)

    # Regex fallback for V3
    comfynode_regex_names = _extract_comfynode_from_regex(file_path)
    all_nodes.extend(comfynode_regex_names)

    return sorted(set(all_nodes))


def _discover_node_files(directory: Path) -> list[Path]:
    """Discover Python files that likely contain node definitions."""
    if not directory.exists():
        return []

    node_files = []
    exclude_patterns = ['__init__', '__pycache__', 'test_', 'setup', 'config']

    for file in directory.iterdir():
        if file.is_file() and file.suffix == '.py':
            if any(pattern in file.name.lower() for pattern in exclude_patterns):
                continue
            node_files.append(file)

    return sorted(node_files)


def _get_frontend_nodes() -> dict:
    """Get known frontend-only and native custom nodes."""
    return {
        'source': 'known_frontend_and_custom',
        'nodes': [
            'MarkdownNote',
            'Note',
            'PrimitiveNode',
            'Reroute',
            'SaveImageWebsocket'
        ],
        'count': 5
    }


def _extract_nodes_from_comfyui(comfyui_path: Path) -> tuple[dict, list]:
    """Extract all built-in nodes from a ComfyUI installation."""
    all_nodes: dict = {}
    errors: list = []

    # Core nodes.py
    nodes_file = comfyui_path / 'nodes.py'
    if nodes_file.exists():
        core_nodes = _extract_node_names(str(nodes_file))
        if core_nodes:
            all_nodes['core'] = {
                'source': 'nodes.py',
                'nodes': core_nodes,
                'count': len(core_nodes)
            }
            logger.debug(f"Extracted {len(core_nodes)} core nodes")

    # comfy_extras directory
    extras_dir = comfyui_path / 'comfy_extras'
    if extras_dir.exists():
        extras_all = []
        extras_by_file = {}

        for file_path in _discover_node_files(extras_dir):
            nodes = _extract_node_names(str(file_path))
            if nodes:
                extras_by_file[file_path.name] = nodes
                extras_all.extend(nodes)

        if extras_all:
            all_nodes['extras'] = {
                'source': 'comfy_extras',
                'nodes': sorted(set(extras_all)),
                'count': len(set(extras_all)),
                'by_file': extras_by_file
            }
            logger.debug(f"Extracted {len(set(extras_all))} extras nodes")

    # comfy_api_nodes directory
    api_dir = comfyui_path / 'comfy_api_nodes'
    if api_dir.exists():
        api_all = []
        api_by_file = {}

        for file_path in _discover_node_files(api_dir):
            nodes = _extract_node_names(str(file_path))
            if nodes:
                api_by_file[file_path.name] = nodes
                api_all.extend(nodes)

        if api_all:
            all_nodes['api'] = {
                'source': 'comfy_api_nodes',
                'nodes': sorted(set(api_all)),
                'count': len(set(api_all)),
                'by_file': api_by_file
            }
            logger.debug(f"Extracted {len(set(api_all))} API nodes")

    # custom_nodes directory (native ones)
    custom_dir = comfyui_path / 'custom_nodes'
    if custom_dir.exists():
        custom_all = []
        custom_by_file = {}

        for file_path in custom_dir.glob('*.py'):
            if file_path.name.startswith('__'):
                continue
            nodes = _extract_node_names(str(file_path))
            if nodes:
                custom_by_file[file_path.name] = nodes
                custom_all.extend(nodes)

        if custom_all:
            all_nodes['custom'] = {
                'source': 'custom_nodes',
                'nodes': sorted(set(custom_all)),
                'count': len(set(custom_all)),
                'by_file': custom_by_file
            }

    # Frontend nodes
    all_nodes['frontend'] = _get_frontend_nodes()

    return all_nodes, errors


def extract_comfyui_builtins(comfyui_path: Path, output_path: Path) -> dict:
    """
    Extract builtin nodes from ComfyUI installation and save to JSON.

    Args:
        comfyui_path: Path to ComfyUI directory
        output_path: Where to save JSON

    Returns:
        dict: Extracted structure with metadata and nodes

    Raises:
        ValueError: If ComfyUI path invalid
    """
    # Validate path
    if not (comfyui_path / "nodes.py").exists():
        raise ValueError(f"Invalid ComfyUI path: {comfyui_path}")

    logger.info(f"Extracting builtin nodes from ComfyUI at {comfyui_path}")

    # Extract nodes
    all_nodes, errors = _extract_nodes_from_comfyui(comfyui_path)

    # Combine all unique node names
    all_builtin = set()
    for category_data in all_nodes.values():
        all_builtin.update(category_data['nodes'])

    all_builtin_list = sorted(all_builtin)

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
            'total_nodes': len(all_builtin_list),
            'categories': list(all_nodes.keys())
        },
        'nodes_by_category': all_nodes,
        'all_builtin_nodes': all_builtin_list
    }

    if errors:
        output['errors'] = [{'file': f, 'error': e} for f, e in errors]

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save to file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"Extracted {len(all_builtin_list)} builtin nodes to {output_path}")

    return output
