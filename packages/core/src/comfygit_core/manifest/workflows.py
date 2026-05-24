"""Workflow manifest helpers."""
from __future__ import annotations

import tomlkit

from ..logging.logging_config import get_logger
from ..models.manifest import ManifestWorkflowModel
from ..models.workflow_contract import WorkflowExecutionContract
from .base import BaseHandler

logger = get_logger(__name__)


class WorkflowHandler(BaseHandler):
    """Handles workflow model resolutions and tracking."""

    @staticmethod
    def _ensure_workflow_entry(config: dict, workflow_name: str) -> dict:
        """Ensure workflow table and path exist, then return the workflow table."""
        workflows = config.setdefault('tool', {}).setdefault('comfygit', {}).setdefault('workflows', {})
        workflow = workflows.get(workflow_name)

        if workflow is None:
            workflow = tomlkit.table()
            workflows[workflow_name] = workflow

        if 'path' not in workflow:
            workflow['path'] = f"workflows/{workflow_name}.json"

        return workflow

    def get_workflow(self, name: str) -> dict | None:
        """Get a workflow from pyproject.toml."""
        try:
            config = self.load()
            return config.get('tool', {}).get('comfygit', {}).get('workflows', {}).get(name, None)
        except Exception:
            logger.error(f"Failed to load config for workflow: {name}")
            return None

    def get_execution_contract(
        self,
        workflow_name: str,
        config: dict | None = None
    ) -> WorkflowExecutionContract | None:
        """Get the saved execution contract for a workflow."""
        try:
            if config is None:
                config = self.load()
            workflow_data = config.get('tool', {}).get('comfygit', {}).get('workflows', {}).get(workflow_name, {})
            contract_data = workflow_data.get('execution_contract')
            if not contract_data:
                return None
            return WorkflowExecutionContract.from_toml_dict(contract_data)
        except Exception as e:
            logger.debug(f"Error loading execution contract for '{workflow_name}': {e}")
            return None

    def set_execution_contract(
        self,
        workflow_name: str,
        contract: WorkflowExecutionContract,
        config: dict | None = None
    ) -> None:
        """Create or replace the saved execution contract for a workflow."""
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        workflow = self._ensure_workflow_entry(config, workflow_name)
        workflow['execution_contract'] = contract.to_toml_dict()

        if not is_batch:
            self.save(config)

        logger.debug(f"Set execution contract for workflow '{workflow_name}'")

    def remove_execution_contract(
        self,
        workflow_name: str,
        config: dict | None = None
    ) -> bool:
        """Remove the saved execution contract for a workflow."""
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        workflow = config.get('tool', {}).get('comfygit', {}).get('workflows', {}).get(workflow_name, {})
        if 'execution_contract' not in workflow:
            return False

        del workflow['execution_contract']

        if not is_batch:
            self.save(config)

        logger.debug(f"Removed execution contract for workflow '{workflow_name}'")
        return True

    def get_workflow_models(
        self,
        workflow_name: str,
        config: dict | None = None
    ) -> list[ManifestWorkflowModel]:
        """Get all models for a workflow.

        Args:
            workflow_name: Workflow name
            config: Optional in-memory config for batched reads. If None, loads from disk.

        Returns:
            List of ManifestWorkflowModel objects (resolved and unresolved)
        """
        try:
            if config is None:
                config = self.load()
            workflow_data = config.get('tool', {}).get('comfygit', {}).get('workflows', {}).get(workflow_name, {})
            models_data = workflow_data.get('models', [])

            return [ManifestWorkflowModel.from_toml_dict(m) for m in models_data]
        except Exception as e:
            logger.debug(f"Error loading workflow models for '{workflow_name}': {e}")
            return []

    def set_workflow_models(
        self,
        workflow_name: str,
        models: list[ManifestWorkflowModel],
        config: dict | None = None
    ) -> None:
        """Set all models for a workflow (unified list).

        Args:
            workflow_name: Workflow name
            models: List of ManifestWorkflowModel objects (resolved and unresolved)
            config: Optional in-memory config for batched writes. If None, loads and saves immediately.
        """
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        workflow = self._ensure_workflow_entry(config, workflow_name)

        # Serialize to array of tables
        models_array = []
        for model in models:
            model_dict = model.to_toml_dict()
            # Convert to inline table for compact representation
            models_array.append(model_dict)

        workflow['models'] = models_array

        if not is_batch:
            self.save(config)

        logger.debug(f"Set {len(models)} model(s) for workflow '{workflow_name}'")

    def add_workflow_model(
        self,
        workflow_name: str,
        model: ManifestWorkflowModel
    ) -> None:
        """Add or update a single model in workflow (progressive write).

        Args:
            workflow_name: Workflow name
            model: ManifestWorkflowModel to add or update

        Note:
            - If same node reference exists, replaces/upgrades that entry
            - If model with same hash exists, merges nodes
            - Otherwise, appends as new model
        """
        existing = self.get_workflow_models(workflow_name)

        # Build set of node references in new model
        new_refs = {(n.node_id, n.widget_index) for n in model.nodes}

        # Check for overlap with existing models
        updated = False
        for i, existing_model in enumerate(existing):
            existing_refs = {(n.node_id, n.widget_index) for n in existing_model.nodes}

            # If any node references overlap, this is a resolution of an existing entry
            if new_refs & existing_refs:
                if model.hash:
                    # Resolved version replaces unresolved
                    existing[i] = model
                    logger.debug(f"Replaced unresolved model '{existing_model.filename}' with resolved '{model.filename}'")
                else:
                    # Both unresolved - merge nodes and update mutable fields
                    non_overlapping = [n for n in model.nodes if (n.node_id, n.widget_index) not in existing_refs]
                    existing_model.nodes.extend(non_overlapping)
                    existing_model.criticality = model.criticality
                    existing_model.status = model.status
                    # Update download intent fields if present
                    if model.sources:
                        existing_model.sources = model.sources
                    if model.relative_path:
                        existing_model.relative_path = model.relative_path
                    logger.debug(f"Updated unresolved model '{existing_model.filename}' with {len(non_overlapping)} new ref(s)")
                updated = True
                break

            # Fallback: hash matching (for models resolved to same file from different nodes)
            elif model.hash and existing_model.hash == model.hash:
                non_overlapping = [n for n in model.nodes if (n.node_id, n.widget_index) not in existing_refs]
                existing_model.nodes.extend(non_overlapping)
                logger.debug(f"Merged {len(non_overlapping)} new node(s) into existing model '{model.filename}'")
                updated = True
                break

        if not updated:
            # Completely new model
            existing.append(model)
            logger.debug(f"Added new model '{model.filename}' to workflow '{workflow_name}'")

        self.set_workflow_models(workflow_name, existing)


    def get_all_with_resolutions(self) -> dict:
        """Get all workflows that have model resolutions."""
        try:
            config = self.load()
            return config.get('tool', {}).get('comfygit', {}).get('workflows', {})
        except Exception:
            return {}

    def set_node_packs(self, name: str, node_pack_ids: set[str] | None, config: dict | None = None) -> None:
        """Set node pack references for a workflow.

        Args:
            name: Workflow name
            node_pack_ids: List of node pack identifiers (e.g., ["comfyui-akatz-nodes"]) | None which clears node packs
            config: Optional in-memory config for batched writes. If None, loads and saves immediately.
        """
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        workflow = self._ensure_workflow_entry(config, name)
        if not node_pack_ids:
            if 'nodes' in workflow:
                logger.info(f"Clearing node packs for workflow: {name}")
                del workflow['nodes']
        else:
            logger.info(f"Set {len(node_pack_ids)} node pack(s) for workflow: {name}")
            workflow['nodes'] = sorted(node_pack_ids)

        if not is_batch:
            self.save(config)

    # === Per-workflow custom_node_map methods ===

    def get_custom_node_map(self, workflow_name: str, config: dict | None = None) -> dict[str, str | bool]:
        """Get custom_node_map for a specific workflow.

        Args:
            workflow_name: Name of workflow
            config: Optional in-memory config for batched reads. If None, loads from disk.

        Returns:
            Dict mapping node_type -> package_id (or false for optional)
        """
        try:
            if config is None:
                config = self.load()
            workflow_data = config.get('tool', {}).get('comfygit', {}).get('workflows', {}).get(workflow_name, {})
            return workflow_data.get('custom_node_map', {})
        except Exception:
            return {}

    def set_custom_node_mapping(self, workflow_name: str, node_type: str, package_id: str | None) -> None:
        """Set a single custom_node_map entry for a workflow (progressive write).

        Args:
            workflow_name: Name of workflow
            node_type: Node type to map
            package_id: Package ID (or None for optional = false)
        """
        config = self.load()
        workflow = self._ensure_workflow_entry(config, workflow_name)

        # Ensure custom_node_map exists
        if 'custom_node_map' not in workflow:
            workflow['custom_node_map'] = {}

        # Set mapping (false for optional, package_id string for resolved)
        if package_id is None:
            workflow['custom_node_map'][node_type] = False
        else:
            workflow['custom_node_map'][node_type] = package_id

        self.save(config)
        logger.debug(f"Set custom_node_map for workflow '{workflow_name}': {node_type} -> {package_id}")

    def remove_custom_node_mapping(self, workflow_name: str, node_type: str, config: dict | None = None) -> bool:
        """Remove a single custom_node_map entry for a workflow.

        Args:
            workflow_name: Name of workflow
            node_type: Node type to remove
            config: Optional in-memory config for batched writes. If None, loads and saves immediately.

        Returns:
            True if removed, False if not found
        """
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        workflow_data = config.get('tool', {}).get('comfygit', {}).get('workflows', {}).get(workflow_name, {})

        if 'custom_node_map' not in workflow_data or node_type not in workflow_data['custom_node_map']:
            return False

        del workflow_data['custom_node_map'][node_type]

        # Clean up empty custom_node_map
        if not workflow_data['custom_node_map']:
            del workflow_data['custom_node_map']

        if not is_batch:
            self.save(config)

        logger.debug(f"Removed custom_node_map entry for workflow '{workflow_name}': {node_type}")
        return True

    def remove_workflows(self, workflow_names: list[str], config: dict | None = None) -> int:
        """Remove workflow sections from pyproject.toml.

        Args:
            workflow_names: List of workflow names to remove
            config: Optional in-memory config for batched writes. If None, loads and saves immediately.

        Returns:
            Number of workflows removed
        """
        if not workflow_names:
            return 0

        is_batch = config is not None
        if not is_batch:
            config = self.load()

        workflows = config.get('tool', {}).get('comfygit', {}).get('workflows', {})

        removed_count = 0
        for name in workflow_names:
            if name in workflows:
                del workflows[name]
                removed_count += 1
                logger.debug(f"Removed workflow section: {name}")

        if removed_count > 0:
            # Clean up empty workflows section
            self.clean_empty_sections(config, 'tool', 'comfygit', 'workflows')
            if not is_batch:
                self.save(config)
            logger.info(f"Removed {removed_count} workflow section(s) from pyproject.toml")

        return removed_count

    def cleanup_node_references(self, node_identifier: str, node_name: str | None = None) -> int:
        """Remove references to a node from all workflow nodes lists.

        Called when a node is removed to clean up orphaned references in workflows.

        Args:
            node_identifier: Primary identifier (registry ID or package name)
            node_name: Optional alternate name to also remove (for case where
                       identifier differs from directory name)

        Returns:
            Number of workflows updated
        """
        config = self.load()
        workflows = config.get('tool', {}).get('comfygit', {}).get('workflows', {})

        if not workflows:
            return 0

        # Build set of identifiers to remove (case-insensitive matching)
        identifiers_to_remove = {node_identifier.lower()}
        if node_name and node_name.lower() != node_identifier.lower():
            identifiers_to_remove.add(node_name.lower())

        updated_count = 0
        for workflow_name, workflow_data in workflows.items():
            nodes_list = workflow_data.get('nodes', [])
            if not nodes_list:
                continue

            # Filter out removed node (case-insensitive)
            updated_nodes = [n for n in nodes_list if n.lower() not in identifiers_to_remove]

            if len(updated_nodes) != len(nodes_list):
                # Nodes were removed - update the workflow
                if updated_nodes:
                    workflow_data['nodes'] = sorted(updated_nodes)
                else:
                    # No nodes left - remove the key entirely
                    del workflow_data['nodes']
                updated_count += 1
                logger.debug(f"Removed node reference '{node_identifier}' from workflow '{workflow_name}'")

        if updated_count > 0:
            self.save(config)
            logger.info(f"Cleaned up node references from {updated_count} workflow(s)")

        return updated_count
