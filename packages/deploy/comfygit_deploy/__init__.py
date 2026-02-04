"""ComfyGit Deploy - Remote deployment and worker management CLI."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("comfygit-deploy")
except PackageNotFoundError:
    __version__ = "unknown"
