"""Helper for populating model index with test data."""
from hashlib import sha256


class ModelIndexBuilder:
    """Fluent builder for populating model index with test models."""

    def __init__(self, workspace):
        self.workspace = workspace
        self.models_dir = workspace.workspace_config_manager.get_models_directory()
        self.created_models = {}

    def add_model(
        self,
        filename: str,
        relative_path: str,
        size_mb: int = 4,
        category: str | None = None
    ) -> "ModelIndexBuilder":
        """Add a model to the index.

        Args:
            filename: Model filename (e.g., "sd15.safetensors")
            relative_path: Path relative to models dir (e.g., "checkpoints")
            size_mb: Size in MB for deterministic testing
            category: Optional category override

        Returns:
            Self for chaining
        """
        # Create file
        model_path = self.models_dir / relative_path / filename
        model_path.parent.mkdir(parents=True, exist_ok=True)

        # Write deterministic content for reproducible hash
        content = b"TEST_MODEL_" + filename.encode() + b"\x00" * (size_mb * 1024 * 1024)
        with open(model_path, 'wb') as f:
            f.write(content)

        # Calculate deterministic hash
        file_hash = sha256(filename.encode()).hexdigest()[:16]

        # Store metadata
        full_relative_path = f"{relative_path}/{filename}"
        self.created_models[filename] = {
            'filename': filename,
            'hash': file_hash,
            'file_size': model_path.stat().st_size,
            'relative_path': full_relative_path,
            'category': category or relative_path.split('/')[0],
            'path': model_path
        }

        return self

    def index_all(self) -> dict[str, dict]:
        """Scan and index all added models.

        Returns:
            Dictionary of created models keyed by filename
        """
        self.workspace.sync_model_directory()
        return self.created_models

    def get_hash(self, filename: str) -> str:
        """Get hash for a created model."""
        return self.created_models[filename]['hash']
