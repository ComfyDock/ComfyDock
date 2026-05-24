"""Global model manifest helpers."""
from __future__ import annotations

import tomlkit

from ..logging.logging_config import get_logger
from ..models.manifest import ManifestModel
from .base import BaseHandler

logger = get_logger(__name__)


class ModelHandler(BaseHandler):
    """Handles global model manifest in pyproject.toml.

    Note: This stores ONLY resolved models with hashes for deduplication.
    Unresolved models are stored per-workflow only.
    """

    def add_model(self, model: ManifestModel, config: dict | None = None) -> None:
        """Add a model to the global manifest.

        If model already exists, merges sources (union of old and new).

        Args:
            model: ManifestModel object with hash, filename, size, etc.
            config: Optional in-memory config for batched writes. If None, loads and saves immediately.

        Raises:
            CDPyprojectError: If save fails
        """
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        # Ensure sections exist
        self.ensure_section(config, "tool", "comfygit", "models")

        # Check if model already exists and merge sources
        # In batch mode, check in-memory config instead of loading from disk
        models_section = config.get("tool", {}).get("comfygit", {}).get("models", {})
        if model.hash in models_section:
            existing_dict = models_section[model.hash]
            existing_sources = existing_dict.get('sources', [])
            model.sources = list(set(existing_sources + model.sources))

        # Serialize to inline table for compact representation
        model_dict = model.to_toml_dict()
        model_entry = tomlkit.inline_table()
        for key, value in model_dict.items():
            model_entry[key] = value

        config["tool"]["comfygit"]["models"][model.hash] = model_entry

        if not is_batch:
            self.save(config)

        logger.debug(f"Added model: {model.filename} ({model.hash[:8]}...)")

    def get_all(self) -> list[ManifestModel]:
        """Get all models in manifest.

        Returns:
            List of ManifestModel objects
        """
        try:
            config = self.load()
            models_data = config.get("tool", {}).get("comfygit", {}).get("models", {})

            return [
                ManifestModel.from_toml_dict(hash_key, data)
                for hash_key, data in models_data.items()
            ]
        except Exception as e:
            logger.debug(f"Error loading models: {e}")
            return []

    def get_by_hash(self, model_hash: str) -> ManifestModel | None:
        """Get a specific model by hash.

        Args:
            model_hash: Model hash to look up

        Returns:
            ManifestModel if found, None otherwise
        """
        try:
            config = self.load()
            models_data = config.get("tool", {}).get("comfygit", {}).get("models", {})

            if model_hash in models_data:
                return ManifestModel.from_toml_dict(model_hash, models_data[model_hash])
            return None
        except Exception as e:
            logger.warning(f"Error getting model by hash {model_hash}: {e}")
            return None

    def cleanup_orphans(self, config: dict | None = None) -> None:
        """Remove models from global table that aren't referenced by any workflow.

        This should be called after all workflows have been processed to clean up
        models that were removed from all workflows.

        Args:
            config: Optional in-memory config for batched writes. If None, loads and saves immediately.
        """
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        # Collect all model hashes referenced by ANY workflow
        # Read from in-memory config instead of loading from disk
        referenced_hashes = set()
        all_workflows = config.get('tool', {}).get('comfygit', {}).get('workflows', {})

        for _workflow_name, workflow_data in all_workflows.items():
            workflow_models_data = workflow_data.get('models', [])
            for model_data in workflow_models_data:
                # Only track resolved models (unresolved models aren't in global table)
                if model_data.get('hash') and model_data.get('status') == "resolved":
                    referenced_hashes.add(model_data['hash'])

        # Get all hashes in global models table (from in-memory config)
        models_section = config.get("tool", {}).get("comfygit", {}).get("models", {})
        global_hashes = set(models_section.keys())

        # Remove orphans (in global but not referenced)
        orphaned_hashes = global_hashes - referenced_hashes

        if orphaned_hashes:
            for model_hash in orphaned_hashes:
                if model_hash in models_section:
                    del models_section[model_hash]
                    logger.debug(f"Removed orphaned model: {model_hash[:8]}...")

            if not is_batch:
                self.save(config)

            logger.info(f"Cleaned up {len(orphaned_hashes)} orphaned model(s)")
