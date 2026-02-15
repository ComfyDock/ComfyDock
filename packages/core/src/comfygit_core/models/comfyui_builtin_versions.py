"""Typed models and helpers for version-indexed ComfyUI builtin nodes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SEMVER_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
GIT_DESCRIBE_TAG_RE = re.compile(r"^(v?\d+\.\d+\.\d+)-\d+-g[0-9a-f]+(?:-dirty)?$")
PRESENT_RANGE_RE = re.compile(r"^(v?\d+\.\d+\.\d+)(?:-(v?\d+\.\d+\.\d+)|\+)$")


def parse_semver_tag(tag: str | None) -> tuple[int, int, int] | None:
    """Parse `vX.Y.Z` or `X.Y.Z` into a sortable semantic version tuple."""
    if not tag:
        return None
    match = SEMVER_TAG_RE.match(tag.strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def normalize_version_tag(version: str | None) -> str | None:
    """Normalize incoming ComfyUI versions to `vX.Y.Z` where possible."""
    if not version:
        return None

    raw = version.strip()
    if not raw:
        return None

    # Common git describe format when running from a non-tag commit.
    describe_match = GIT_DESCRIBE_TAG_RE.match(raw)
    if describe_match:
        raw = describe_match.group(1)

    parsed = parse_semver_tag(raw)
    if parsed is None:
        return None
    return f"v{parsed[0]}.{parsed[1]}.{parsed[2]}"


def _parse_present_range(
    range_spec: str
) -> tuple[tuple[int, int, int], tuple[int, int, int] | None, str] | None:
    """Parse present range syntax (`vA.B.C-vD.E.F` or `vA.B.C+`)."""
    match = PRESENT_RANGE_RE.match(range_spec.strip())
    if not match:
        return None

    start_tag = normalize_version_tag(match.group(1))
    if not start_tag:
        return None

    start_tuple = parse_semver_tag(start_tag)
    if start_tuple is None:
        return None

    end_capture = match.group(2)
    if end_capture:
        end_tag = normalize_version_tag(end_capture)
        end_tuple = parse_semver_tag(end_tag) if end_tag else None
        if end_tuple is None:
            return None
        return (start_tuple, end_tuple, start_tag)

    return (start_tuple, None, start_tag)


@dataclass
class ComfyUIBuiltinVersionEntry:
    """Single builtin node presence entry."""

    introduced_in: str
    category: str
    removed_in: str | None = None
    present_in: list[str] = field(default_factory=list)


@dataclass
class BuiltinVersionGateInfo:
    """Classification metadata for a builtin missing from the current environment."""

    node_type: str
    current_version: str | None
    message: str
    reason: str
    introduced_in: str | None = None
    removed_in: str | None = None
    required_version: str | None = None


@dataclass
class ComfyUIBuiltinVersions:
    """Version-indexed ComfyUI builtin node database."""

    version: str
    generated_at: str
    comfyui_versions_processed: list[str]
    stats: dict
    builtins: dict[str, ComfyUIBuiltinVersionEntry]

    @classmethod
    def from_dict(cls, data: dict) -> "ComfyUIBuiltinVersions":
        """Build typed model from JSON dict payload."""
        builtins_raw = data.get("builtins", {})
        builtins: dict[str, ComfyUIBuiltinVersionEntry] = {}

        if isinstance(builtins_raw, dict):
            for node_type, entry in builtins_raw.items():
                if not isinstance(entry, dict):
                    continue
                introduced_in = entry.get("introduced_in")
                category = entry.get("category")
                if not isinstance(introduced_in, str) or not introduced_in:
                    continue
                if not isinstance(category, str) or not category:
                    category = "frontend"
                present_in = entry.get("present_in", [])
                if not isinstance(present_in, list):
                    present_in = []

                builtins[node_type] = ComfyUIBuiltinVersionEntry(
                    introduced_in=introduced_in,
                    category=category,
                    removed_in=entry.get("removed_in"),
                    present_in=[str(spec) for spec in present_in],
                )

        return cls(
            version=str(data.get("version", "unknown")),
            generated_at=str(data.get("generated_at", "")),
            comfyui_versions_processed=list(data.get("comfyui_versions_processed", [])),
            stats=dict(data.get("stats", {})),
            builtins=builtins,
        )

    def is_known_builtin(self, node_type: str) -> bool:
        """Return True when node exists in any ComfyUI version."""
        return node_type in self.builtins

    def get_entry(self, node_type: str) -> ComfyUIBuiltinVersionEntry | None:
        """Get typed entry for a node type."""
        return self.builtins.get(node_type)

    def is_present_at_version(self, node_type: str, current_version: str | None) -> bool | None:
        """Return whether node is present at current version, or None if version unknown."""
        entry = self.get_entry(node_type)
        if entry is None:
            return False

        normalized_current = normalize_version_tag(current_version)
        if normalized_current is None:
            return None

        current_tuple = parse_semver_tag(normalized_current)
        if current_tuple is None:
            return None

        return self._is_present_for_entry(entry, current_tuple)

    def get_version_gate_info(
        self,
        node_type: str,
        current_version: str | None
    ) -> BuiltinVersionGateInfo | None:
        """Return detailed version-gated info when a known builtin is not present now."""
        entry = self.get_entry(node_type)
        if entry is None:
            return None

        normalized_current = normalize_version_tag(current_version)
        normalized_intro = normalize_version_tag(entry.introduced_in)
        normalized_removed = normalize_version_tag(entry.removed_in)

        if normalized_current is None:
            message = f"Node {node_type} is a ComfyUI builtin; current ComfyUI version is unknown."
            if normalized_intro:
                message += f" It was introduced in {normalized_intro}."
            return BuiltinVersionGateInfo(
                node_type=node_type,
                current_version=None,
                message=message,
                reason="unknown_current_version",
                introduced_in=normalized_intro,
                removed_in=normalized_removed,
                required_version=normalized_intro,
            )

        current_tuple = parse_semver_tag(normalized_current)
        if current_tuple is None:
            return BuiltinVersionGateInfo(
                node_type=node_type,
                current_version=normalized_current,
                message=f"Node {node_type} is a ComfyUI builtin; current ComfyUI version could not be parsed.",
                reason="invalid_current_version",
                introduced_in=normalized_intro,
                removed_in=normalized_removed,
                required_version=normalized_intro,
            )

        if self._is_present_for_entry(entry, current_tuple):
            return None

        required_version = self._next_present_version(entry, current_tuple)
        removed_tuple = parse_semver_tag(normalized_removed) if normalized_removed else None

        if required_version:
            message = (
                f"Node {node_type} requires ComfyUI >= {required_version} "
                f"(current {normalized_current})."
            )
            reason = "requires_newer_comfyui"
        elif removed_tuple and current_tuple >= removed_tuple:
            message = (
                f"Node {node_type} is not available in ComfyUI {normalized_current}; "
                f"it was removed in {normalized_removed}."
            )
            reason = "removed_builtin"
        else:
            message = f"Node {node_type} is not available in ComfyUI {normalized_current}."
            reason = "not_present_for_version"

        return BuiltinVersionGateInfo(
            node_type=node_type,
            current_version=normalized_current,
            message=message,
            reason=reason,
            introduced_in=normalized_intro,
            removed_in=normalized_removed,
            required_version=required_version,
        )

    def _is_present_for_entry(
        self,
        entry: ComfyUIBuiltinVersionEntry,
        current_tuple: tuple[int, int, int]
    ) -> bool:
        """Evaluate node presence for a parsed current semantic version."""
        if entry.present_in:
            for range_spec in entry.present_in:
                parsed = _parse_present_range(range_spec)
                if parsed is None:
                    continue
                start_tuple, end_tuple, _start_tag = parsed
                if current_tuple < start_tuple:
                    continue
                if end_tuple is None or current_tuple <= end_tuple:
                    return True
            return False

        introduced_tuple = parse_semver_tag(normalize_version_tag(entry.introduced_in))
        removed_tuple = parse_semver_tag(normalize_version_tag(entry.removed_in))

        if introduced_tuple and current_tuple < introduced_tuple:
            return False
        if removed_tuple and current_tuple >= removed_tuple:
            return False
        return True

    def _next_present_version(
        self,
        entry: ComfyUIBuiltinVersionEntry,
        current_tuple: tuple[int, int, int]
    ) -> str | None:
        """Return earliest future version tag where node is present."""
        if entry.present_in:
            starts: list[tuple[tuple[int, int, int], str]] = []
            for range_spec in entry.present_in:
                parsed = _parse_present_range(range_spec)
                if parsed is None:
                    continue
                start_tuple, _end_tuple, start_tag = parsed
                starts.append((start_tuple, start_tag))

            for start_tuple, start_tag in sorted(starts, key=lambda item: item[0]):
                if start_tuple > current_tuple:
                    return start_tag
            return None

        intro_tag = normalize_version_tag(entry.introduced_in)
        intro_tuple = parse_semver_tag(intro_tag)
        if intro_tag and intro_tuple and intro_tuple > current_tuple:
            return intro_tag
        return None
