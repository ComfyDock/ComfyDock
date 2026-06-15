"""Manages .pytorch-backend file and PyTorch overlay configuration."""
from __future__ import annotations

import re
from pathlib import Path

from ..constants import PYTORCH_CORE_PACKAGES
from ..logging.logging_config import get_logger
from ..utils.pytorch import get_pytorch_index_url

logger = get_logger(__name__)


class PyTorchBackendManager:
    """Manages .pytorch-backend file and PyTorch overlay configuration.

    The .pytorch-backend file stores the user's PyTorch backend choice (e.g., cu128, cpu).
    This file is gitignored, allowing different machines to use different backends
    while sharing the same environment configuration.
    """

    # Valid backend patterns
    BACKEND_PATTERNS = [
        r'^cu\d{2,3}$',  # CUDA: cu118, cu121, cu128, cu130, etc.
        r'^cpu$',  # CPU
        r'^rocm\d+\.\d+$',  # ROCm: rocm6.2, rocm6.3, etc.
        r'^xpu$',  # Intel XPU
    ]

    def __init__(self, cec_path: Path):
        """Initialize manager.

        Args:
            cec_path: Path to the .cec directory
        """
        self.cec_path = cec_path
        self.backend_file = cec_path / ".pytorch-backend"

    def get_backend(self) -> str:
        """Read backend from file (first line only).

        Returns:
            Backend string (e.g., 'cu128', 'cpu')

        Raises:
            ValueError: If .pytorch-backend file doesn't exist or is empty
        """
        if self.backend_file.exists():
            lines = self.backend_file.read_text().strip().split('\n')
            if lines and lines[0]:
                backend = lines[0].strip()
                logger.debug(f"Read PyTorch backend from file: {backend}")
                return backend

        raise ValueError(
            ".pytorch-backend file not found or empty. "
            "Run probe_and_set_backend() first."
        )

    def set_backend(self, backend: str, versions: dict[str, str] | None = None) -> None:
        """Write backend and optional versions to file.

        File format:
            cu128
            torch=2.9.1+cu128
            torchvision=0.24.1+cu128
            torchaudio=2.9.1+cu128

        Args:
            backend: Backend string (e.g., 'cu128', 'cpu')
            versions: Optional dict mapping package name to version
        """
        content = backend
        if versions:
            for pkg, version in versions.items():
                content += f"\n{pkg}={version}"
        self.backend_file.write_text(content)
        logger.info(f"Set PyTorch backend: {backend}")

        # Ensure .gitignore has this entry (migration support)
        self._ensure_gitignore_entry()

    def probe_and_set_backend(
        self,
        python_version: str,
        backend: str = "auto",
    ) -> str:
        """Probe PyTorch versions and set backend.

        Uses uv's dry-run probing to detect the appropriate backend.

        Args:
            python_version: Python version (e.g., "3.12")
            backend: Backend to probe ("auto" for auto-detection, or specific like "cu128")

        Returns:
            Resolved backend string (e.g., "cu128", "cpu")

        Raises:
            PyTorchProbeError: If probing fails
        """
        from ..utils.pytorch_prober import probe_pytorch_versions

        # Probe versions
        versions, resolved_backend = probe_pytorch_versions(python_version, backend)

        # Write backend AND versions to file
        self.set_backend(resolved_backend, versions)

        return resolved_backend

    def has_backend(self) -> bool:
        """Check if .pytorch-backend file exists and is non-empty."""
        if not self.backend_file.exists():
            return False
        return bool(self.backend_file.read_text().strip())

    def ensure_backend(self, python_version: str = "3.12") -> str:
        """Ensure backend is configured, auto-probing if necessary.

        If .pytorch-backend file exists and is valid, returns its contents.
        Otherwise, probes the system for available backends and saves the result.

        Args:
            python_version: Python version for probing (e.g., "3.12")

        Returns:
            Backend string (e.g., 'cu128', 'cpu')
        """
        if self.has_backend():
            return self.get_backend()
        return self.probe_and_set_backend(python_version, "auto")

    def get_versions(self) -> dict[str, str]:
        """Read PyTorch versions from .pytorch-backend file.

        Returns:
            Dict mapping package name to version (e.g., {"torch": "2.9.1+cu128"})
            Empty dict if no versions stored or file missing.
        """
        if not self.backend_file.exists():
            return {}

        lines = self.backend_file.read_text().strip().split('\n')
        versions = {}

        # Skip first line (backend), parse remaining as pkg=version
        for line in lines[1:]:
            if '=' in line:
                pkg, version = line.split('=', 1)
                versions[pkg.strip()] = version.strip()

        return versions

    def _ensure_gitignore_entry(self) -> None:
        """Ensure .pytorch-backend is in .gitignore."""
        gitignore_path = self.cec_path / ".gitignore"
        entry = ".pytorch-backend"

        if not gitignore_path.exists():
            gitignore_path.write_text(f"# PyTorch backend configuration (machine-specific)\n{entry}\n")
            logger.debug(f"Created .gitignore with entry: {entry}")
            return

        current_content = gitignore_path.read_text()

        # Check if entry already exists
        for line in current_content.split('\n'):
            stripped = line.split('#')[0].strip()
            if stripped == entry:
                return  # Already present

        # Add entry at the end
        if not current_content.endswith('\n'):
            current_content += '\n'
        current_content += f"\n# PyTorch backend configuration (machine-specific)\n{entry}\n"
        gitignore_path.write_text(current_content)
        logger.info(f"Added {entry} to .gitignore (migration)")

    def is_valid_backend(self, backend: str) -> bool:
        """Check if backend string matches valid patterns.

        Args:
            backend: Backend string to validate

        Returns:
            True if valid, False otherwise
        """
        if not backend:
            return False

        for pattern in self.BACKEND_PATTERNS:
            if re.match(pattern, backend):
                return True

        return False

    def get_pytorch_config(
        self,
        backend_override: str | None = None,
        python_version: str | None = None,
    ) -> dict:
        """Generate PyTorch uv config for current backend.

        Args:
            backend_override: Override backend instead of reading from file (e.g., "cu128")
            python_version: Python version for probing (e.g., "3.12"). Required when
                           using backend_override to probe correct wheel versions.

        Returns dict with:
            - indexes: List of index configs (name, url, explicit)
            - sources: Dict mapping package names to index names
            - constraints: List of version constraints (e.g., ["torch==2.9.1+cu128"])

        Note: PyPI's Linux wheels include CUDA, so we always use PyTorch's index
        for all backends (including CPU) to get the correct wheel variants.

        Returns:
            Configuration dict for PyTorch packages
        """
        backend = backend_override if backend_override else self.get_backend()
        index_url = get_pytorch_index_url(backend)
        index_name = f"pytorch-{backend}"

        sources: dict[str, dict[str, str]] = {}
        for package in PYTORCH_CORE_PACKAGES:
            sources[package] = {"index": index_name}

        # Generate constraints
        constraints: list[str] = []
        if backend_override and python_version:
            # Probe versions for the override backend to get correct wheel versions
            from ..utils.pytorch_prober import probe_pytorch_versions
            versions, _ = probe_pytorch_versions(python_version, backend_override)
            constraints = [
                f"{pkg}=={version}"
                for pkg, version in versions.items()
                if pkg in PYTORCH_CORE_PACKAGES
            ]
            logger.debug(f"PyTorch constraints for backend override {backend_override}: {constraints}")
        elif not backend_override:
            # Use stored versions from .pytorch-backend file
            versions = self.get_versions()
            constraints = [
                f"{pkg}=={version}"
                for pkg, version in versions.items()
                if pkg in PYTORCH_CORE_PACKAGES
            ]

        config = {
            "indexes": [
                {
                    "name": index_name,
                    "url": index_url,
                    "explicit": True,
                }
            ],
            "sources": sources,
            "constraints": constraints,
        }

        logger.debug(f"Generated PyTorch config for backend {backend}: {config}")
        return config
