"""UV overlay materialization for disposable pyproject manifests."""
from __future__ import annotations

import re
from typing import Any, cast

import tomlkit
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from ..constants import PYTORCH_CORE_PACKAGES
from ..models.overlay import OverlayConfig
from ..utils.dependency_parser import parse_dependency_string
from .migrations import (
    strip_local_path_sources_from_config,
    strip_pytorch_uv_config_from_config,
)


def summarize_modified_overlay_fields(overlays: list[OverlayConfig]) -> dict[str, int]:
    summary = {
        "dependencies": 0,
        "sources": 0,
        "constraints": 0,
        "indexes": 0,
        "dependency_metadata": 0,
        "no_build_isolation_packages": 0,
        "override_dependencies": 0,
        "environments": 0,
    }

    for overlay in overlays:
        payload = overlay.to_uv_payload()
        for key in summary:
            value = payload.get(key)
            if isinstance(value, dict):
                summary[key] += len(value)
            elif isinstance(value, list):
                summary[key] += len(value)
            elif value:
                summary[key] += 1

    return {
        key: count
        for key, count in summary.items()
        if count > 0
    }


def apply_uv_overlays_to_config(
    config: dict,
    effective_overlays: list[OverlayConfig],
) -> None:
    """Apply overlay-derived uv configuration to an in-memory manifest."""
    if not effective_overlays:
        return

    if any(overlay.is_local for overlay in effective_overlays):
        strip_local_path_sources_from_config(config)

    for overlay in effective_overlays:
        if overlay.kind == "pytorch":
            strip_pytorch_uv_config_from_config(config, set(PYTORCH_CORE_PACKAGES))

        inject_overlay_payload(config, overlay.to_uv_payload())


def extract_dependency_key(requirement: str) -> str:
    normalized_requirement = requirement.strip()
    try:
        parsed = Requirement(normalized_requirement)
        return canonicalize_name(parsed.name)
    except Exception:
        pass

    try:
        package_name, _ = parse_dependency_string(normalized_requirement)
        return canonicalize_name(package_name)
    except Exception:
        match = re.match(r"^([A-Za-z0-9._-]+)", normalized_requirement)
        if not match:
            return normalized_requirement.lower()
        return canonicalize_name(match.group(1))


def to_aot(values: list[dict]) -> Any:
    aot = tomlkit.aot()
    for value in values:
        table = tomlkit.table()
        for key, item in value.items():
            table[key] = item
        aot.append(table)
    return aot


def merge_by_name_last_wins(
    existing: list[dict],
    new_items: list[dict],
    key_name: str,
) -> list[dict]:
    merged: list[dict] = [dict(item) for item in existing if isinstance(item, dict)]
    for item in new_items:
        if not isinstance(item, dict):
            continue
        key = item.get(key_name)
        if isinstance(key, str):
            merged = [candidate for candidate in merged if candidate.get(key_name) != key]
        merged.append(dict(item))
    return merged


def merge_specs_last_wins(existing: list[str], new_specs: list[str]) -> list[str]:
    merged = list(existing)
    for spec in new_specs:
        spec_key = extract_dependency_key(spec)
        merged = [value for value in merged if extract_dependency_key(value) != spec_key]
        merged.append(spec)
    return merged


def inject_overlay_payload(config: dict, payload: dict) -> None:
    if not payload:
        return

    if "project" not in config:
        config["project"] = tomlkit.table()
    if "dependencies" not in config["project"]:
        config["project"]["dependencies"] = []

    existing_project_dependencies = config["project"].get("dependencies", [])
    if not isinstance(existing_project_dependencies, list):
        existing_project_dependencies = [existing_project_dependencies] if existing_project_dependencies else []

    overlay_deps = [dep for dep in payload.get("dependencies", []) if isinstance(dep, str)]
    merged_deps = merge_specs_last_wins(
        [dep for dep in existing_project_dependencies if isinstance(dep, str)],
        overlay_deps,
    )
    config["project"]["dependencies"] = merged_deps

    if "tool" not in config:
        config["tool"] = tomlkit.table()
    if "uv" not in config["tool"]:
        config["tool"]["uv"] = tomlkit.table()

    uv_config = cast(dict[str, Any], config["tool"]["uv"])

    existing_indexes = uv_config.get("index", [])
    if not isinstance(existing_indexes, list):
        existing_indexes = [existing_indexes] if existing_indexes else []
    merged_indexes = merge_by_name_last_wins(
        existing_indexes,
        payload.get("indexes", []),
        key_name="name",
    )
    if merged_indexes:
        uv_config["index"] = to_aot(merged_indexes)

    existing_sources = uv_config.get("sources", {})
    if not isinstance(existing_sources, dict):
        existing_sources = {}
    if "sources" not in uv_config:
        uv_config["sources"] = tomlkit.table()
    uv_sources = cast(dict[str, Any], uv_config["sources"])
    for package_name, source in payload.get("sources", {}).items():
        source_key = canonicalize_name(package_name)
        existing_key = next(
            (
                key for key in list(uv_sources.keys())
                if canonicalize_name(key) == source_key
            ),
            None,
        )
        if existing_key and existing_key != package_name:
            del uv_sources[existing_key]
        uv_sources[package_name] = source

    constraints = [constraint for constraint in payload.get("constraints", []) if isinstance(constraint, str)]
    if constraints:
        existing_constraints = uv_config.get("constraint-dependencies", [])
        if not isinstance(existing_constraints, list):
            existing_constraints = [existing_constraints] if existing_constraints else []
        uv_config["constraint-dependencies"] = merge_specs_last_wins(
            [constraint for constraint in existing_constraints if isinstance(constraint, str)],
            constraints,
        )

    metadata_entries = [
        entry for entry in payload.get("dependency_metadata", [])
        if isinstance(entry, dict)
    ]
    if metadata_entries:
        existing_metadata = uv_config.get("dependency-metadata", [])
        if not isinstance(existing_metadata, list):
            existing_metadata = [existing_metadata] if existing_metadata else []

        merged_metadata = [dict(entry) for entry in existing_metadata if isinstance(entry, dict)]
        for metadata in metadata_entries:
            package_name = metadata.get("name")
            if not isinstance(package_name, str):
                merged_metadata.append(dict(metadata))
                continue
            package_key = canonicalize_name(package_name)
            merged_metadata = [
                item
                for item in merged_metadata
                if canonicalize_name(str(item.get("name", ""))) != package_key
            ]
            merged_metadata.append(dict(metadata))

        uv_config["dependency-metadata"] = to_aot(merged_metadata)

    no_build_isolation = [
        item for item in payload.get("no_build_isolation_packages", [])
        if isinstance(item, str)
    ]
    if no_build_isolation:
        existing_no_build = uv_config.get("no-build-isolation-package", [])
        if not isinstance(existing_no_build, list):
            existing_no_build = [existing_no_build] if existing_no_build else []
        merged_no_build = list(existing_no_build)
        seen_no_build = {
            canonicalize_name(item)
            for item in existing_no_build
            if isinstance(item, str)
        }
        for package_name in no_build_isolation:
            package_key = canonicalize_name(package_name)
            if package_key in seen_no_build:
                continue
            merged_no_build.append(package_name)
            seen_no_build.add(package_key)
        uv_config["no-build-isolation-package"] = merged_no_build

    override_dependencies = [
        item for item in payload.get("override_dependencies", [])
        if isinstance(item, str)
    ]
    if override_dependencies:
        existing_override = uv_config.get("override-dependencies", [])
        if not isinstance(existing_override, list):
            existing_override = [existing_override] if existing_override else []
        uv_config["override-dependencies"] = merge_specs_last_wins(
            [item for item in existing_override if isinstance(item, str)],
            override_dependencies,
        )

    environments = [
        item for item in payload.get("environments", [])
        if isinstance(item, str)
    ]
    if environments:
        existing_environments = uv_config.get("environments", [])
        if not isinstance(existing_environments, list):
            existing_environments = [existing_environments] if existing_environments else []
        merged_environments = list(existing_environments)
        for environment in environments:
            if environment not in merged_environments:
                merged_environments.append(environment)
        uv_config["environments"] = merged_environments
