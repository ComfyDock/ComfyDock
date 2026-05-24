"""Overlay configuration model and TOML parser."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomllib
from packaging.utils import canonicalize_name

ALLOWED_OVERLAY_KINDS = {"pytorch", "shared", "local"}
ALLOWED_OVERLAY_REQUIRES = {"cuda", "rocm"}

OVERLAY_TEMPLATE = """[overlay]
# description = "Describe this overlay"
# kind = "pytorch"
# requires = ["cuda"]

[dependencies]
packages = []

[sources]
# package-name = { git = "https://github.com/user/repo.git" }

[settings]
no-build-isolation-package = []
override-dependencies = []
environments = []

# [[dependency-metadata]]
# name = "package-name"
# version = "1.0.0"
# requires-dist = ["torch"]

[constraints]
packages = []

# [[index]]
# name = "custom-index"
# url = "https://example.com/simple"
# explicit = true
"""


def _as_dict(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Overlay field '{field_name}' must be a table")
    return dict(value)


def _as_list_of_strings(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Overlay field '{field_name}' must be a list")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"Overlay field '{field_name}' must contain only strings")
    return list(value)


def _as_list_of_dicts(value: Any, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Overlay field '{field_name}' must be an array of tables")
    parsed: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"Overlay field '{field_name}' must be an array of tables")
        parsed.append(dict(item))
    return parsed


@dataclass
class OverlayInfo:
    """Display metadata for a discovered overlay."""

    name: str
    description: str | None
    is_local: bool
    is_active: bool
    requires: list[str]
    is_stock: bool = False


@dataclass
class OverlayConfig:
    """Parsed overlay file configuration."""

    name: str
    path: Path
    description: str | None = None
    kind: str | None = None
    requires: list[str] = field(default_factory=list)
    is_local: bool = False

    dependencies: list[str] = field(default_factory=list)
    sources: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    dependency_metadata: list[dict[str, Any]] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    indexes: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def validate_name(name: str) -> None:
        if not name:
            raise ValueError("Overlay name cannot be empty")
        if "/" in name or "\\" in name:
            raise ValueError(f"Overlay name must be flat (no subdirectories): {name}")
        if name in {".", ".."}:
            raise ValueError(f"Invalid overlay name: {name}")

    @classmethod
    def from_toml(cls, path: Path) -> OverlayConfig:
        """Parse and validate an overlay file."""
        if path.suffix != ".toml":
            raise ValueError(f"Overlay must use .toml extension: {path}")

        name = path.stem
        cls.validate_name(name)

        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except FileNotFoundError:
            raise ValueError(f"Overlay file not found: {path}") from None
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"Failed to parse overlay TOML {path}: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(f"Overlay file must decode to a table: {path}")

        overlay = _as_dict(data.get("overlay"), "overlay")
        dependencies = _as_dict(data.get("dependencies"), "dependencies")
        sources = _as_dict(data.get("sources"), "sources")
        settings = _as_dict(data.get("settings"), "settings")
        constraints = _as_dict(data.get("constraints"), "constraints")
        dependency_metadata = [
            entry for entry in _as_list_of_dicts(data.get("dependency-metadata"), "dependency-metadata")
            if entry.get("name")
        ]
        indexes = [
            idx for idx in _as_list_of_dicts(data.get("index"), "index")
            if idx.get("name") and idx.get("url")
        ]

        description = overlay.get("description")
        if description is not None and not isinstance(description, str):
            raise ValueError("Overlay 'description' must be a string")

        kind = overlay.get("kind")
        if kind is not None:
            if not isinstance(kind, str):
                raise ValueError("Overlay 'kind' must be a string")
            if kind not in ALLOWED_OVERLAY_KINDS:
                allowed = ", ".join(sorted(ALLOWED_OVERLAY_KINDS))
                raise ValueError(f"Unsupported overlay kind '{kind}', allowed: {allowed}")

        requires = _as_list_of_strings(overlay.get("requires"), "overlay.requires")
        normalized_requires: list[str] = []
        for requirement in requires:
            normalized = requirement.lower()
            if normalized not in ALLOWED_OVERLAY_REQUIRES:
                allowed = ", ".join(sorted(ALLOWED_OVERLAY_REQUIRES))
                raise ValueError(
                    f"Unsupported overlay requirement '{requirement}', allowed: {allowed}"
                )
            if normalized not in normalized_requires:
                normalized_requires.append(normalized)

        dependency_packages = _as_list_of_strings(
            dependencies.get("packages"), "dependencies.packages"
        )
        constraint_packages = _as_list_of_strings(
            constraints.get("packages"), "constraints.packages"
        )

        return cls(
            name=name,
            path=path,
            description=description,
            kind=kind,
            requires=normalized_requires,
            is_local=name.startswith("."),
            dependencies=dependency_packages,
            sources=sources,
            settings=settings,
            dependency_metadata=dependency_metadata,
            constraints=constraint_packages,
            indexes=indexes,
        )

    def _dedupe_by_canonical_name(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            canonical = canonicalize_name(value)
            if canonical in seen:
                continue
            seen.add(canonical)
            deduped.append(value)
        return deduped

    def to_uv_payload(self) -> dict[str, Any]:
        """Convert overlay config to the UV pyproject payload."""
        no_build_isolation = _as_list_of_strings(
            self.settings.get("no-build-isolation-package"),
            "settings.no-build-isolation-package",
        )
        override_dependencies = _as_list_of_strings(
            self.settings.get("override-dependencies"),
            "settings.override-dependencies",
        )
        environments = _as_list_of_strings(
            self.settings.get("environments"),
            "settings.environments",
        )

        return {
            "dependencies": list(self.dependencies),
            "sources": dict(self.sources),
            "constraints": list(self.constraints),
            "indexes": [dict(index) for index in self.indexes],
            "dependency_metadata": [dict(entry) for entry in self.dependency_metadata],
            "no_build_isolation_packages": self._dedupe_by_canonical_name(no_build_isolation),
            "override_dependencies": list(override_dependencies),
            "environments": list(environments),
        }

    def is_empty(self) -> bool:
        payload = self.to_uv_payload()
        return not any(
            payload[key]
            for key in (
                "dependencies",
                "sources",
                "constraints",
                "indexes",
                "dependency_metadata",
                "no_build_isolation_packages",
                "override_dependencies",
                "environments",
            )
        )
