"""Probe-based dependency resolution utilities.

This module provides utilities for probing dependency changes by installing
requirements one-by-one in an isolated venv, similar to how ComfyUI Manager
handles installations.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import tomlkit
from packaging.version import Version
from packaging.version import parse as parse_version

from ..integrations.uv_command import UVCommand
from ..logging.logging_config import get_logger
from ..utils.filesystem import rmtree

logger = get_logger(__name__)


@dataclass
class ProbeResult:
    """Result of dependency probing."""

    success: bool
    added: dict[str, str] = field(default_factory=dict)
    removed: dict[str, str] = field(default_factory=dict)
    upgraded: dict[str, tuple[str, str]] = field(default_factory=dict)
    downgraded: dict[str, tuple[str, str]] = field(default_factory=dict)
    protected_changes: list[str] = field(default_factory=list)
    suggested_constraints: list[str] = field(default_factory=list)
    install_failures: list[str] = field(default_factory=list)


class DependencyProbe:
    """Probe what dependency changes installing requirements would cause.

    Uses an isolated venv to install requirements one-by-one (ComfyUI Manager style)
    and captures before/after package states to infer needed constraints.
    """

    PROTECTED_PACKAGES: set[str] = {
        "torch",
        "torchvision",
        "torchaudio",
        "torchsde",
    }

    def __init__(
        self,
        cec_path: Path,
        workspace_path: Path,
        *,
        python_version: str | None = None,
        torch_backend: str | None = None,
        keep_venv: bool = False,
    ):
        """Initialize the dependency probe.

        Args:
            cec_path: Path to the .cec directory containing pyproject.toml
            workspace_path: Path to ComfyGit workspace for UV cache/python
            python_version: Python version to use (auto-detected if not provided)
            torch_backend: PyTorch backend (auto-detected if not provided)
            keep_venv: If True, don't cleanup probe venv after run (for debugging)
        """
        self.cec_path = cec_path
        self.pyproject_path = cec_path / "pyproject.toml"
        self.probe_venv = cec_path / ".venv-probe"
        self.uv_cache_path = workspace_path / "uv_cache"
        self.uv_python_path = workspace_path / "uv" / "python"
        self.keep_venv = keep_venv

        self.python_version = python_version or self._detect_python_version()
        self.torch_backend = torch_backend or self._detect_torch_backend()

    def run(self, requirements: list[str]) -> ProbeResult:
        """Run probe and return results.

        Args:
            requirements: List of requirements to probe (e.g., ["librosa>=0.9.0"])

        Returns:
            ProbeResult with changes detected and suggested constraints
        """
        reqs = [r.strip() for r in requirements if r and r.strip()]
        if not reqs:
            return ProbeResult(success=True)

        try:
            self._create_probe_venv()
            self._sync_probe_to_current_state()

            before = self._freeze_packages()
            failures = self._install_one_by_one(reqs)
            after = self._freeze_packages()

            return self._analyze(before, after, failures)
        finally:
            if not self.keep_venv:
                self._cleanup()

    def _detect_python_version(self) -> str:
        """Detect Python version from pyproject.toml."""
        if not self.pyproject_path.exists():
            return f"{sys.version_info.major}.{sys.version_info.minor}"

        try:
            data = tomlkit.loads(self.pyproject_path.read_text(encoding="utf-8"))
            python_req = data.get("project", {}).get("requires-python", "")
            # Extract version from requires-python (e.g., ">=3.12" -> "3.12")
            if python_req:
                version = python_req.lstrip(">=<~! ")
                if version:
                    return version
        except Exception as e:
            logger.debug(f"Could not detect Python version from pyproject: {e}")

        return f"{sys.version_info.major}.{sys.version_info.minor}"

    def _detect_torch_backend(self) -> str | None:
        """Detect PyTorch backend from .cec/.pytorch-backend file.

        The file may contain additional lines (torch version info), so we only
        read the first line which contains the backend identifier (e.g., 'cu129').
        """
        backend_file = self.cec_path / ".pytorch-backend"
        if backend_file.exists():
            try:
                content = backend_file.read_text(encoding="utf-8").strip()
                # Only take the first line - the backend identifier
                first_line = content.split("\n")[0].strip()
                return first_line if first_line else None
            except Exception as e:
                logger.debug(f"Could not read pytorch-backend file: {e}")
        return None

    def _get_probe_python(self) -> Path:
        """Get path to Python executable in probe venv."""
        if sys.platform == "win32":
            return self.probe_venv / "Scripts" / "python.exe"
        return self.probe_venv / "bin" / "python"

    def _create_probe_venv(self) -> None:
        """Create the isolated probe venv."""
        # Remove existing probe venv if it exists
        if self.probe_venv.exists():
            rmtree(self.probe_venv)

        uv = UVCommand(
            cache_dir=self.uv_cache_path,
            python_install_dir=self.uv_python_path,
            cwd=self.cec_path,
        )

        uv.venv(self.probe_venv, python=self.python_version, seed=True)
        logger.debug(f"Created probe venv at {self.probe_venv}")

    def _sync_probe_to_current_state(self) -> None:
        """Sync probe venv to match the current environment state."""
        uv = UVCommand(
            project_env=self.probe_venv,
            cache_dir=self.uv_cache_path,
            python_install_dir=self.uv_python_path,
            cwd=self.cec_path,
            torch_backend=self.torch_backend,
        )

        uv.sync(all_groups=True)
        logger.debug("Synced probe venv to current state")

    def _freeze_packages(self) -> dict[str, str]:
        """Get current installed packages from probe venv.

        Returns:
            Dict mapping normalized package names to versions
        """
        uv = UVCommand(
            cache_dir=self.uv_cache_path,
            python_install_dir=self.uv_python_path,
        )

        result = uv.pip_freeze(python=self._get_probe_python())
        packages = {}

        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue

            if "==" in line:
                name, version = line.split("==", 1)
                packages[self._normalize_name(name)] = version

        return packages

    def _install_one_by_one(self, requirements: list[str]) -> list[str]:
        """Install requirements one-by-one, recording failures.

        Args:
            requirements: List of requirements to install

        Returns:
            List of requirements that failed to install
        """
        failures = []
        uv = UVCommand(
            cache_dir=self.uv_cache_path,
            python_install_dir=self.uv_python_path,
        )
        # Allow longer timeout for slow packages
        uv.timeout = 300

        for req in requirements:
            try:
                uv.pip_install(
                    packages=[req],
                    python=self._get_probe_python(),
                    torch_backend=self.torch_backend,
                )
                logger.debug(f"Probe installed: {req}")
            except Exception as e:
                logger.debug(f"Probe failed to install {req}: {e}")
                failures.append(req)

        return failures

    def _analyze(
        self, before: dict[str, str], after: dict[str, str], failures: list[str]
    ) -> ProbeResult:
        """Analyze before/after package states to determine changes.

        Args:
            before: Package versions before installation
            after: Package versions after installation
            failures: List of requirements that failed to install

        Returns:
            ProbeResult with all detected changes and suggested constraints
        """
        result = ProbeResult(success=len(failures) == 0)
        result.install_failures = list(failures)

        # Detect added packages
        for name, version in after.items():
            if name not in before:
                result.added[name] = version

        # Detect removed packages
        for name, version in before.items():
            if name not in after:
                result.removed[name] = version

        # Detect version changes (upgrades/downgrades)
        for name, new_version in after.items():
            if name not in before:
                continue

            old_version = before[name]
            if old_version == new_version:
                continue

            try:
                old_v = parse_version(old_version)
                new_v = parse_version(new_version)

                if new_v < old_v:
                    # Downgrade detected
                    result.downgraded[name] = (old_version, new_version)

                    # Check if protected
                    if self._is_protected(name):
                        result.protected_changes.append(name)
                    else:
                        # Generate constraint from downgraded version
                        constraint = self._version_to_constraint(name, new_version)
                        if constraint:
                            result.suggested_constraints.append(constraint)
                else:
                    # Upgrade detected
                    result.upgraded[name] = (old_version, new_version)
            except Exception as e:
                logger.debug(f"Could not compare versions for {name}: {e}")
                # Treat as text comparison
                if old_version != new_version:
                    result.upgraded[name] = (old_version, new_version)

        return result

    def _version_to_constraint(self, package: str, downgraded_version: str) -> str:
        """Generate a broad constraint from a downgraded version.

        The constraint excludes the next minor version, e.g.:
        - numpy 2.3.5 -> numpy<2.4
        - llvmlite 0.46.0 -> llvmlite<0.47

        Args:
            package: Package name (will be normalized)
            downgraded_version: The version we downgraded TO

        Returns:
            Constraint string like "numpy<2.4"
        """
        try:
            v = parse_version(downgraded_version)
            if isinstance(v, Version):
                # Exclude next minor version
                next_minor = f"{v.major}.{v.minor + 1}"
                return f"{self._normalize_name(package)}<{next_minor}"
        except Exception as e:
            logger.debug(f"Could not parse version for constraint: {e}")

        # Fallback: use exact upper bound
        return f"{self._normalize_name(package)}<={downgraded_version}"

    def _is_protected(self, name: str) -> bool:
        """Check if a package is protected from auto-constraining."""
        return self._normalize_name(name) in {
            self._normalize_name(p) for p in self.PROTECTED_PACKAGES
        }

    def _normalize_name(self, name: str) -> str:
        """Normalize package name for comparison.

        Package index treats foo-bar and foo_bar as equivalent.
        We normalize to lowercase with underscores.

        Args:
            name: Package name to normalize

        Returns:
            Normalized name (lowercase, dashes to underscores)
        """
        return name.lower().replace("-", "_")

    def _cleanup(self) -> None:
        """Remove the probe venv."""
        if self.probe_venv.exists():
            rmtree(self.probe_venv)
            logger.debug(f"Cleaned up probe venv at {self.probe_venv}")
