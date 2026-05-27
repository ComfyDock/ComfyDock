#!/usr/bin/env python3
"""Compare unmanaged ComfyUI scan output against managed environment manifests.

This is a developer audit harness, not a product command. It is useful when
tuning unmanaged import scanning because a managed ComfyGit workspace gives us
both sides of the comparison:

- the live ComfyUI tree, scanned as if it were unmanaged
- the tracked .cec/pyproject.toml manifest, used as an approximate baseline

The comparison intentionally treats manifest drift as diagnostic context rather
than a test failure. The scanner's job is to describe what exists in the live
ComfyUI install.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import tomllib
from comfygit_core import Workspace
from comfygit_core.analyzers.unmanaged_comfyui_analyzer import scan_unmanaged_comfyui

IGNORED_CUSTOM_NODES = {"comfygit-manager"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workspace",
        nargs="?",
        type=Path,
        help="ComfyGit workspace containing managed environments",
    )
    parser.add_argument(
        "--workspace",
        dest="workspace_option",
        type=Path,
        help="ComfyGit workspace containing managed environments",
    )
    parser.add_argument("--json", action="store_true", help="Emit full JSON instead of the text summary")
    parser.add_argument("--json-output", type=Path, help="Write full JSON report to this path")
    parser.add_argument(
        "--include-manager",
        action="store_true",
        help="Include comfygit-manager in custom-node scoring",
    )
    args = parser.parse_args()

    workspace_arg = args.workspace_option or args.workspace
    if not workspace_arg:
        parser.error("workspace is required, either as a positional argument or --workspace")

    workspace_path = workspace_arg.expanduser().resolve()
    ignored_nodes = set() if args.include_manager else set(IGNORED_CUSTOM_NODES)
    result = audit_workspace(workspace_path, ignored_nodes=ignored_nodes)

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_text_report(result)

    return 0


def audit_workspace(workspace_path: Path, *, ignored_nodes: set[str]) -> dict[str, Any]:
    workspace = Workspace.open(workspace_path)
    node_registry_lookup = getattr(workspace, "node_mapping_repository", None)

    results: list[dict[str, Any]] = []
    environments_dir = workspace_path / "environments"
    for env_dir in sorted(environments_dir.iterdir()):
        if not _is_managed_environment_dir(env_dir):
            continue
        try:
            results.append(
                audit_environment(
                    env_dir,
                    node_registry_lookup=node_registry_lookup,
                    ignored_nodes=ignored_nodes,
                )
            )
        except Exception as exc:
            results.append({"environment": env_dir.name, "error": repr(exc)})

    aggregate = _aggregate_scores(results)
    return {
        "workspace": str(workspace_path),
        "environment_count": len(results),
        "aggregate": aggregate,
        "results": results,
    }


def audit_environment(
    env_dir: Path,
    *,
    node_registry_lookup: Any | None,
    ignored_nodes: set[str],
) -> dict[str, Any]:
    manifest = _load_manifest(env_dir)
    preview = scan_unmanaged_comfyui(
        env_dir / "ComfyUI",
        node_registry_lookup=node_registry_lookup,
        ignored_custom_node_names=tuple(ignored_nodes),
    )
    scanned = preview.to_dict()

    actual_workflows = set(manifest["workflows"])
    scanned_workflows = {workflow["name"] for workflow in scanned["workflows"]}

    graph_models = [model for model in manifest["models"] if model["node_ref_count"] > 0]
    actual_models_path = {_model_key(model, mode="path") for model in graph_models}
    actual_models_strict = {_model_key(model, mode="strict") for model in graph_models}
    actual_models_loose = {_model_key(model, loose=True) for model in graph_models}
    scanned_models_path = {_scan_model_key(model, mode="path") for model in scanned["model_references"]}
    scanned_models_strict = {_scan_model_key(model, mode="strict") for model in scanned["model_references"]}
    scanned_models_loose = {_scan_model_key(model, loose=True) for model in scanned["model_references"]}

    actual_nodes = {
        identifier: info
        for identifier, info in manifest["nodes"].items()
        if _normalize(identifier) not in ignored_nodes
    }
    scanned_node_aliases = set().union(
        *(_scanned_node_aliases(node, ignored_nodes=ignored_nodes) for node in scanned["custom_nodes"])
    ) if scanned["custom_nodes"] else set()
    matched_node_identifiers = {
        identifier
        for identifier, info in actual_nodes.items()
        if _manifest_node_aliases(identifier, info, ignored_nodes=ignored_nodes) & scanned_node_aliases
    }

    result = {
        "environment": env_dir.name,
        "versions": {
            "manifest": manifest["comfyui_version"],
            "scan": scanned["comfyui_version"],
        },
        "workflow": {
            "manifest_count": len(actual_workflows),
            "scan_count": len(scanned_workflows),
            "matched_count": len(actual_workflows & scanned_workflows),
            "missing": sorted(actual_workflows - scanned_workflows),
            "extra": sorted(scanned_workflows - actual_workflows),
        },
        "nodes": {
            "manifest_count": len(actual_nodes),
            "scan_count": len(scanned["custom_nodes"]),
            "matched_count": len(matched_node_identifiers),
            "missing": sorted(set(actual_nodes) - matched_node_identifiers),
            "review_required_count": sum(1 for node in scanned["custom_nodes"] if node.get("requires_review")),
        },
        "models": {
            "manifest_graph_count": len(actual_models_strict),
            "manifest_all_count": len({_model_key(model, mode="strict") for model in manifest["models"]}),
            "manifest_manual_count": len(manifest["models"]) - len(graph_models),
            "scan_count": len(scanned_models_strict),
            "matched_path": len(actual_models_path & scanned_models_path),
            "matched_strict": len(actual_models_strict & scanned_models_strict),
            "matched_loose": len(actual_models_loose & scanned_models_loose),
            "missing_path": sorted(actual_models_path - scanned_models_path)[:40],
            "extra_path": sorted(scanned_models_path - actual_models_path)[:40],
            "missing_strict": sorted(actual_models_strict - scanned_models_strict)[:40],
            "extra_strict": sorted(scanned_models_strict - actual_models_strict)[:40],
            "missing_loose": sorted(actual_models_loose - scanned_models_loose)[:40],
            "extra_loose": sorted(scanned_models_loose - actual_models_loose)[:40],
        },
        "warnings": scanned["warnings"],
        "models_scanned": scanned["models_scanned"],
    }
    result["scores"] = _scores_for_result(result)
    return result


def _is_managed_environment_dir(env_dir: Path) -> bool:
    return (
        env_dir.is_dir()
        and (env_dir / ".cec" / "pyproject.toml").exists()
        and (env_dir / "ComfyUI").is_dir()
    )


def _load_manifest(env_dir: Path) -> dict[str, Any]:
    with (env_dir / ".cec" / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)

    comfygit = data.get("tool", {}).get("comfygit", {})
    workflows = {
        name: value
        for name, value in (comfygit.get("workflows", {}) or {}).items()
        if isinstance(value, dict)
    }
    models: list[dict[str, Any]] = []
    for workflow_name, workflow_data in workflows.items():
        for model in workflow_data.get("models", []) or []:
            if not isinstance(model, dict) or not model.get("filename"):
                continue
            node_refs = model.get("nodes", []) or []
            models.append({
                "workflow": workflow_name,
                "filename": model.get("filename"),
                "category": model.get("category"),
                "relative_path": model.get("relative_path"),
                "declared_by": model.get("declared_by"),
                "node_ref_count": len(node_refs),
            })

    return {
        "comfyui_version": comfygit.get("comfyui_version"),
        "nodes": comfygit.get("nodes", {}) or {},
        "workflows": workflows,
        "models": models,
    }


def _model_key(model: dict[str, Any], *, mode: str = "strict", loose: bool = False) -> tuple[str, str, str, str]:
    filename = model.get("filename")
    relative_path = _model_relative_path(model)
    if mode == "path":
        filename = _basename(filename)
    elif loose:
        filename = _basename(filename)
        relative_path = None
    else:
        relative_path = None
    return (
        _normalize(model.get("workflow")),
        _normalize(filename),
        _normalize(model.get("category")),
        _normalize(relative_path),
    )


def _scan_model_key(model: dict[str, Any], *, mode: str = "strict", loose: bool = False) -> tuple[str, str, str, str]:
    filename = model.get("filename")
    relative_path = _model_relative_path(model)
    if mode == "path":
        filename = _basename(filename)
    elif loose:
        filename = _basename(filename)
        relative_path = None
    else:
        relative_path = None
    return (
        _normalize(model.get("workflow")),
        _normalize(filename),
        _normalize(model.get("category")),
        _normalize(relative_path),
    )


def _model_relative_path(model: dict[str, Any]) -> Any:
    relative_path = model.get("relative_path")
    if relative_path:
        return relative_path
    filename = model.get("filename")
    category = model.get("category")
    if filename and category:
        return f"{category}/{filename}"
    return relative_path


def _manifest_node_aliases(identifier: str, info: dict[str, Any], *, ignored_nodes: set[str]) -> set[str]:
    aliases = {
        _normalize(identifier),
        _normalize(info.get("name")),
        _normalize(info.get("registry_id")),
        _repo_slug(info.get("repository")),
    }
    return {alias for alias in aliases if alias and alias not in ignored_nodes}


def _scanned_node_aliases(node: dict[str, Any], *, ignored_nodes: set[str]) -> set[str]:
    aliases = {
        _normalize(node.get("name")),
        _normalize(node.get("registry_id")),
        _repo_slug(node.get("repository")),
        _repo_slug(node.get("install_spec")),
    }
    return {alias for alias in aliases if alias and alias not in ignored_nodes}


def _scores_for_result(result: dict[str, Any]) -> dict[str, float | None]:
    return {
        "workflow_recall_pct": _pct(result["workflow"]["matched_count"], result["workflow"]["manifest_count"]),
        "node_recall_pct": _pct(result["nodes"]["matched_count"], result["nodes"]["manifest_count"]),
        "model_recall_path_pct": _pct(result["models"]["matched_path"], result["models"]["manifest_graph_count"]),
        "model_precision_path_pct": _pct(result["models"]["matched_path"], result["models"]["scan_count"]),
        "model_recall_strict_pct": _pct(result["models"]["matched_strict"], result["models"]["manifest_graph_count"]),
        "model_precision_strict_pct": _pct(result["models"]["matched_strict"], result["models"]["scan_count"]),
        "model_recall_loose_pct": _pct(result["models"]["matched_loose"], result["models"]["manifest_graph_count"]),
        "model_precision_loose_pct": _pct(result["models"]["matched_loose"], result["models"]["scan_count"]),
    }


def _aggregate_scores(results: list[dict[str, Any]]) -> dict[str, float | None]:
    totals = {
        "workflow_manifest": 0,
        "workflow_matched": 0,
        "node_manifest": 0,
        "node_matched": 0,
        "model_manifest": 0,
        "model_matched_strict": 0,
        "model_matched_loose": 0,
        "model_matched_path": 0,
        "model_scanned": 0,
    }
    for result in results:
        if "error" in result:
            continue
        totals["workflow_manifest"] += result["workflow"]["manifest_count"]
        totals["workflow_matched"] += result["workflow"]["matched_count"]
        totals["node_manifest"] += result["nodes"]["manifest_count"]
        totals["node_matched"] += result["nodes"]["matched_count"]
        totals["model_manifest"] += result["models"]["manifest_graph_count"]
        totals["model_matched_path"] += result["models"]["matched_path"]
        totals["model_matched_strict"] += result["models"]["matched_strict"]
        totals["model_matched_loose"] += result["models"]["matched_loose"]
        totals["model_scanned"] += result["models"]["scan_count"]

    return {
        "workflow_recall_pct": _pct(totals["workflow_matched"], totals["workflow_manifest"]),
        "node_recall_pct": _pct(totals["node_matched"], totals["node_manifest"]),
        "model_recall_path_pct": _pct(totals["model_matched_path"], totals["model_manifest"]),
        "model_precision_path_pct": _pct(totals["model_matched_path"], totals["model_scanned"]),
        "model_recall_strict_pct": _pct(totals["model_matched_strict"], totals["model_manifest"]),
        "model_precision_strict_pct": _pct(totals["model_matched_strict"], totals["model_scanned"]),
        "model_recall_loose_pct": _pct(totals["model_matched_loose"], totals["model_manifest"]),
        "model_precision_loose_pct": _pct(totals["model_matched_loose"], totals["model_scanned"]),
    }


def print_text_report(result: dict[str, Any]) -> None:
    print(f"Workspace: {result['workspace']}")
    print(f"Environments: {result['environment_count']}")
    print(f"Aggregate: {result['aggregate']}")
    print()

    for item in result["results"]:
        if "error" in item:
            print(f"{item['environment']}: ERROR {item['error']}")
            continue
        print(
            f"{item['environment']}: "
            f"wf {item['workflow']['matched_count']}/{item['workflow']['manifest_count']}, "
            f"nodes {item['nodes']['matched_count']}/{item['nodes']['manifest_count']}, "
            f"models path {item['models']['matched_path']}/{item['models']['manifest_graph_count']}, "
            f"models strict {item['models']['matched_strict']}/{item['models']['manifest_graph_count']}, "
            f"scan {item['models']['scan_count']}, "
            f"loose {item['models']['matched_loose']}/{item['models']['manifest_graph_count']}"
        )
        if item["warnings"]:
            print(f"  warnings: {len(item['warnings'])}")
        if item["workflow"]["missing"] or item["workflow"]["extra"]:
            print(f"  workflow missing={item['workflow']['missing']} extra={item['workflow']['extra']}")
        if item["nodes"]["missing"]:
            print(f"  node missing={item['nodes']['missing']}")
        if item["models"]["missing_path"] or item["models"]["extra_path"]:
            print(f"  model missing path={item['models']['missing_path']}")
            print(f"  model extra path={item['models']['extra_path']}")
        if item["models"]["missing_strict"] or item["models"]["extra_strict"]:
            print(f"  model missing strict={item['models']['missing_strict']}")
            print(f"  model extra strict={item['models']['extra_strict']}")


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _basename(value: Any) -> str:
    return Path(str(value or "").replace("\\", "/")).name


def _repo_slug(url: Any) -> str:
    normalized = str(url or "").rstrip("/").removesuffix(".git")
    return _normalize(normalized.rsplit("/", 1)[-1])


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator * 100, 1)


if __name__ == "__main__":
    sys.exit(main())
