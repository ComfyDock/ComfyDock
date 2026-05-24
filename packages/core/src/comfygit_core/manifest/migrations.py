"""Manifest migration and cleanup helpers."""
from __future__ import annotations


def safe_delete(container: dict, key: str) -> None:
    """Delete a key from a TOML container without leaking tomlkit proxy errors."""
    try:
        del container[key]
    except (KeyError, Exception):
        pass


def strip_local_path_sources_from_config(config: dict) -> list[str]:
    """Remove uv sources with local filesystem paths from a config dict."""
    uv_config = config.get("tool", {}).get("uv", {})
    sources = uv_config.get("sources", {})

    if not sources:
        return []

    def is_local_source(value: object) -> bool:
        if isinstance(value, dict):
            return "path" in value
        if isinstance(value, list):
            return any(is_local_source(item) for item in value)
        return False

    to_remove = []
    for pkg_name, source_config in list(sources.items()):
        if is_local_source(source_config):
            to_remove.append(pkg_name)
            sources.pop(pkg_name, None)

    if not to_remove:
        return []

    if not sources:
        safe_delete(uv_config, "sources")

    if not uv_config:
        safe_delete(config.get("tool", {}), "uv")

    return to_remove


def strip_pytorch_uv_config_from_config(config: dict, pytorch_packages: set[str]) -> None:
    """Strip PyTorch uv config from an in-memory config dict."""
    if "tool" not in config or "uv" not in config["tool"]:
        return

    uv_config = config["tool"]["uv"]

    if "index" in uv_config:
        indexes = uv_config.get("index", [])
        if isinstance(indexes, list):
            uv_config["index"] = [
                idx for idx in indexes
                if not any(p in idx.get("name", "").lower() for p in ["pytorch-", "torch-"])
            ]

    if "sources" in uv_config:
        sources = uv_config["sources"]
        for package in pytorch_packages:
            sources.pop(package, None)

    if "constraint-dependencies" in uv_config:
        constraints = uv_config["constraint-dependencies"]
        if isinstance(constraints, list):
            uv_config["constraint-dependencies"] = [
                constraint for constraint in constraints
                if not any(package in constraint for package in pytorch_packages)
            ]


def strip_tracked_pytorch_config_from_config(config: dict, pytorch_packages: set[str]) -> None:
    """Remove tracked PyTorch backend and uv configuration from a manifest."""
    if "tool" in config and "comfygit" in config["tool"]:
        config["tool"]["comfygit"].pop("torch_backend", None)

    if "tool" not in config or "uv" not in config["tool"]:
        return

    uv_config = config["tool"]["uv"]

    if "index" in uv_config:
        indexes = uv_config["index"]
        if isinstance(indexes, list):
            uv_config["index"] = [
                idx for idx in indexes
                if "pytorch" not in idx.get("name", "").lower()
            ]
            if not uv_config["index"]:
                safe_delete(uv_config, "index")

    if "sources" in uv_config:
        for package in pytorch_packages:
            uv_config["sources"].pop(package, None)
        if not uv_config["sources"]:
            safe_delete(uv_config, "sources")

    if "constraint-dependencies" in uv_config:
        constraints = uv_config["constraint-dependencies"]
        uv_config["constraint-dependencies"] = [
            constraint for constraint in constraints
            if not any(package in constraint.lower() for package in pytorch_packages)
        ]
        if not uv_config["constraint-dependencies"]:
            safe_delete(uv_config, "constraint-dependencies")

    if not uv_config:
        safe_delete(config["tool"], "uv")
