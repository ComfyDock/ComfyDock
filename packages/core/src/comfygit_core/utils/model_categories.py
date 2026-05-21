"""Utility functions for determining model categories from filesystem paths."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..configs.comfyui_models import COMFYUI_MODELS_CONFIG

if TYPE_CHECKING:
    from ..configs.model_config import ModelConfig


def get_model_category(relative_path: str, model_config: ModelConfig | None = None) -> str:
    """Determine model category from relative path.

    Extracts the first directory component from the relative path and checks
    if it matches a standard ComfyUI model directory. If not found in the
    standard directories, returns 'unknown' to indicate a custom directory.

    Args:
        relative_path: Path relative to models directory (e.g., "checkpoints/sd_xl.safetensors")
        model_config: Optional environment-aware model config to use for category lookup

    Returns:
        Category name (e.g., "checkpoints", "loras", "vae") or "unknown"

    Examples:
        >>> get_model_category("checkpoints/sd_xl_base.safetensors")
        'checkpoints'
        >>> get_model_category("loras/detail_tweaker.safetensors")
        'loras'
        >>> get_model_category("custom_nodes/my-node/models/special.pt")
        'unknown'
        >>> get_model_category("model.safetensors")
        'unknown'
    """
    if not relative_path:
        return "unknown"

    # Normalize path and extract first component
    normalized_path = Path(relative_path).as_posix()
    parts = normalized_path.split('/')

    if not parts or not parts[0]:
        return "unknown"

    # Get first directory component (lowercase for case-insensitive matching)
    first_dir = parts[0].lower()

    # Check against standard directories
    standard_dirs = (
        model_config.standard_directories
        if model_config is not None
        else COMFYUI_MODELS_CONFIG.get('standard_directories', [])
    )

    # Case-insensitive match
    for std_dir in standard_dirs:
        if first_dir == std_dir.lower():
            return std_dir

    return "unknown"
