#!/usr/bin/env python3
"""Copy the built Studio frontend into the Studio runtime package."""

from __future__ import annotations

import shutil
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    source = root / "packages" / "studio" / "dist" / "static"
    target = root / "packages" / "studio-runtime" / "comfygit_studio" / "static"

    if not source.exists():
        raise SystemExit(f"Studio build output not found: {source}")

    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    print(f"Synced {source.relative_to(root)} -> {target.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
