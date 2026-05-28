"""Custom-node manifest helpers."""
from __future__ import annotations

import hashlib
import re

import tomlkit

from ..logging.logging_config import get_logger
from ..models.shared import NodeInfo, normalize_node_criticality
from .base import BaseHandler

logger = get_logger(__name__)


class NodeHandler(BaseHandler):
    """Handles custom node management."""

    def add(self, node_info: NodeInfo, node_identifier: str | None) -> None:
        """Add a custom node to the pyproject.toml."""
        config = self.load()
        identifier = node_identifier or (node_info.registry_id if node_info.registry_id else node_info.name)

        # Only create nodes section when actually adding a node
        self.ensure_section(config, 'tool', 'comfygit', 'nodes')

        # Build node data, excluding any None values (tomlkit requirement)
        filtered_data = {k: v for k, v in node_info.__dict__.copy().items() if v is not None}

        # Create a proper tomlkit table for better formatting
        node_table = tomlkit.table()
        for key, value in filtered_data.items():
            node_table[key] = value

        # Add node to configuration
        config['tool']['comfygit']['nodes'][identifier] = node_table

        logger.info(f"Added custom node: {identifier}")
        self.save(config)

    def get_existing(self) -> dict[str, NodeInfo]:
        """Get all existing custom nodes from pyproject.toml."""
        config = self.load()
        nodes_data = config.get('tool', {}).get('comfygit', {}).get('nodes', {})

        result = {}
        for identifier, node_data in nodes_data.items():
            result[identifier] = NodeInfo(
                name=node_data.get('name') or identifier,
                repository=node_data.get('repository'),
                registry_id=node_data.get('registry_id'),
                version=node_data.get('version'),
                source=node_data.get('source', 'unknown'),
                download_url=node_data.get('download_url'),
                dependency_sources=node_data.get('dependency_sources'),
                criticality=node_data.get('criticality', 'required'),
                branch=node_data.get('branch'),
                pinned_commit=node_data.get('pinned_commit'),
            )

        return result

    def set_criticality(self, node_identifier: str, criticality: str) -> bool:
        """Set package-level custom-node criticality.

        Criticality is intentionally user-declared package metadata. Workflow graph
        analysis must not infer or mutate it.
        """
        normalized = normalize_node_criticality(criticality)
        config = self.load()
        nodes = config.get('tool', {}).get('comfygit', {}).get('nodes', {})

        if node_identifier not in nodes:
            return False

        nodes[node_identifier]['criticality'] = normalized
        self.save(config)
        logger.debug("Set custom node criticality: %s -> %s", node_identifier, normalized)
        return True

    def remove(self, node_identifier: str) -> bool:
        """Remove a custom node and its associated dependency group."""
        config = self.load()
        removed = False

        # Get existing nodes to find the one to remove
        existing_nodes = self.get_existing()
        if node_identifier not in existing_nodes:
            return False

        node_info = existing_nodes[node_identifier]

        # Generate the hash-based group name that was used during add
        fallback_identifier = node_info.registry_id if node_info.registry_id else node_info.name
        group_name = self.generate_group_name(node_info, fallback_identifier)

        # Remove from dependency-groups using the hash-based group name
        if 'dependency-groups' in config and group_name in config['dependency-groups']:
            del config['dependency-groups'][group_name]
            removed = True
            logger.debug(f"Removed dependency group: {group_name}")

        # Remove from nodes using the original identifier
        if ('tool' in config and 'comfygit' in config['tool'] and
            'nodes' in config['tool']['comfygit'] and
            node_identifier in config['tool']['comfygit']['nodes']):
            del config['tool']['comfygit']['nodes'][node_identifier]
            removed = True
            logger.debug(f"Removed node info: {node_identifier}")

        if removed:
            # Clean up empty sections
            self.clean_empty_sections(config, 'tool', 'comfygit', 'nodes')
            self.save(config)
            logger.info(f"Removed custom node: {node_identifier}")

        return removed

    @staticmethod
    def generate_group_name(node_info: NodeInfo, fallback_identifier: str) -> str:
        """Generate a collision-resistant group name for a custom node."""
        # Use node name as base, fallback to identifier
        base_name = node_info.name or fallback_identifier

        # Normalize the base name (similar to what UV would do)
        normalized = re.sub(r'[^a-z0-9]+', '-', base_name.lower()).strip('-')

        # Generate hash from repository URL (most unique identifier) or fallback
        hash_source = node_info.repository or fallback_identifier
        hash_digest = hashlib.sha256(hash_source.encode()).hexdigest()[:8]

        return f"{normalized}-{hash_digest}"


# DevNodeHandler removed - development nodes now handled by NodeHandler with version='dev'
