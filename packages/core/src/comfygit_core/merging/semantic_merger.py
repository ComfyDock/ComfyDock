"""Semantic pyproject.toml merger for ComfyGit environments.

Intelligently merges pyproject.toml based on workflow resolutions,
handling the derived nature of most pyproject sections.
"""

import re

from ..models.merge_plan import Resolution


class SemanticMerger:
    """Intelligently merges pyproject.toml based on workflow resolutions.

    Section Types:
    - DERIVED: Regenerate from merged workflows (nodes, workflow configs)
    - SEMANTIC MERGE: Merge by key intelligently (models - union sources)
    - PRESERVE LOCAL: Never merge from remote (UV config, platform settings)
    - PRESERVE FROM BOTH: Keep manual additions from both (manual dep groups)
    """

    def merge(
        self,
        base_config: dict,
        target_config: dict,
        workflow_resolutions: dict[str, Resolution],
        merged_workflow_files: list[str],
    ) -> dict:
        """Build merged pyproject.toml.

        Args:
            base_config: pyproject.toml from HEAD (ours)
            target_config: pyproject.toml from target branch (theirs)
            workflow_resolutions: User's per-workflow choices
            merged_workflow_files: List of workflow names that exist after file merge

        Returns:
            Complete merged pyproject.toml as dict
        """
        result: dict = {}

        # 1. Project metadata: Always copy from base
        if "project" in base_config:
            result["project"] = dict(base_config["project"])

        # 2. Initialize tool.comfygit structure
        result["tool"] = {}
        result["tool"]["comfygit"] = {}

        # 3. Preserve local comfygit metadata (version, python, torch_backend)
        self._preserve_comfygit_metadata(result, base_config)

        # 4. Workflows: Based on which files exist and user choices
        workflow_sources = self._merge_workflows(
            result, base_config, target_config, workflow_resolutions, merged_workflow_files
        )

        # 5. Nodes: Determined by merged workflows' requirements
        self._merge_nodes(result, base_config, target_config, workflow_sources)

        # 6. Models: Semantic merge by hash, union sources
        self._merge_models(result, base_config, target_config, merged_workflow_files)

        # 7. Dependency groups: Regenerate auto + preserve manual
        self._merge_dependency_groups(result, base_config, target_config)

        # 8. UV config: Always keep base (platform-specific)
        self._preserve_uv_config(result, base_config)

        return result

    def _preserve_comfygit_metadata(self, result: dict, base_config: dict) -> None:
        """Preserve local environment metadata from base."""
        base_cg = base_config.get("tool", {}).get("comfygit", {})

        for key in ["comfyui_version", "python_version", "torch_backend"]:
            if key in base_cg:
                result["tool"]["comfygit"][key] = base_cg[key]

    def _merge_workflows(
        self,
        result: dict,
        base_config: dict,
        target_config: dict,
        workflow_resolutions: dict[str, Resolution],
        merged_workflow_files: list[str],
    ) -> dict[str, str]:
        """Merge workflow configs based on resolutions.

        Returns:
            Mapping of workflow name to actual source ("base" or "target").
        """
        base_workflows = base_config.get("tool", {}).get("comfygit", {}).get("workflows", {})
        target_workflows = target_config.get("tool", {}).get("comfygit", {}).get("workflows", {})

        merged = {}
        workflow_sources: dict[str, str] = {}  # wf_name -> "base" | "target"

        for wf_name in merged_workflow_files:
            resolution = workflow_resolutions.get(wf_name)

            if resolution == "take_target":
                # Use target workflow config
                if wf_name in target_workflows:
                    merged[wf_name] = dict(target_workflows[wf_name])
                    workflow_sources[wf_name] = "target"
                elif wf_name in base_workflows:
                    merged[wf_name] = dict(base_workflows[wf_name])
                    workflow_sources[wf_name] = "base"
            elif resolution == "take_base":
                # Use base workflow config
                if wf_name in base_workflows:
                    merged[wf_name] = dict(base_workflows[wf_name])
                    workflow_sources[wf_name] = "base"
                elif wf_name in target_workflows:
                    merged[wf_name] = dict(target_workflows[wf_name])
                    workflow_sources[wf_name] = "target"
            else:
                # No explicit resolution - prefer base, fall back to target
                if wf_name in base_workflows:
                    merged[wf_name] = dict(base_workflows[wf_name])
                    workflow_sources[wf_name] = "base"
                elif wf_name in target_workflows:
                    merged[wf_name] = dict(target_workflows[wf_name])
                    workflow_sources[wf_name] = "target"

        result["tool"]["comfygit"]["workflows"] = merged
        return workflow_sources

    def _merge_nodes(
        self,
        result: dict,
        base_config: dict,
        target_config: dict,
        workflow_sources: dict[str, str],
    ) -> None:
        """Merge nodes based on which workflows need them.

        Args:
            workflow_sources: Mapping of workflow name to actual source
                ("base" or "target") as determined by _merge_workflows.
        """
        base_nodes = base_config.get("tool", {}).get("comfygit", {}).get("nodes", {})
        target_nodes = target_config.get("tool", {}).get("comfygit", {}).get("nodes", {})

        # Collect all required nodes from merged workflows
        required_nodes: set[str] = set()
        merged_workflows = result["tool"]["comfygit"].get("workflows", {})

        for wf_name, wf_config in merged_workflows.items():
            nodes_list = wf_config.get("nodes", [])
            required_nodes.update(nodes_list)

        # Build merged nodes dict
        merged_nodes = {}
        for node_id in required_nodes:
            # Check ALL workflows that reference this node.
            # If any workflow sourced from target uses this node, prefer target entry.
            uses_target = any(
                workflow_sources.get(wf_name) == "target"
                for wf_name, wf_config in merged_workflows.items()
                if node_id in wf_config.get("nodes", [])
            )
            source_config = target_nodes if uses_target else base_nodes

            if node_id in source_config:
                merged_nodes[node_id] = dict(source_config[node_id])
            elif node_id in base_nodes:
                merged_nodes[node_id] = dict(base_nodes[node_id])
            elif node_id in target_nodes:
                merged_nodes[node_id] = dict(target_nodes[node_id])

        result["tool"]["comfygit"]["nodes"] = merged_nodes

    def _merge_models(
        self,
        result: dict,
        base_config: dict,
        target_config: dict,
        merged_workflow_files: list[str],
    ) -> None:
        """Merge model tables by hash, unioning sources."""
        base_models = base_config.get("tool", {}).get("comfygit", {}).get("models", {})
        target_models = target_config.get("tool", {}).get("comfygit", {}).get("models", {})

        # Collect model hashes referenced by merged workflows
        referenced_hashes = self._get_referenced_model_hashes(result, merged_workflow_files)

        merged_models = {}
        for model_hash in referenced_hashes:
            base_entry = base_models.get(model_hash, {})
            target_entry = target_models.get(model_hash, {})

            if base_entry and target_entry:
                # Both have it - merge, unioning sources
                merged_entry = dict(base_entry)
                base_sources = base_entry.get("sources", [])
                target_sources = target_entry.get("sources", [])
                # Union sources, preserving order (base first)
                all_sources = list(base_sources)
                for src in target_sources:
                    if src not in all_sources:
                        all_sources.append(src)
                merged_entry["sources"] = all_sources
                merged_models[model_hash] = merged_entry
            elif target_entry:
                merged_models[model_hash] = dict(target_entry)
            elif base_entry:
                merged_models[model_hash] = dict(base_entry)

        result["tool"]["comfygit"]["models"] = merged_models

    def _get_referenced_model_hashes(
        self, result: dict, merged_workflow_files: list[str]
    ) -> set[str]:
        """Get all model hashes referenced by merged workflows."""
        hashes = set()
        workflows = result.get("tool", {}).get("comfygit", {}).get("workflows", {})

        for wf_name in merged_workflow_files:
            wf_config = workflows.get(wf_name, {})
            models_list = wf_config.get("models", [])
            hashes.update(models_list)

        return hashes

    def _is_auto_generated_group(self, name: str) -> bool:
        """Check if dependency group is auto-generated (has hash suffix).

        Pattern: node-name-8charhex (e.g., comfy-mtb-9bb64296)
        """
        return bool(re.match(r".*-[a-f0-9]{8}$", name))

    def _merge_dependency_groups(
        self,
        result: dict,
        base_config: dict,
        target_config: dict,
    ) -> None:
        """Merge dependency groups: regenerate auto, preserve manual."""
        base_groups = base_config.get("dependency-groups", {})
        target_groups = target_config.get("dependency-groups", {})

        merged_groups: dict = {}

        # Collect MANUAL groups from both branches
        for groups in [base_groups, target_groups]:
            for name, deps in groups.items():
                if not self._is_auto_generated_group(name):
                    if name not in merged_groups:
                        merged_groups[name] = list(deps)
                    else:
                        # Merge deps if both have same group
                        existing = set(merged_groups[name])
                        for dep in deps:
                            if dep not in existing:
                                merged_groups[name].append(dep)

        # Auto-generated groups will be rebuilt during sync
        # (We don't copy them here - they're regenerated from node requirements)

        if merged_groups:
            result["dependency-groups"] = merged_groups

    def _preserve_uv_config(self, result: dict, base_config: dict) -> None:
        """Preserve platform-specific UV config from base."""
        base_uv = base_config.get("tool", {}).get("uv", {})

        if base_uv:
            result["tool"]["uv"] = dict(base_uv)
