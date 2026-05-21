#!/usr/bin/env python3
"""Check version compatibility across release artifacts (lockstep versioning)."""

import json
import sys
from pathlib import Path
import tomllib


def get_version(pyproject_path):
    """Extract version from pyproject.toml."""
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
        return data["project"]["version"]


def get_package_json_version(package_json_path):
    """Extract version from package.json."""
    with open(package_json_path, encoding="utf-8") as f:
        data = json.load(f)
        return data["version"]


def check_compatibility():
    """Check if all release artifacts have identical versions (lockstep)."""
    root = Path(__file__).parent.parent.parent

    artifacts = {
        "core": (root / "packages/core/pyproject.toml", get_version),
        "cli": (root / "packages/cli/pyproject.toml", get_version),
        "studio": (root / "packages/studio/package.json", get_package_json_version),
    }

    versions = {}
    for name, (path, reader) in artifacts.items():
        if path.exists():
            versions[name] = reader(path)
            print(f"{name:10} {versions[name]}")

    # Lockstep: all versions must be exactly equal
    unique_versions = set(versions.values())

    if len(unique_versions) > 1:
        print("\n❌ ERROR: Version mismatch detected!")
        print("Lockstep versioning requires all release artifacts to have the same version.")
        print("Run: make bump-version VERSION=X.Y.Z")
        return False

    print(f"\n✅ All release artifacts at version {list(unique_versions)[0]} (lockstep)")
    return True


if __name__ == "__main__":
    if not check_compatibility():
        sys.exit(1)
