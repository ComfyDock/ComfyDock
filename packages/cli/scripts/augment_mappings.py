#!/usr/bin/env python3
"""Augment node mappings with ComfyUI Manager's extension-node-map data.

This script enhances the ComfyUI registry node mappings by filling in missing node data
from ComfyUI Manager's extension-node-map.json file. It both augments existing registry
packages and creates synthetic packages for Manager-only extensions.

BEHAVIOR:
- Augments packages that exist in the registry (matched by GitHub URL)
- Creates synthetic packages for Manager-only extensions (prefixed with "github_")
- Adds node mappings with unknown input signatures (marked with "_")
- Skips nodes that already exist or conflict with other packages
- Preserves existing mappings with real input signatures over Manager's name-only data

HOW IT WORKS:
1. Loads existing node_mappings.json and extension-node-map.json
2. First pass: Augments registry packages with Manager node data
3. Second pass: Creates synthetic packages for Manager-only extensions:
   - Generates package ID like "github_author_repo"
   - Extracts metadata from Manager extension data
   - Adds node mappings for synthetic packages
4. Saves augmented mappings with both registry and synthetic packages

USAGE:
    # Basic usage (overwrites input file)
    uv run python scripts/augment_mappings.py

    # Custom files
    uv run python scripts/augment_mappings.py \\
        --mappings path/to/node_mappings.json \\
        --manager path/to/extension-node-map.json \\
        --output path/to/augmented.json

    # With debug logging
    uv run python scripts/augment_mappings.py --log-level DEBUG

EXAMPLE OUTPUT:
    Registry package augmentation:
    "FaceShaper::_": { "package_id": "ComfyUI_FaceShaper", "versions": [], "source": "manager" }

    Synthetic package creation:
    "github_IIEleven11_ComfyUI-FairyTaler": {
        "display_name": "ComfyUI-FairyTaler",
        "author": "IIEleven11",
        "repository": "https://github.com/IIEleven11/ComfyUI-FairyTaler",
        "synthetic": true,
        "source": "manager"
    }

IMPROVEMENTS:
- Now includes Manager-only extensions as synthetic packages
- Provides complete node coverage from both registry and community sources
- Enables workflow analysis for nodes not yet in the registry
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from comfygit_core.logging.logging_config import get_logger, setup_logging
from comfygit_core.workflow import create_node_key

logger = get_logger(__name__)


def normalize_github_url(url: str) -> str:
    """Normalize GitHub URL for consistent matching."""
    # Remove trailing .git
    url = url.rstrip('/')
    if url.endswith('.git'):
        url = url[:-4]

    # Parse and rebuild to ensure consistent format
    parsed = urlparse(url.lower())
    # Keep only scheme, netloc, and path
    normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))

    return normalized


class MappingsAugmenter:
    """Augments node mappings with ComfyUI Manager data."""

    def __init__(self, mappings_file: Path, manager_file: Path):
        self.mappings_file = mappings_file
        self.manager_file = manager_file
        self.mappings_data = None
        self.manager_data = None
        self.stats = {
            'nodes_added': 0,
            'nodes_skipped_exists': 0,
            'nodes_skipped_conflict': 0,
            'packages_augmented': set(),
            'packages_not_found': set(),
            'synthetic_packages_created': set(),
            'total_manager_nodes': 0
        }

    def load_data(self):
        """Load both data files."""
        # Load existing mappings
        with open(self.mappings_file) as f:
            self.mappings_data = json.load(f)
        logger.info(f"Loaded {len(self.mappings_data['mappings'])} mappings, {len(self.mappings_data['packages'])} packages")

        # Load manager extension map
        with open(self.manager_file) as f:
            self.manager_data = json.load(f)
        logger.info(f"Loaded {len(self.manager_data)} extensions from Manager")

    def build_url_to_package_map(self) -> dict[str, str]:
        """Build mapping from GitHub URLs to package IDs."""
        url_map = {}

        for package_id, package_info in self.mappings_data['packages'].items():
            repo_url = package_info.get('repository', '')
            if repo_url and 'github.com' in repo_url.lower():
                normalized_url = normalize_github_url(repo_url)
                url_map[normalized_url] = package_id

        logger.info(f"Built URL map with {len(url_map)} GitHub repositories")
        return url_map

    def extract_github_parts(self, github_url: str) -> tuple[str, str] | None:
        """Extract author and repo name from GitHub URL."""
        normalized = normalize_github_url(github_url)

        # Extract from normalized URL like https://github.com/author/repo
        parts = normalized.replace('https://github.com/', '').split('/')
        if len(parts) >= 2:
            return parts[0], parts[1]
        return None

    def create_synthetic_package(self, github_url: str, extension_data: list) -> str | None:
        """Create a synthetic package entry for a Manager-only extension."""
        github_parts = self.extract_github_parts(github_url)
        if not github_parts:
            logger.debug(f"Could not extract GitHub parts from {github_url}")
            return None

        author, repo = github_parts

        # Create synthetic package ID
        package_id = f"github_{author}_{repo}"

        # Skip if synthetic package already exists
        if package_id in self.mappings_data['packages']:
            return package_id

        # Extract metadata if available
        metadata = extension_data[1] if len(extension_data) > 1 and isinstance(extension_data[1], dict) else {}

        # Create synthetic package entry
        self.mappings_data['packages'][package_id] = {
            'display_name': metadata.get('title', repo),
            'author': metadata.get('author', author),
            'description': metadata.get('description', ''),
            'repository': github_url,
            'synthetic': True,  # Mark as synthetic
            'source': 'manager',  # Track source
            'versions': {}  # No version info available
        }

        self.stats['synthetic_packages_created'].add(package_id)
        logger.info(f"Created synthetic package: {package_id}")
        return package_id

    def augment_mappings(self):
        """Augment mappings with Manager data."""
        url_to_package = self.build_url_to_package_map()
        packages_not_found = {}  # Store for second pass

        # First pass: Process extensions that exist in registry
        for github_url, extension_data in self.manager_data.items():
            # Skip non-GitHub entries
            if 'github.com' not in github_url.lower():
                continue

            normalized_url = normalize_github_url(github_url)
            package_id = url_to_package.get(normalized_url)

            if not package_id:
                # Store for second pass to create synthetic packages
                packages_not_found[github_url] = extension_data
                continue

            # Extract node list (first element of the array)
            if not isinstance(extension_data, list) or len(extension_data) < 1:
                continue

            node_list = extension_data[0]
            if not isinstance(node_list, list):
                continue

            self.stats['total_manager_nodes'] += len(node_list)

            # Process each node type
            nodes_added_for_package = 0
            for node_type in node_list:
                if not isinstance(node_type, str):
                    continue

                # Create node key with unknown signature
                node_key = create_node_key(node_type, "_")

                # Check if this key already exists
                if node_key in self.mappings_data['mappings']:
                    existing = self.mappings_data['mappings'][node_key]
                    if existing['package_id'] == package_id:
                        # Same package, already tracked
                        self.stats['nodes_skipped_exists'] += 1
                    else:
                        # Different package, conflict
                        self.stats['nodes_skipped_conflict'] += 1
                        logger.debug(f"Conflict: {node_type} exists in {existing['package_id']}, skipping for {package_id}")
                else:
                    # Add new mapping
                    self.mappings_data['mappings'][node_key] = {
                        'package_id': package_id,
                        'versions': [],  # Empty versions since we don't know
                        'source': 'manager'  # Track where this came from
                    }
                    self.stats['nodes_added'] += 1
                    nodes_added_for_package += 1
                    logger.debug(f"Added {node_type} -> {package_id}")

            if nodes_added_for_package > 0:
                self.stats['packages_augmented'].add(package_id)
                logger.info(f"Augmented {package_id} with {nodes_added_for_package} nodes")

        # Second pass: Create synthetic packages for Manager-only extensions
        logger.info(f"Creating synthetic packages for {len(packages_not_found)} Manager-only extensions...")
        for github_url, extension_data in packages_not_found.items():
            # Extract node list
            if not isinstance(extension_data, list) or len(extension_data) < 1:
                continue

            node_list = extension_data[0]
            if not isinstance(node_list, list):
                continue

            # Create synthetic package
            package_id = self.create_synthetic_package(github_url, extension_data)
            if not package_id:
                self.stats['packages_not_found'].add(github_url)
                continue

            self.stats['total_manager_nodes'] += len(node_list)

            # Add node mappings for synthetic package
            nodes_added_for_package = 0
            for node_type in node_list:
                if not isinstance(node_type, str):
                    continue

                node_key = create_node_key(node_type, "_")

                # Check for conflicts
                if node_key in self.mappings_data['mappings']:
                    existing = self.mappings_data['mappings'][node_key]
                    if existing['package_id'] != package_id:
                        self.stats['nodes_skipped_conflict'] += 1
                        logger.debug(f"Conflict: {node_type} exists in {existing['package_id']}, skipping for synthetic {package_id}")
                        continue
                    else:
                        self.stats['nodes_skipped_exists'] += 1
                        continue

                # Add mapping for synthetic package
                self.mappings_data['mappings'][node_key] = {
                    'package_id': package_id,
                    'versions': [],
                    'source': 'manager',
                    'synthetic': True
                }
                self.stats['nodes_added'] += 1
                nodes_added_for_package += 1
                logger.debug(f"Added {node_type} -> synthetic {package_id}")

            if nodes_added_for_package > 0:
                logger.info(f"Synthetic package {package_id} mapped {nodes_added_for_package} nodes")

    def save_augmented_mappings(self, output_file: Path):
        """Save the augmented mappings."""
        # Update stats
        self.mappings_data['stats']['augmented'] = True
        self.mappings_data['stats']['augmentation_date'] = datetime.now().isoformat()
        self.mappings_data['stats']['nodes_from_manager'] = self.stats['nodes_added']
        self.mappings_data['stats']['signatures'] = len(self.mappings_data['mappings'])
        self.mappings_data['stats']['packages'] = len(self.mappings_data['packages'])
        self.mappings_data['stats']['synthetic_packages'] = len(self.stats['synthetic_packages_created'])

        # Sort mappings for deterministic output
        self.mappings_data['mappings'] = dict(sorted(self.mappings_data['mappings'].items()))

        # Atomic write
        temp_file = Path(str(output_file) + '.tmp')
        try:
            with open(temp_file, 'w') as f:
                json.dump(self.mappings_data, f, indent=2)
            temp_file.replace(output_file)
            logger.info(f"Saved augmented mappings to {output_file}")
        finally:
            if temp_file.exists():
                temp_file.unlink()

    def print_summary(self):
        """Print augmentation summary."""
        print("\n" + "=" * 60)
        print("📊 AUGMENTATION SUMMARY")
        print("=" * 60)
        print(f"Total Manager nodes processed: {self.stats['total_manager_nodes']}")
        print(f"Nodes added: {self.stats['nodes_added']}")
        print(f"Nodes skipped (already exists): {self.stats['nodes_skipped_exists']}")
        print(f"Nodes skipped (conflicts): {self.stats['nodes_skipped_conflict']}")
        print(f"Registry packages augmented: {len(self.stats['packages_augmented'])}")
        print(f"Synthetic packages created: {len(self.stats['synthetic_packages_created'])}")
        print(f"Packages failed to process: {len(self.stats['packages_not_found'])}")
        print("=" * 60)

        if self.stats['synthetic_packages_created']:
            print(f"\n✨ Created {len(self.stats['synthetic_packages_created'])} synthetic packages from Manager-only extensions")

        if self.stats['packages_not_found'] and logger.isEnabledFor(10):  # DEBUG level
            print("\nPackages that couldn't be processed (first 10):")
            for url in list(self.stats['packages_not_found'])[:10]:
                print(f"  - {url}")


def main():
    parser = argparse.ArgumentParser(description="Augment node mappings with ComfyUI Manager data")
    parser.add_argument(
        '--mappings',
        type=Path,
        default=Path('src/comfygit_core/data/node_mappings.json'),
        help='Path to existing node_mappings.json'
    )
    parser.add_argument(
        '--manager',
        type=Path,
        default=Path('src/comfygit_core/data/extension-node-map.json'),
        help='Path to ComfyUI Manager extension-node-map.json'
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Output file (default: overwrite input mappings file)'
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        help='Logging level'
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(level=args.log_level, log_file=None, simple_format=True, console_level=args.log_level)

    # Default output to input file (in-place update)
    if not args.output:
        args.output = args.mappings

    # Validate input files exist
    if not args.mappings.exists():
        parser.error(f"Mappings file not found: {args.mappings}")
    if not args.manager.exists():
        parser.error(f"Manager file not found: {args.manager}")

    # Run augmentation
    augmenter = MappingsAugmenter(args.mappings, args.manager)
    augmenter.load_data()
    augmenter.augment_mappings()
    augmenter.save_augmented_mappings(args.output)
    augmenter.print_summary()


if __name__ == '__main__':
    main()
