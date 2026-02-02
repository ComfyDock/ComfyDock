"""Dependency parsing utilities for pyproject.toml files.

This module provides utilities for parsing and comparing Python package dependencies
from pyproject.toml files, including support for UV dependency groups.
"""

import re

from ..logging.logging_config import get_logger

logger = get_logger(__name__)


def parse_dependency_string(dep_str: str) -> tuple[str, str | None]:
    """Parse a dependency string like 'numpy>=1.21.0' into name and version.

    Args:
        dep_str: Dependency string (e.g., 'numpy>=1.21.0', 'numpy[extra]>=1.21.0')

    Returns:
        Tuple of (package_name, version_spec) where version_spec may be None
    """
    # Handle various formats: numpy, numpy>=1.21.0, numpy[extra]>=1.21.0
    match = re.match(r'^([a-zA-Z0-9_-]+)(?:\[.*?\])?(.*)$', dep_str.strip())
    if match:
        name = match.group(1)
        version_spec = match.group(2).strip() if match.group(2) else None
        return name, version_spec

    return dep_str.strip(), None


def extract_all_dependencies(pyproject_data: dict) -> dict[str, dict]:
    """Extract all dependencies from pyproject.toml including groups.

    When a package appears in multiple places, we track all occurrences
    and use the most restrictive constraint as the effective one.

    Args:
        pyproject_data: Parsed pyproject.toml data

    Returns:
        Dict mapping package names to their info (version, source)
    """
    deps = {}

    # Track all sources and versions for each package
    package_occurrences = {}  # name -> [(source, version), ...]

    # Main dependencies
    if "project" in pyproject_data:
        for dep_str in pyproject_data["project"].get("dependencies", []):
            name, version = parse_dependency_string(dep_str)
            if name not in package_occurrences:
                package_occurrences[name] = []
            package_occurrences[name].append(("main", version))

    # Dependency groups (UV format)
    if "dependency-groups" in pyproject_data:
        for group_name, group_deps in pyproject_data["dependency-groups"].items():
            for dep_str in group_deps:
                name, version = parse_dependency_string(dep_str)
                if name not in package_occurrences:
                    package_occurrences[name] = []
                package_occurrences[name].append((f"group:{group_name}", version))

    # Tool-specific dependencies (for custom nodes)
    if "tool" in pyproject_data:
        if "uv" in pyproject_data["tool"]:
            uv_config = pyproject_data["tool"]["uv"]
            if "dev-dependencies" in uv_config:
                for dep_str in uv_config["dev-dependencies"]:
                    name, version = parse_dependency_string(dep_str)
                    if name not in package_occurrences:
                        package_occurrences[name] = []
                    package_occurrences[name].append(("dev", version))

    # For each package, determine the effective constraint
    for name, occurrences in package_occurrences.items():
        # Find the most restrictive version constraint
        # Priority: exact pins > bounded constraints > lower bounds > unconstrained
        most_restrictive = None
        all_sources = []

        for source, version in occurrences:
            all_sources.append(source)
            if most_restrictive is None:
                most_restrictive = version
            elif version is not None:
                # Compare constraints - this is simplified
                # In reality, we'd need proper version parsing
                if most_restrictive is None:
                    most_restrictive = version
                elif "==" in version:  # Exact pin
                    most_restrictive = version
                elif "==" not in most_restrictive:
                    # Prefer the more specific constraint
                    if len(version) > len(most_restrictive or ""):
                        most_restrictive = version

        deps[name] = {
            "version": most_restrictive,
            "source": ", ".join(set(all_sources))  # Show all sources
        }

    return deps


def is_meaningful_version_change(old_version: str | None,
                                new_version: str | None) -> bool:
    """Determine if a version change is meaningful.

    Rules:
    - No change if both are None or both are the same
    - No change if one is None and the other is a lower bound (>=)
      since unconstrained effectively means "any version"
    - Change if going from unconstrained to pinned
    - Change if version numbers actually differ

    Args:
        old_version: Previous version constraint
        new_version: New version constraint

    Returns:
        True if the change is meaningful
    """
    # Both None or identical - no change
    if old_version == new_version:
        return False

    # One is None - check if it's effectively the same
    if old_version is None and new_version is not None:
        # Going from unconstrained to constrained
        # Only meaningful if it's not just a lower bound
        if new_version.startswith(">="):
            # Lower bound only - not really a meaningful constraint
            return False
        return True

    if new_version is None and old_version is not None:
        # Going from constrained to unconstrained
        # Only meaningful if we had a real constraint before
        if old_version.startswith(">="):
            # Was just a lower bound - not meaningful
            return False
        return True

    # Both have versions - check if they differ meaningfully
    # This is simplified - a full implementation would parse version specs
    return old_version != new_version


def find_most_restrictive_constraint(constraints: list[str]) -> str | None:
    """Find the most restrictive version constraint from a list.

    Priority: exact pins > upper bounds > ranges > lower bounds > unconstrained

    Args:
        constraints: List of version constraints

    Returns:
        The most restrictive constraint or None
    """
    if not constraints:
        return None

    # Filter out None values
    valid_constraints = [c for c in constraints if c]
    if not valid_constraints:
        return None

    # Look for exact pins first
    for constraint in valid_constraints:
        if "==" in constraint:
            return constraint

    # Look for upper bounds or ranges
    for constraint in valid_constraints:
        if "<" in constraint or "," in constraint:
            return constraint

    # Return any constraint (likely lower bounds)
    return valid_constraints[0]


def compare_dependency_sets(before: dict[str, dict], after: dict[str, dict]) -> dict[str, list]:
    """Compare two sets of dependencies to find changes.

    Args:
        before: Previous dependencies (from git)
        after: Current dependencies (from file)

    Returns:
        Dict with 'added', 'removed', and 'updated' lists
    """
    changes = {
        "added": [],
        "removed": [],
        "updated": []
    }

    all_packages = set(before.keys()) | set(after.keys())

    for pkg in all_packages:
        if pkg not in before:
            # New package
            changes["added"].append({
                "name": pkg,
                "version": after[pkg].get("version"),
                "source": after[pkg].get("source")
            })
        elif pkg not in after:
            # Removed package
            changes["removed"].append({
                "name": pkg,
                "version": before[pkg].get("version")
            })
        else:
            # Check if there's a meaningful change
            old_version = before[pkg].get("version")
            new_version = after[pkg].get("version")

            if is_meaningful_version_change(old_version, new_version):
                changes["updated"].append({
                    "name": pkg,
                    "old_version": old_version,
                    "new_version": new_version,
                    "source": after[pkg].get("source")
                })

    return changes
