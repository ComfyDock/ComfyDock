"""Compatibility imports for TOML parsing."""

from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib  # pyright: ignore[reportMissingImports]

__all__ = ["tomllib"]
