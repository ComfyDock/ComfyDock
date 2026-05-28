"""Typed runtime configuration results exposed by Environment facades."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TorchBackendStatus:
    """Current local PyTorch backend state for an environment."""

    backend: str | None
    versions: Mapping[str, str]
    backend_file: Path
    is_configured: bool


@dataclass(frozen=True)
class TorchBackendSelection:
    """Result of ensuring or overriding a PyTorch backend."""

    backend: str
    versions: Mapping[str, str]
    backend_file: Path
    is_configured: bool
    was_probed: bool = False


@dataclass(frozen=True)
class TorchBackendDetection:
    """Detected compatible PyTorch backend and package versions."""

    backend: str
    versions: Mapping[str, str]
    python_version: str


@dataclass(frozen=True)
class OverlayActivationResult:
    """Result of enabling or disabling an overlay."""

    name: str
    changed: bool
    is_compatible: bool


@dataclass(frozen=True)
class OverlayTemplateResult:
    """Result of creating a local or shared overlay template."""

    name: str
    path: Path
    scope: str
    created: bool


@dataclass(frozen=True)
class DependencyGroupRemovalResult:
    """Packages removed from or skipped in a dependency group mutation."""

    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        """Serialize for legacy callers and JSON/API edges."""
        return {
            "removed": list(self.removed),
            "skipped": list(self.skipped),
        }


@dataclass(frozen=True)
class UVCommandContext:
    """Environment-scoped uv command context for adapter passthrough commands."""

    binary: str
    cwd: Path
    env: Mapping[str, str]
