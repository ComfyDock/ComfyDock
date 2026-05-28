#!/usr/bin/env python3
"""Build global node mappings from cached registry data."""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from comfygit_core.logging.logging_config import get_logger, setup_logging
from comfygit_core.workflow import (
    create_node_key,
    normalize_registry_inputs,
)

logger = get_logger(__name__)


class GlobalMappingsBuilder:
    """Builds global node mappings from cached registry data."""

    def __init__(self):
        self.mappings = {}  # node_key -> {package_id, versions[]}
        self.packages = {}  # package_id -> package metadata
        self.total_nodes = 0
        self.total_signatures = 0

    def build_mappings(self, registry_cache: Path) -> dict:
        """Build mappings from cached registry data."""
        start_time = time.time()
        logger.info("Starting mappings build from cache")

        # Load registry cache
        if not registry_cache.exists():
            logger.error(f"Registry cache not found: {registry_cache}")
            return {}

        with open(registry_cache) as f:
            cache_data = json.load(f)

        nodes = cache_data.get("nodes", [])
        cached_at = cache_data.get("cached_at", "")
        metadata_entries = cache_data.get("metadata_entries", 0)

        logger.info(f"Loaded cache: {len(nodes)} nodes, {metadata_entries} metadata entries (cached at: {cached_at})")

        # Process all nodes
        for i, node in enumerate(nodes, 1):
            if i % 100 == 0:
                logger.info(f"Processing node {i}/{len(nodes)}...")

            self._process_node(node)

        # Build stats
        elapsed = time.time() - start_time
        logger.info("=" * 60)
        logger.info("📊 BUILD SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total packages processed: {len(self.packages)}")
        logger.info(f"Node signatures collected: {len(self.mappings)}")
        logger.info(f"Total nodes mapped: {self.total_nodes}")
        logger.info(f"Build time: {elapsed:.1f}s")
        logger.info("=" * 60)

        # Return complete data structure
        return {
            "version": datetime.now().strftime("%Y.%m.%d"),
            "generated_at": datetime.now().isoformat(),
            "stats": {
                "packages": len(self.packages),
                "signatures": len(self.mappings),
                "total_nodes": self.total_nodes
            },
            "mappings": self.mappings,
            "packages": self.packages
        }

    def _process_node(self, node: dict):
        """Process a single node package from cache."""
        package_id = node["id"]

        # Store package metadata (only once per package)
        if package_id not in self.packages:
            self.packages[package_id] = {
                "display_name": node.get("name", package_id),
                "author": node.get("author", ""),
                "description": node.get("description", ""),
                "repository": node.get("repository", ""),
                "downloads": node.get("downloads", 0),
                "github_stars": node.get("github_stars", 0),
                "rating": node.get("rating", 0),
                "license": node.get("license", ""),
                "category": node.get("category", ""),
                "tags": node.get("tags", []),
                "status": node.get("status", ""),
                "created_at": node.get("created_at", ""),
                "versions": {}  # version -> metadata
            }

        # Process versions
        versions_list = node.get("versions_list", [])
        if not versions_list:
            logger.debug(f"No versions for {package_id}")
            return

        # Process each version
        for version_info in versions_list:
            version = version_info["version"]

            # Skip deprecated versions for node mappings
            skip_for_mappings = version_info.get("deprecated", False)

            # Store version metadata (excluding comfy_nodes)
            version_metadata = {
                "version": version,
                "changelog": version_info.get("changelog", ""),
                "release_date": version_info.get("createdAt", ""),
                "dependencies": version_info.get("dependencies", []),
                "deprecated": version_info.get("deprecated", False),
                "download_url": version_info.get("download_url", version_info.get("downloadUrl", "")),
                "status": version_info.get("status", ""),
                "supported_accelerators": version_info.get("supported_accelerators"),
                "supported_comfyui_version": version_info.get("supported_comfyui_version", ""),
                "supported_os": version_info.get("supported_os")
            }

            # Add to package versions
            self.packages[package_id]["versions"][version] = version_metadata

            # Process comfy-nodes metadata for mappings (skip deprecated versions)
            if not skip_for_mappings:
                comfy_nodes = version_info.get("comfy_nodes", [])
                if comfy_nodes:
                    self._process_comfy_nodes(package_id, version, comfy_nodes)

        # Sort versions dictionary by version number (highest first)
        # Use semantic version sorting
        versions_dict = self.packages[package_id]["versions"]
        sorted_versions = sorted(
            versions_dict.items(),
            key=lambda x: self._parse_version(x[0]),
            reverse=True  # Highest/newest first
        )
        self.packages[package_id]["versions"] = dict(sorted_versions)

    def _parse_version(self, version_str: str) -> tuple:
        """Parse version string for sorting.

        Returns tuple of integers for proper semantic version sorting.
        Examples: "1.2.3" -> (1, 2, 3), "2.0.0-beta1" -> (2, 0, 0)
        """
        # Remove any pre-release suffixes for now
        base_version = version_str.split('-')[0].split('+')[0]

        # Split by dots and convert to integers
        try:
            parts = []
            for part in base_version.split('.'):
                try:
                    parts.append(int(part))
                except ValueError:
                    # Handle non-numeric parts by using 0
                    parts.append(0)
            # Pad with zeros to ensure consistent length for comparison
            while len(parts) < 3:
                parts.append(0)
            return tuple(parts)
        except Exception:
            # Fallback to string comparison
            return (0, 0, 0)

    def _process_comfy_nodes(self, package_id: str, version: str, comfy_nodes: list[dict]):
        """Process comfy-nodes metadata and create mappings."""
        for node_data in comfy_nodes:
            display_name = node_data.get("comfy_node_name", "")
            if not display_name:
                continue

            # Parse and normalize inputs
            input_types_str = node_data.get("input_types", "")
            normalized_inputs = ""

            if input_types_str:
                try:
                    # input_types might be string or already parsed dict
                    if isinstance(input_types_str, str):
                        normalized_inputs = normalize_registry_inputs(input_types_str)
                    elif isinstance(input_types_str, dict):
                        # Already parsed, convert back to string and normalize
                        normalized_inputs = normalize_registry_inputs(json.dumps(input_types_str))
                except Exception as e:
                    logger.debug(f"Failed to normalize inputs for {display_name}: {e}")
                    normalized_inputs = ""

            # Create node key
            node_key = create_node_key(display_name, normalized_inputs)

            # Add to mappings (aggregate versions)
            # TODO: Allow for multiple packages per node (rank by downloads?)
            if node_key not in self.mappings:
                self.mappings[node_key] = {
                    "package_id": package_id,
                    "versions": []
                }
                self.total_signatures += 1

            # Add version if not already present
            if version not in self.mappings[node_key]["versions"]:
                self.mappings[node_key]["versions"].append(version)

            self.total_nodes += 1


def main():
    parser = argparse.ArgumentParser(
        description="Build global node mappings from registry cache",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run scripts/build_global_mappings.py \\
    --cache registry_cache.json \\
    --output node_mappings.json
        """
    )

    parser.add_argument(
        "--cache",
        "-c",
        type=Path,
        required=True,
        help="Registry cache file (from build_registry_cache.py)"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Output mappings file"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level"
    )

    args = parser.parse_args()
    setup_logging(level=args.log_level, simple_format=True)

    # Build mappings
    builder = GlobalMappingsBuilder()
    data = builder.build_mappings(registry_cache=args.cache)

    if not data:
        logger.error("Failed to build mappings")
        return 1

    # Save results
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(data, f, indent=2)

        file_size = args.output.stat().st_size / 1024 / 1024
        logger.info(f"✅ Mappings saved to {args.output} ({file_size:.1f} MB)")

    except Exception as e:
        logger.error(f"Failed to save mappings: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main() or 0)
