"""Overlay manager for loading, activation, collection, and migration."""
from __future__ import annotations

import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomlkit
from packaging.utils import canonicalize_name
from tomlkit.exceptions import TOMLKitError

from ..logging.logging_config import get_logger
from ..models.overlay import OverlayConfig
from .pytorch_backend_manager import PyTorchBackendManager

logger = get_logger(__name__)


@dataclass
class OverlayInfo:
    """Display metadata for a discovered overlay."""

    name: str
    description: str | None
    is_local: bool
    is_active: bool
    requires: list[str]


class OverlayManager:
    """Manage overlay files and activation state for an environment."""

    def __init__(self, env_path: Path):
        """Initialize manager.

        Args:
            env_path: Environment .cec path.
        """
        self.env_path = env_path
        self.overlays_dir = env_path / "overlays"
        self.activation_path = env_path / ".overlay-config.toml"
        self.legacy_local_uv_path = env_path / ".local-uv-config"
        self.local_overlay_path = self.overlays_dir / ".local.toml"
        self.pyproject_path = env_path / "pyproject.toml"
        self.pytorch_manager = PyTorchBackendManager(env_path)

        self.overlays_dir.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_local_uv_config()

    def _overlay_path(self, name: str) -> Path:
        OverlayConfig.validate_name(name)
        return self.overlays_dir / f"{name}.toml"

    def _normalize_name_sequence(self, names: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for name in names:
            OverlayConfig.validate_name(name)
            key = canonicalize_name(name)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(name)
        return deduped

    def _read_activation_config(self) -> list[str]:
        if not self.activation_path.exists():
            return []

        try:
            with open(self.activation_path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"Failed to parse {self.activation_path}: {exc}") from exc

        active = data.get("active", [])
        if not isinstance(active, list) or not all(isinstance(item, str) for item in active):
            raise ValueError(f"{self.activation_path} must contain an 'active' string list")

        return self._normalize_name_sequence(active)

    def _write_activation_config(self, active_names: list[str]) -> None:
        doc = tomlkit.document()
        doc["active"] = active_names
        self.activation_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    def _load_legacy_local_uv(self) -> dict:
        try:
            with open(self.legacy_local_uv_path, encoding="utf-8") as f:
                data = tomlkit.load(f)
        except (OSError, TOMLKitError) as exc:
            raise ValueError(f"Failed to parse {self.legacy_local_uv_path}: {exc}") from exc
        return dict(data) if isinstance(data, dict) else {}

    def _build_local_overlay_doc(self, legacy: dict) -> tomlkit.TOMLDocument:
        doc = tomlkit.document()
        overlay = tomlkit.table()
        overlay["description"] = "Migrated from .local-uv-config"
        doc["overlay"] = overlay

        sources = legacy.get("sources", {})
        if sources:
            if not isinstance(sources, dict):
                raise ValueError("Legacy .local-uv-config 'sources' must be a table")
            doc["sources"] = sources

        constraints = legacy.get("constraint-dependencies", [])
        if not constraints:
            constraints = legacy.get("constraints", [])
        if constraints:
            if not isinstance(constraints, list) or not all(isinstance(c, str) for c in constraints):
                raise ValueError("Legacy .local-uv-config constraints must be a string list")
            constraints_table = tomlkit.table()
            constraints_table["packages"] = list(constraints)
            doc["constraints"] = constraints_table

        indexes = legacy.get("index", [])
        if indexes and not isinstance(indexes, list):
            indexes = [indexes]
        if indexes:
            aot = tomlkit.aot()
            for index in indexes:
                if not isinstance(index, dict):
                    raise ValueError("Legacy .local-uv-config indexes must be tables")
                table = tomlkit.table()
                for key, value in index.items():
                    table[key] = value
                aot.append(table)
            doc["index"] = aot

        return doc

    def _migrate_legacy_local_uv_config(self) -> None:
        has_legacy = self.legacy_local_uv_path.exists()
        has_local_overlay = self.local_overlay_path.exists()

        if not has_legacy:
            return

        if has_local_overlay:
            # New file already exists; discard stale legacy file.
            self.legacy_local_uv_path.unlink(missing_ok=True)
            logger.info("Removed legacy .local-uv-config (already migrated)")
            return

        legacy_data = self._load_legacy_local_uv()
        overlay_doc = self._build_local_overlay_doc(legacy_data)

        self.overlays_dir.mkdir(parents=True, exist_ok=True)
        self.local_overlay_path.write_text(tomlkit.dumps(overlay_doc), encoding="utf-8")
        self.legacy_local_uv_path.unlink(missing_ok=True)
        logger.info("Migrated .local-uv-config to overlays/.local.toml")

    def _meets_platform_requirements(self, overlay: OverlayConfig) -> bool:
        if not overlay.requires:
            return True

        backend: str | None = None
        if self.pytorch_manager.has_backend():
            try:
                backend = self.pytorch_manager.get_backend()
            except Exception:
                backend = None

        has_cuda = bool(backend and backend.startswith("cu")) or self._command_exists("nvidia-smi")
        has_rocm = bool(backend and backend.startswith("rocm")) or self._command_exists("rocm-smi")

        for requirement in overlay.requires:
            if requirement == "cuda" and not has_cuda:
                logger.warning(
                    "Skipping overlay '%s': requires CUDA but capability not detected",
                    overlay.name,
                )
                return False
            if requirement == "rocm" and not has_rocm:
                logger.warning(
                    "Skipping overlay '%s': requires ROCm but capability not detected",
                    overlay.name,
                )
                return False
        return True

    @staticmethod
    def _command_exists(command: str) -> bool:
        try:
            completed = subprocess.run(
                [command, "--help"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0 or completed.returncode == 1

    def load_overlay(self, name: str) -> OverlayConfig:
        """Load a single overlay by name."""
        path = self._overlay_path(name)
        if not path.exists():
            raise ValueError(f"Overlay '{name}' does not exist at {path}")
        return OverlayConfig.from_toml(path)

    def list_overlays(self) -> list[OverlayInfo]:
        """List overlays with metadata and activation state."""
        active = set(canonicalize_name(name) for name in self.get_active_names())
        overlays: list[OverlayInfo] = []

        for path in sorted(self.overlays_dir.glob("*.toml"), key=lambda p: p.name):
            overlay = OverlayConfig.from_toml(path)
            overlays.append(
                OverlayInfo(
                    name=overlay.name,
                    description=overlay.description,
                    is_local=overlay.is_local,
                    is_active=canonicalize_name(overlay.name) in active,
                    requires=list(overlay.requires),
                )
            )
        return overlays

    def get_tracked_defaults(self) -> list[str]:
        """Get tracked default overlays from pyproject.toml."""
        if not self.pyproject_path.exists():
            return []

        try:
            with open(self.pyproject_path, "rb") as f:
                config = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"Failed to parse {self.pyproject_path}: {exc}") from exc

        defaults = (
            config.get("tool", {})
            .get("comfygit", {})
            .get("overlay-defaults", [])
        )

        if not isinstance(defaults, list) or not all(isinstance(item, str) for item in defaults):
            raise ValueError("tool.comfygit.overlay-defaults must be a string list")

        return self._normalize_name_sequence(defaults)

    def get_active_names(self) -> list[str]:
        """Get persistent active overlay names."""
        if self.activation_path.exists():
            names = self._read_activation_config()
        else:
            names = self.get_tracked_defaults()
        return self._normalize_name_sequence(names)

    def set_active_names(self, names: list[str]) -> None:
        """Persist active overlay names to local activation config."""
        normalized = self._normalize_name_sequence(names)
        discovered = {
            canonicalize_name(path.stem): path
            for path in self.overlays_dir.glob("*.toml")
        }

        unknown = [name for name in normalized if canonicalize_name(name) not in discovered]
        if unknown:
            raise ValueError(f"Unknown overlay(s): {', '.join(unknown)}")

        self._write_activation_config(normalized)

    def _resolve_known_name(self, requested_name: str) -> str:
        discovered = {
            canonicalize_name(path.stem): path.stem
            for path in self.overlays_dir.glob("*.toml")
        }
        resolved = discovered.get(canonicalize_name(requested_name))
        if not resolved:
            raise ValueError(f"Unknown overlay: {requested_name}")
        return resolved

    def _from_pytorch_config(self, pytorch_config: dict) -> OverlayConfig | None:
        if not pytorch_config:
            return None

        return OverlayConfig(
            name=".pytorch",
            path=self.env_path / ".pytorch-backend",
            description="Auto-generated PyTorch backend overlay",
            kind="pytorch",
            requires=[],
            is_local=True,
            dependencies=[],
            sources=dict(pytorch_config.get("sources", {})),
            settings={},
            dependency_metadata=[],
            constraints=list(pytorch_config.get("constraints", [])),
            indexes=list(pytorch_config.get("indexes", [])),
        )

    def collect_overlays(
        self,
        extra_names: list[str] | None = None,
        pytorch_config: dict | None = None,
    ) -> list[OverlayConfig]:
        """Collect overlays in deterministic merge order.

        Order: local -> activated (alphabetical) -> CLI extras -> pytorch.
        """
        overlays: list[OverlayConfig] = []
        seen: set[str] = set()

        if self.local_overlay_path.exists():
            local_overlay = OverlayConfig.from_toml(self.local_overlay_path)
            if self._meets_platform_requirements(local_overlay):
                overlays.append(local_overlay)
                seen.add(canonicalize_name(local_overlay.name))

        active_names = sorted(self.get_active_names(), key=lambda n: canonicalize_name(n))
        for name in active_names:
            resolved_name = self._resolve_known_name(name)
            key = canonicalize_name(resolved_name)
            if key in seen:
                continue
            overlay = self.load_overlay(resolved_name)
            if not self._meets_platform_requirements(overlay):
                continue
            overlays.append(overlay)
            seen.add(key)

        for name in extra_names or []:
            OverlayConfig.validate_name(name)
            resolved_name = self._resolve_known_name(name)
            key = canonicalize_name(resolved_name)
            if key in seen:
                continue
            overlay = self.load_overlay(resolved_name)
            if not self._meets_platform_requirements(overlay):
                continue
            overlays.append(overlay)
            seen.add(key)

        pytorch_overlay = self._from_pytorch_config(pytorch_config or {})
        if pytorch_overlay and self._meets_platform_requirements(pytorch_overlay):
            overlays.append(pytorch_overlay)

        return overlays
