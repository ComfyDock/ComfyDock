# formatters/error_formatter.py

from comfygit_core.models.exceptions import (
    CDDependencyConflictError,
    CDNodeConflictError,
    CDRegistryDataError,
    NodeAction,
)


class NodeErrorFormatter:
    """Formats core library errors for CLI display."""

    @staticmethod
    def format_registry_error(error: CDRegistryDataError) -> str:
        """Format registry data error with recovery commands."""
        lines = [str(error)]

        if error.cache_path:
            lines.append(f"  Cache location: {error.cache_path}")

        if error.can_retry:
            lines.append("\nTo fix this issue:")
            lines.append("  1. Download registry data:")
            lines.append("     → cg registry update")
            lines.append("")
            lines.append("  2. Check download status:")
            lines.append("     → cg registry status")

        return "\n".join(lines)

    @staticmethod
    def format_node_action(action: NodeAction) -> str:
        """Convert NodeAction to CLI command string."""
        if action.action_type == 'remove_node':
            return f"cg node remove {action.node_identifier}"

        elif action.action_type == 'add_node_dev':
            return f"cg node add {action.node_name} --dev"

        elif action.action_type == 'add_node_force':
            return f"cg node add {action.node_identifier} --force"

        elif action.action_type == 'add_node_version':
            return f"cg node add {action.node_identifier}"

        elif action.action_type == 'rename_directory':
            return f"mv custom_nodes/{action.directory_name} custom_nodes/{action.new_name}"

        elif action.action_type == 'update_node':
            return f"cg node update {action.node_identifier}"

        elif action.action_type == 'add_constraint':
            return "cg constraint add \"<package>==<version>\""

        elif action.action_type == 'skip_node':
            return "# Don't install this node"

        return f"# Unknown action: {action.action_type}"

    @staticmethod
    def format_conflict_error(error: CDNodeConflictError) -> str:
        """Format a conflict error with suggested actions."""
        if not error.context:
            return str(error)

        lines = [str(error)]

        # Add context details
        ctx = error.context
        if ctx.local_remote_url:
            lines.append(f"  Filesystem: {ctx.local_remote_url}")
        if ctx.expected_remote_url:
            lines.append(f"  Registry:   {ctx.expected_remote_url}")

        # Add suggested actions
        if ctx.suggested_actions:
            lines.append("\nSuggested actions:")
            for i, action in enumerate(ctx.suggested_actions, 1):
                cmd = NodeErrorFormatter.format_node_action(action)
                desc = action.description
                lines.append(f"  {i}. {desc}")
                lines.append(f"     → {cmd}")

        return "\n".join(lines)

    @staticmethod
    def format_dependency_conflict_error(error: CDDependencyConflictError, verbose: bool = False) -> str:
        """Format a dependency conflict error with actionable suggestions.

        Args:
            error: The dependency conflict error
            verbose: If True, include full UV stderr output

        Returns:
            Formatted error message
        """
        if not error.context:
            return str(error)

        lines = [f"✗ {str(error)}"]

        ctx = error.context

        # Show simplified conflict descriptions
        if ctx.conflict_descriptions:
            lines.append("")
            for conflict in ctx.conflict_descriptions[:3]:  # Limit to top 3
                lines.append(f"  • {conflict}")

        # Show package pairs if available
        if ctx.conflicting_packages:
            lines.append("")
            lines.append("Conflicting packages:")
            for pkg1, pkg2 in ctx.conflicting_packages[:3]:
                lines.append(f"  - {pkg1} ↔ {pkg2}")

        # Add suggested actions
        if ctx.suggested_actions:
            lines.append("")
            lines.append("Options:")
            for i, action in enumerate(ctx.suggested_actions, 1):
                desc = action.description
                cmd = NodeErrorFormatter.format_node_action(action)
                lines.append(f"  {i}. {desc}")
                if action.action_type != 'skip_node':  # Skip "don't install" has no command
                    lines.append(f"     → {cmd}")

        # Add hints
        lines.append("")
        lines.append("To see full UV error output: Add --verbose flag")
        lines.append("To force installation anyway: Add --no-test flag (not recommended)")

        # Show full stderr if verbose
        if verbose and ctx.raw_stderr:
            lines.append("")
            lines.append("=== Full UV Error Output ===")
            lines.append(ctx.raw_stderr)
            lines.append("=== End UV Output ===")

        return "\n".join(lines)
