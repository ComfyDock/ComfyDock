"""Manual workflow model dependency policy."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from ..models.shared import ModelWithLocation


class WorkflowManualModelPolicy:
    """Owns identity rules for manually declared workflow model dependencies."""

    @staticmethod
    def normalize_model_relative_path(relative_path: str) -> str:
        """Normalize and validate a path relative to the configured models directory."""
        normalized = relative_path.replace("\\", "/").strip()
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Model path must be relative to the models directory: {relative_path}")
        return path.as_posix()

    @staticmethod
    def category_for_indexed_model(model: ModelWithLocation) -> str:
        """Return the manifest category for an indexed model location."""
        if model.category and model.category != "unknown":
            return model.category
        parts = PurePosixPath(model.relative_path.replace("\\", "/")).parts
        if len(parts) > 1 and parts[0]:
            return parts[0]
        return model.category or "unknown"

    @staticmethod
    def is_manual_workflow_model(model: Any) -> bool:
        """Return whether a workflow model was manually declared outside graph analysis."""
        return getattr(model, "declared_by", None) == "manual" or not getattr(model, "nodes", None)

    def manual_workflow_model_key(self, model: Any) -> tuple[str, str] | None:
        """Return stable identity for a manual workflow model dependency."""
        relative_path = getattr(model, "relative_path", None)
        if relative_path:
            return ("path", self.normalize_model_relative_path(relative_path))
        model_hash = getattr(model, "hash", None)
        if model_hash:
            return ("hash", str(model_hash))
        return None
