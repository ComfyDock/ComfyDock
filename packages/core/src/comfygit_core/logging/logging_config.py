"""Core logging utilities for ComfyDock."""

import logging


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for the given module.

    Args:
        name: Module name (typically __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
