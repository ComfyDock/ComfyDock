"""Merge compatibility validator for ComfyGit environments.

Validates that merge resolutions won't create node version conflicts.
"""

from ..models.merge_plan import MergeValidation, NodeVersionConflict, Resolution


class MergeValidator:
    """Validates merge compatibility before execution."""

    def validate(
        self,
        base_config: dict,
        target_config: dict,
        workflow_resolutions: dict[str, Resolution],
    ) -> MergeValidation:
        """Check if resolved merge would be consistent.

        Returns:
            MergeValidation with is_compatible and any conflicts
        """
        # Determine final workflow set
        merged_workflows = self._compute_merged_workflows(
            base_config, target_config, workflow_resolutions
        )

        # Extract all node requirements with versions
        required_nodes = self._extract_node_requirements(
            base_config, target_config, merged_workflows, workflow_resolutions
        )

        # Check for version conflicts
        conflicts = self._detect_version_conflicts(required_nodes)

        return MergeValidation(
            is_compatible=len(conflicts) == 0,
            conflicts=conflicts,
            merged_workflow_set=merged_workflows,
        )

    def _compute_merged_workflows(
        self,
        base_config: dict,
        target_config: dict,
        workflow_resolutions: dict[str, Resolution],
    ) -> list[str]:
        """Compute final workflow set after merge."""
        base_workflows = set(
            base_config.get("tool", {}).get("comfygit", {}).get("workflows", {}).keys()
        )
        target_workflows = set(
            target_config.get("tool", {}).get("comfygit", {}).get("workflows", {}).keys()
        )

        # Start with base workflows
        result = set(base_workflows)

        # Add target-only workflows
        result.update(target_workflows)

        # Handle resolutions
        for _wf_name, resolution in workflow_resolutions.items():
            if resolution == "take_base":
                # Keep base version (already in result)
                pass
            elif resolution == "take_target":
                # Use target version (already in result from union)
                pass

        return sorted(result)

    def _extract_node_requirements(
        self,
        base_config: dict,
        target_config: dict,
        merged_workflows: list[str],
        workflow_resolutions: dict[str, Resolution],
    ) -> dict[str, list[tuple[str, str, str]]]:
        """Extract node requirements: {node_id: [(version, workflow_name, source)]}"""
        requirements: dict[str, list[tuple[str, str, str]]] = {}

        base_wf_configs = base_config.get("tool", {}).get("comfygit", {}).get("workflows", {})
        target_wf_configs = target_config.get("tool", {}).get("comfygit", {}).get("workflows", {})
        base_nodes = base_config.get("tool", {}).get("comfygit", {}).get("nodes", {})
        target_nodes = target_config.get("tool", {}).get("comfygit", {}).get("nodes", {})

        for wf_name in merged_workflows:
            # Determine which config this workflow comes from
            resolution = workflow_resolutions.get(wf_name)

            # Explicit resolution takes precedence
            if resolution == "take_target":
                wf_configs = target_wf_configs
                node_configs = target_nodes
                source = "target"
            elif resolution == "take_base":
                wf_configs = base_wf_configs
                node_configs = base_nodes
                source = "base"
            else:
                # No explicit resolution - use source where workflow exists
                # Prefer base, but use target if only in target
                if wf_name in base_wf_configs:
                    wf_configs = base_wf_configs
                    node_configs = base_nodes
                    source = "base"
                else:
                    wf_configs = target_wf_configs
                    node_configs = target_nodes
                    source = "target"

            wf_data = wf_configs.get(wf_name, {})
            for node_id in wf_data.get("nodes", []):
                node_data = node_configs.get(node_id, {})
                version = node_data.get("version", "unknown")

                if node_id not in requirements:
                    requirements[node_id] = []
                requirements[node_id].append((version, wf_name, source))

        return requirements

    def _detect_version_conflicts(
        self,
        requirements: dict[str, list[tuple[str, str, str]]],
    ) -> list[NodeVersionConflict]:
        """Detect nodes required at different versions."""
        conflicts = []

        for node_id, version_info in requirements.items():
            versions = {v[0] for v in version_info}
            if len(versions) > 1:
                # Get base and target versions
                base_version = None
                target_version = None
                affected = []

                for version, wf_name, source in version_info:
                    affected.append((wf_name, source))
                    if source == "base" and base_version is None:
                        base_version = version
                    elif source == "target" and target_version is None:
                        target_version = version

                conflicts.append(
                    NodeVersionConflict(
                        node_id=node_id,
                        node_name=node_id,  # Could be enhanced with actual name lookup
                        base_version=base_version,
                        target_version=target_version,
                        affected_workflows=affected,
                    )
                )

        return conflicts
