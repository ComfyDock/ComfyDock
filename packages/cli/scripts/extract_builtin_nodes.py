#!/usr/bin/env python3
"""
Extract built-in ComfyUI nodes by parsing NODE_CLASS_MAPPINGS from Python files.

Usage:
    python extract_builtin_nodes.py --path /path/to/ComfyUI --output /path/to/output.json
    python extract_builtin_nodes.py  # Uses current directory and default output
"""

import argparse
import ast
import json
import re
import sys
from datetime import datetime
from pathlib import Path


def is_valid_node_name(name: str) -> bool:
    """Check if a string is likely to be a valid node name."""
    # Filter out obviously invalid node names
    invalid_patterns = [
        r'^\.py$',  # Just .py extension
        r'^pip\s+install',  # pip commands
        r'^\s*$',  # Empty or whitespace only
        r'^__',  # Python internals
        r'^\d+$',  # Just numbers
    ]

    for pattern in invalid_patterns:
        if re.match(pattern, name, re.IGNORECASE):
            return False

    # Node names should be non-empty and contain valid characters
    if not name or len(name) < 2:
        return False

    return True


def extract_from_ast(file_path: str) -> list[str]:
    """Extract NODE_CLASS_MAPPINGS using AST parsing."""
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        tree = ast.parse(content, filename=file_path)
        node_names = []

        for node in ast.walk(tree):
            # Look for NODE_CLASS_MAPPINGS = {...} assignments
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "NODE_CLASS_MAPPINGS":
                        if isinstance(node.value, ast.Dict):
                            # Extract string keys from the dictionary
                            for key in node.value.keys:
                                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                    name = key.value.strip()  # Remove any surrounding whitespace
                                    if is_valid_node_name(name):
                                        node_names.append(name)
                                elif isinstance(key, ast.Str):  # Python 3.7 compatibility
                                    name = key.s.strip()
                                    if is_valid_node_name(name):
                                        node_names.append(name)

        return node_names
    except Exception:
        # If AST parsing fails, return empty list
        return []


def extract_comfynode_from_ast(file_path: str) -> list[str]:
    """Extract nodes using the new io.ComfyNode pattern."""
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        tree = ast.parse(content, filename=file_path)
        node_names = []

        # Find classes that inherit from io.ComfyNode or similar
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Check if class inherits from ComfyNode
                for base in node.bases:
                    base_name = ""
                    if isinstance(base, ast.Attribute):
                        base_name = base.attr
                    elif isinstance(base, ast.Name):
                        base_name = base.id

                    if "ComfyNode" in base_name:
                        # Look for define_schema method and extract node_id
                        for item in node.body:
                            if isinstance(item, ast.FunctionDef) and item.name == "define_schema":
                                # Walk through the function body looking for node_id
                                for func_node in ast.walk(item):
                                    if isinstance(func_node, ast.keyword) and func_node.arg == "node_id":
                                        if isinstance(func_node.value, ast.Constant):
                                            name = func_node.value.value
                                            if is_valid_node_name(str(name)):
                                                node_names.append(name)
                                        elif isinstance(func_node.value, ast.Str):  # Python 3.7
                                            name = func_node.value.s
                                            if is_valid_node_name(name):
                                                node_names.append(name)

        return node_names
    except Exception:
        # If AST parsing fails, return empty list
        return []


def extract_from_regex(file_path: str) -> list[str]:
    """Extract NODE_CLASS_MAPPINGS using regex as fallback."""
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        # Find NODE_CLASS_MAPPINGS = { ... }
        # Use a more precise pattern that looks for the assignment
        pattern = r'NODE_CLASS_MAPPINGS\s*=\s*\{'
        match = re.search(pattern, content)

        if not match:
            return []

        # Start from the opening brace
        start_pos = match.end() - 1  # Include the opening brace

        # Find the matching closing brace by counting braces
        brace_count = 0
        end_pos = start_pos
        in_string = False
        string_char = None

        for i, char in enumerate(content[start_pos:], start_pos):
            # Handle string literals to avoid counting braces inside strings
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

        # Extract string keys from the dictionary
        # Look for patterns like "NodeName": or 'NodeName':
        key_patterns = [
            r'"([^"]+)"\s*:',  # Double quoted keys
            r"'([^']+)'\s*:",  # Single quoted keys
        ]

        node_names = []
        for pattern in key_patterns:
            matches = re.finditer(pattern, dict_content)
            for match in matches:
                name = match.group(1).strip()
                if is_valid_node_name(name) and name not in node_names:
                    node_names.append(name)

        return node_names

    except Exception:
        return []


def extract_comfynode_from_regex(file_path: str) -> list[str]:
    """Extract io.ComfyNode nodes using regex as fallback."""
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        node_names = []

        # Look for multiple patterns for node definitions
        patterns = [
            r'node_id\s*=\s*"([^"]+)"',          # node_id="NodeName"
            r"node_id\s*=\s*'([^']+)'",          # node_id='NodeName'
            r'NodeId\s*=\s*"([^"]+)"',           # NodeId="NodeName"
            r"NodeId\s*=\s*'([^']+)'",           # NodeId='NodeName'
            r'schema\.node_id\s*=\s*"([^"]+)"',  # schema.node_id="NodeName"
            r"schema\.node_id\s*=\s*'([^']+)'",  # schema.node_id='NodeName'
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                name = match.group(1).strip()
                if is_valid_node_name(name) and name not in node_names:
                    node_names.append(name)

        return node_names

    except Exception:
        return []


def extract_node_names(file_path: str) -> tuple[list[str], str | None]:
    """
    Extract node names from a Python file using both traditional and new patterns.
    Combines NODE_CLASS_MAPPINGS and io.ComfyNode patterns.
    """
    all_nodes = []

    # Try traditional NODE_CLASS_MAPPINGS pattern
    node_names = extract_from_ast(file_path)

    # If AST parsing found nothing or very few nodes, try regex
    if len(node_names) < 3:  # Arbitrary threshold
        regex_names = extract_from_regex(file_path)
        if len(regex_names) > len(node_names):
            node_names = regex_names

    all_nodes.extend(node_names)

    # Try new io.ComfyNode pattern with AST
    comfynode_names = extract_comfynode_from_ast(file_path)
    all_nodes.extend(comfynode_names)

    # Always also try regex for io.ComfyNode patterns
    # This catches cases where subclasses define node_id differently
    comfynode_regex_names = extract_comfynode_from_regex(file_path)
    all_nodes.extend(comfynode_regex_names)

    # Remove duplicates and sort
    unique_names = sorted(set(all_nodes))

    if unique_names:
        return unique_names, None
    else:
        return [], None


def discover_node_files(directory: Path) -> list[Path]:
    """Discover Python files that likely contain node definitions."""
    if not directory.exists():
        return []

    node_files = []

    # Look for all .py files that might contain nodes
    # Exclude common non-node files
    exclude_patterns = ['__init__', '__pycache__', 'test_', 'setup', 'config']

    for file in directory.iterdir():
        if file.is_file() and file.suffix == '.py':
            # Skip files matching exclude patterns
            if any(pattern in file.name.lower() for pattern in exclude_patterns):
                continue
            node_files.append(file)

    return sorted(node_files)


def get_frontend_and_custom_nodes() -> dict:
    """Get known frontend-only and native custom nodes."""
    return {
        'source': 'known_frontend_and_custom',
        'nodes': [
            'MarkdownNote',      # Frontend-only UI node
            'Note',              # Frontend-only UI node
            'PrimitiveNode',     # Frontend-only UI node
            'Reroute',           # Frontend-only UI node
            'SaveImageWebsocket' # Native custom node from websocket_image_save.py
        ],
        'count': 5,
        'description': 'Frontend-only UI nodes and native custom nodes that exist in ComfyUI but are not backend-defined'
    }


def extract_custom_nodes(comfyui_path: Path, quiet: bool = False) -> dict:
    """Extract nodes from custom_nodes directory."""
    custom_dir = comfyui_path / 'custom_nodes'
    if not custom_dir.exists():
        return {}

    custom_all = []
    custom_by_file = {}

    # Look for .py files directly in custom_nodes
    for file_path in custom_dir.glob('*.py'):
        if file_path.name.startswith('__'):
            continue
        nodes, _ = extract_node_names(str(file_path))
        if nodes:
            custom_by_file[file_path.name] = nodes
            custom_all.extend(nodes)
            if not quiet:
                print(f"   {file_path.name}: {len(nodes)} nodes")

    if custom_all:
        return {
            'source': 'custom_nodes',
            'nodes': sorted(set(custom_all)),
            'count': len(set(custom_all)),
            'by_file': custom_by_file
        }
    return {}


def extract_nodes_from_comfyui(comfyui_path: Path, quiet: bool = False) -> tuple[dict, list]:
    """Extract all built-in nodes from a ComfyUI installation."""
    all_nodes = {}
    errors = []

    # Extract from core nodes.py
    nodes_file = comfyui_path / 'nodes.py'
    if nodes_file.exists():
        if not quiet:
            print("\n📋 Processing core nodes.py...")
        core_nodes, error = extract_node_names(str(nodes_file))
        if error:
            errors.append(('nodes.py', error))
        elif core_nodes:
            all_nodes['core'] = {
                'source': 'nodes.py',
                'nodes': core_nodes,
                'count': len(core_nodes)
            }
            if not quiet:
                print(f"   Found {len(core_nodes)} nodes")
    elif not quiet:
        print(f"⚠️  Warning: nodes.py not found at {nodes_file}")

    # Process comfy_extras directory
    extras_dir = comfyui_path / 'comfy_extras'
    if extras_dir.exists():
        if not quiet:
            print(f"\n🔧 Processing {extras_dir.name}/ directory...")
        extras_all = []
        extras_by_file = {}

        for file_path in discover_node_files(extras_dir):
            nodes, error = extract_node_names(str(file_path))

            if error:
                errors.append((str(file_path), error))
            elif nodes:
                extras_by_file[file_path.name] = nodes
                extras_all.extend(nodes)
                if not quiet:
                    print(f"   {file_path.name}: {len(nodes)} nodes")

        if extras_all:
            all_nodes['extras'] = {
                'source': 'comfy_extras',
                'nodes': sorted(set(extras_all)),
                'count': len(set(extras_all)),
                'by_file': extras_by_file
            }

    # Process comfy_api_nodes directory
    api_dir = comfyui_path / 'comfy_api_nodes'
    if api_dir.exists():
        if not quiet:
            print(f"\n🌐 Processing {api_dir.name}/ directory...")
        api_all = []
        api_by_file = {}

        for file_path in discover_node_files(api_dir):
            nodes, error = extract_node_names(str(file_path))

            if error:
                errors.append((str(file_path), error))
            elif nodes:
                api_by_file[file_path.name] = nodes
                api_all.extend(nodes)
                if not quiet:
                    print(f"   {file_path.name}: {len(nodes)} nodes")

        if api_all:
            all_nodes['api'] = {
                'source': 'comfy_api_nodes',
                'nodes': sorted(set(api_all)),
                'count': len(set(api_all)),
                'by_file': api_by_file
            }

    # Check for native custom nodes
    if not quiet:
        print("\n🔌 Checking custom_nodes directory...")
    custom_nodes = extract_custom_nodes(comfyui_path, quiet)
    if custom_nodes:
        all_nodes['custom'] = custom_nodes

    # Add known frontend-only and native custom nodes
    all_nodes['frontend'] = get_frontend_and_custom_nodes()
    if not quiet:
        print(f"\n🖼️  Including {all_nodes['frontend']['count']} known frontend/custom nodes")

    return all_nodes, errors


def create_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser."""
    parser = argparse.ArgumentParser(
        description='Extract built-in ComfyUI nodes by parsing NODE_CLASS_MAPPINGS',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract from specific ComfyUI installation
  python extract_builtin_nodes.py --path /path/to/ComfyUI --output /output/builtin_nodes.json

  # Use current directory as ComfyUI path
  python extract_builtin_nodes.py --output ./builtin_nodes.json

  # Use all defaults (current dir, output to comfyui_builtin_nodes.json)
  python extract_builtin_nodes.py
"""
    )

    parser.add_argument(
        '--path',
        type=str,
        default='.',
        help='Path to ComfyUI directory (default: current directory)'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='comfyui_builtin_nodes.json',
        help='Output JSON file path (default: comfyui_builtin_nodes.json)'
    )

    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress progress output'
    )

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()

    # Convert paths to Path objects
    comfyui_path = Path(args.path).resolve()
    output_path = Path(args.output).resolve()

    # Validate ComfyUI path
    if not comfyui_path.exists():
        print(f"❌ Error: ComfyUI path does not exist: {comfyui_path}", file=sys.stderr)
        return 1

    if not comfyui_path.is_dir():
        print(f"❌ Error: ComfyUI path is not a directory: {comfyui_path}", file=sys.stderr)
        return 1

    # Check for nodes.py as a basic validation
    if not (comfyui_path / 'nodes.py').exists():
        print(f"⚠️  Warning: nodes.py not found in {comfyui_path}")
        print("   This may not be a valid ComfyUI directory")
        response = input("   Continue anyway? (y/N): ")
        if response.lower() != 'y':
            return 1

    if not args.quiet:
        print(f"🔍 Extracting built-in ComfyUI nodes from: {comfyui_path}")

    # Extract nodes
    all_nodes, errors = extract_nodes_from_comfyui(comfyui_path, quiet=args.quiet)

    # Combine all unique node names
    all_builtin = set()
    for category_data in all_nodes.values():
        all_builtin.update(category_data['nodes'])

    all_builtin_list = sorted(all_builtin)

    # Create output structure
    output = {
        'metadata': {
            'description': 'Built-in ComfyUI node mappings',
            'extraction_date': datetime.now().isoformat(),
            'comfyui_path': str(comfyui_path),
            'total_nodes': len(all_builtin_list),
            'categories': list(all_nodes.keys())
        },
        'nodes_by_category': all_nodes,
        'all_builtin_nodes': all_builtin_list
    }

    if errors:
        output['errors'] = [{'file': f, 'error': e} for f, e in errors]

    # Create output directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save to file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    if not args.quiet:
        # Print summary
        print("\n" + "="*50)
        print("📊 EXTRACTION SUMMARY")
        print("="*50)

        for category, data in all_nodes.items():
            print(f"\n{category.upper()}:")
            print(f"  Source: {data['source']}")
            print(f"  Nodes: {data['count']}")
            if 'description' in data:
                print(f"  Description: {data['description']}")
            if 'by_file' in data:
                print(f"  Files: {len(data['by_file'])}")

        print(f"\n📈 TOTAL UNIQUE NODES: {len(all_builtin_list)}")

        if errors:
            print(f"\n⚠️  Errors encountered: {len(errors)}")

        print(f"\n💾 Results saved to: {output_path}")

        # Show sample nodes
        if all_builtin_list:
            print("\n📝 Sample nodes:")
            for node in all_builtin_list[:10]:
                print(f"   • {node}")
            if len(all_builtin_list) > 10:
                print(f"   ... and {len(all_builtin_list) - 10} more")

    return 0


if __name__ == "__main__":
    exit(main())
