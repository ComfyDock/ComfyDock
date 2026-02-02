"""Command-line interface for ComfyUI environment detection."""

from importlib.metadata import PackageNotFoundError, version

from .cli import main

try:
    __version__ = version("comfygit")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = ['main', '__version__']
