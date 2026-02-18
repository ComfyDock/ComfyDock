"""Environment-specific commands for ComfyGit CLI."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import shutil
from functools import cached_property
from typing import TYPE_CHECKING, Any

from comfygit_core.models.exceptions import (
    CDDependencyConflictError,
    CDNodeConflictError,
    CDRegistryDataError,
    UVCommandError,
)

from .formatters.error_formatter import NodeErrorFormatter
from .strategies.interactive import InteractiveModelStrategy, InteractiveNodeStrategy

if TYPE_CHECKING:
    from comfygit_core.core.environment import Environment
    from comfygit_core.core.workspace import Workspace
    from comfygit_core.models.environment import EnvironmentStatus
    from comfygit_core.models.workflow import WorkflowAnalysisStatus

from .cli_utils import get_workspace_or_exit
from .logging.environment_logger import with_env_logging
from .logging.logging_config import get_logger

logger = get_logger(__name__)


class EnvironmentCommands:
    """Handler for environment-specific commands - simplified for MVP."""

    def __init__(self) -> None:
        """Initialize environment commands handler."""
        pass

    @cached_property
    def workspace(self) -> Workspace:
        return get_workspace_or_exit()

    def _get_or_create_workspace(self, args: argparse.Namespace) -> Workspace:
        """Get existing workspace or initialize a new one with user confirmation.

        This is a delegation to GlobalCommands._get_or_create_workspace to avoid duplication.
        We import and use GlobalCommands here for the shared logic.

        Args:
            args: Command arguments, must have 'yes' attribute for non-interactive mode

        Returns:
            Workspace instance (existing or newly created)
        """
        from .global_commands import GlobalCommands

        global_cmds = GlobalCommands()
        return global_cmds._get_or_create_workspace(args)

    def _get_env(self, args) -> Environment:
        """Get environment from global -e flag or active environment.

        Args:
            args: Parsed command line arguments

        Returns:
            Environment instance

        Raises:
            SystemExit if no environment specified
        """
        # Check global -e flag first
        if hasattr(args, 'target_env') and args.target_env:
            try:
                env = self.workspace.get_environment(args.target_env)
                return env
            except Exception:
                print(f"✗ Unknown environment: {args.target_env}")
                print("Available environments:")
                for e in self.workspace.list_environments():
                    print(f"  • {e.name}")
                sys.exit(1)

        # Fall back to active environment
        active = self.workspace.get_active_environment()
        if not active:
            print("✗ No environment specified. Either:")
            print("  • Use -e flag: cg -e my-env <command>")
            print("  • Set active: cg use <name>")
            sys.exit(1)
        return active

    def _get_python_version(self, env: Environment) -> str:
        """Get Python version from environment."""
        python_version_file = env.cec_path / ".python-version"
        if python_version_file.exists():
            return python_version_file.read_text(encoding="utf-8").strip()
        return "3.12"

    def _get_or_probe_backend(
        self, env: Environment, override: str | None = None
    ) -> tuple[str, bool]:
        """Get torch backend from file or probe if missing.

        Args:
            env: Environment to get backend for
            override: Optional explicit backend override

        Returns:
            Tuple of (backend_string, was_probed) where was_probed is True
            if we had to auto-probe because no backend was configured.
        """
        if override:
            return override, False

        had_backend = env.pytorch_manager.has_backend()

        try:
            python_version = self._get_python_version(env)
            backend = env.pytorch_manager.ensure_backend(python_version)

            was_probed = not had_backend
            if was_probed:
                print("⚠️  No PyTorch backend configured. Auto-detecting...")
                print(f"✓ Backend detected and saved: {backend}")
                print("   To change: cg env-config torch-backend set <backend>")

            return backend, was_probed
        except Exception as e:
            print(f"✗ Error probing PyTorch backend: {e}")
            print("   Try setting it explicitly: cg env-config torch-backend set <backend>")
            sys.exit(1)

    def _show_legacy_manager_notice(self, env: Environment) -> None:
        """Show legacy manager notice if environment uses symlinked manager."""
        try:
            status = env.get_manager_status()
            if status.is_legacy:
                print("")
                print("Legacy manager detected. Run 'cg manager update' to migrate.")
        except Exception:
            pass  # Silently fail - notice is informational only

    def _format_size(self, size_bytes: int) -> str:
        """Format bytes as human-readable size."""
        for unit in ("B", "KB", "MB", "GB"):
            if abs(size_bytes) < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024  # type: ignore[assignment]
        return f"{size_bytes:.1f} TB"

    def _display_diff_preview(self, diff: Any) -> None:
        """Display a RefDiff to the user."""
        from comfygit_core.models.ref_diff import RefDiff

        if not isinstance(diff, RefDiff):
            return

        summary = diff.summary()
        print(f"\nChanges from {diff.target_ref}:")
        print("-" * 40)

        # Nodes
        if diff.node_changes:
            print("\nNodes:")
            for node_change in diff.node_changes:
                symbol = {"added": "+", "removed": "-", "version_changed": "~"}[
                    node_change.change_type
                ]
                conflict_mark = " (CONFLICT)" if node_change.conflict else ""
                version_info = ""
                if node_change.change_type == "version_changed":
                    version_info = f" ({node_change.base_version} -> {node_change.target_version})"
                print(f"  {symbol} {node_change.name}{version_info}{conflict_mark}")

        # Models
        if diff.model_changes:
            print("\nModels:")
            for model_change in diff.model_changes:
                symbol = "+" if model_change.change_type == "added" else "-"
                size_str = self._format_size(model_change.size)
                print(f"  {symbol} {model_change.filename} ({size_str})")

        # Workflows
        if diff.workflow_changes:
            print("\nWorkflows:")
            for wf_change in diff.workflow_changes:
                symbol = {"added": "+", "deleted": "-", "modified": "~"}[
                    wf_change.change_type
                ]
                conflict_mark = " (CONFLICT)" if wf_change.conflict else ""
                print(f"  {symbol} {wf_change.name}.json{conflict_mark}")

        # Dependencies
        deps = diff.dependency_changes
        if deps.has_changes:
            print("\nDependencies:")
            for dep in deps.added:
                print(f"  + {dep.get('name', 'unknown')}")
            for dep in deps.removed:
                print(f"  - {dep.get('name', 'unknown')}")
            for dep in deps.updated:
                print(f"  ~ {dep.get('name', 'unknown')} ({dep.get('old', '?')} -> {dep.get('new', '?')})")

        # Summary
        print()
        summary_parts = []
        if summary["nodes_added"] or summary["nodes_removed"]:
            summary_parts.append(
                f"{summary['nodes_added']} nodes added, {summary['nodes_removed']} removed"
            )
        if summary["models_added"]:
            summary_parts.append(
                f"{summary['models_added']} models to download ({self._format_size(summary['models_added_size'])})"
            )
        if summary["workflows_added"] or summary["workflows_modified"] or summary["workflows_deleted"]:
            summary_parts.append(
                f"{summary['workflows_added']} workflows added, {summary['workflows_modified']} modified, {summary['workflows_deleted']} deleted"
            )
        if summary["conflicts"]:
            summary_parts.append(f"{summary['conflicts']} conflicts to resolve")

        if summary_parts:
            print("Summary:")
            for part in summary_parts:
                print(f"  {part}")

    # === Commands that operate ON environments ===

    @with_env_logging("create")
    def create(self, args: argparse.Namespace, logger=None) -> None:
        """Create a new environment."""
        # Ensure workspace exists, creating it if necessary
        workspace = self._get_or_create_workspace(args)

        print(f"🚀 Creating environment: {args.name}")
        print("   This will download PyTorch and dependencies (may take a few minutes)...")
        print()

        try:
            workspace.create_environment(
                name=args.name,
                comfyui_version=args.comfyui,
                python_version=args.python,
                template_path=args.template,
                torch_backend=args.torch_backend,
                no_manager=getattr(args, "no_manager", False),
            )
        except Exception as e:
            if logger:
                logger.error(f"Environment creation failed for '{args.name}': {e}", exc_info=True)
            print(f"✗ Failed to create environment: {e}", file=sys.stderr)
            sys.exit(1)

        if args.use:
            try:
                workspace.set_active_environment(args.name)

            except Exception as e:
                if logger:
                    logger.error(f"Failed to set active environment '{args.name}': {e}", exc_info=True)
                print(f"✗ Failed to set active environment: {e}", file=sys.stderr)
                sys.exit(1)

        print(f"✓ Environment created: {args.name}")
        if args.use:
            print(f"✓ Active environment set to: {args.name}")
            print("\nNext steps:")
            print("  • Run ComfyUI: cg run")
            print("  • Add nodes: cg node add <node-name>")
        else:
            print("\nNext steps:")
            print(f"  • Run ComfyUI: cg -e {args.name} run")
            print(f"  • Add nodes: cg -e {args.name} node add <node-name>")
            print(f"  • Set as active: cg use {args.name}")

    @with_env_logging("use")
    def use(self, args: argparse.Namespace, logger=None) -> None:
        """Set the active environment."""
        from comfygit_cli.utils.progress import create_model_sync_progress

        try:
            progress = create_model_sync_progress()
            self.workspace.set_active_environment(args.name, progress=progress)
        except Exception as e:
            if logger:
                logger.error(f"Failed to set active environment '{args.name}': {e}", exc_info=True)
            print(f"✗ Failed to set active environment: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"✓ Active environment set to: {args.name}")
        print("You can now run commands without the -e flag")

    @with_env_logging("delete")
    def delete(self, args: argparse.Namespace, logger=None) -> None:
        """Delete an environment."""
        # Check that environment exists (don't require active environment)
        env_path = self.workspace.paths.environments / args.name
        if not env_path.exists():
            print(f"✗ Environment '{args.name}' not found")
            print("\nAvailable environments:")
            for env in self.workspace.list_environments():
                print(f"  • {env.name}")
            sys.exit(1)

        # Confirm deletion unless --yes is specified
        if not args.yes:
            response = input(f"Delete environment '{args.name}'? This cannot be undone. (y/N): ")
            if response.lower() != 'y':
                print("Cancelled")
                return

        print(f"🗑 Deleting environment: {args.name}")

        try:
            self.workspace.delete_environment(args.name)
        except Exception as e:
            if logger:
                logger.error(f"Environment deletion failed for '{args.name}': {e}", exc_info=True)
            print(f"✗ Failed to delete environment: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"✓ Environment deleted: {args.name}")

    # === Commands that operate IN environments ===

    # === Environment Configuration ===

    @with_env_logging("env-config torch-backend show")
    def env_config_torch_show(self, args: argparse.Namespace, logger=None) -> None:
        """Show current PyTorch backend setting for this environment."""
        env = self._get_env(args)

        backend = env.pytorch_manager.get_backend()
        backend_file = env.pytorch_manager.backend_file
        versions = env.pytorch_manager.get_versions()

        print(f"PyTorch Backend: {backend}")
        if versions:
            for pkg, ver in versions.items():
                print(f"   {pkg}={ver}")

        if backend_file.exists():
            print(f"   Source: {backend_file}")
        else:
            print("   Source: auto-detected (no .pytorch-backend file)")
            print()
            print(f"💡 To save this setting: cg env-config torch-backend set {backend}")

    @with_env_logging("env-config torch-backend set")
    def env_config_torch_set(self, args: argparse.Namespace, logger=None) -> None:
        """Set PyTorch backend for this environment.

        Probes for exact versions and stores both backend and version pins.
        """
        from comfygit_core.utils.pytorch_prober import PyTorchProbeError

        env = self._get_env(args)
        backend = args.backend

        # Validate backend format
        if not env.pytorch_manager.is_valid_backend(backend):
            print(f"✗ Invalid backend: {backend}")
            print()
            print("Valid formats:")
            print("  • cu118, cu121, cu124, cu126, cu128 (CUDA)")
            print("  • cpu")
            print("  • rocm6.2, rocm6.3 (AMD)")
            print("  • xpu (Intel)")
            sys.exit(1)

        # Read python version
        python_version_file = env.cec_path / ".python-version"
        python_version = (
            python_version_file.read_text(encoding="utf-8").strip()
            if python_version_file.exists()
            else "3.12"
        )

        # Probe and set backend with versions
        print(f"🔍 Probing PyTorch versions for {backend} (Python {python_version})...")
        try:
            resolved = env.pytorch_manager.probe_and_set_backend(python_version, backend)
        except PyTorchProbeError as e:
            print(f"✗ Error probing PyTorch: {e}")
            sys.exit(1)

        # Show what was stored
        versions = env.pytorch_manager.get_versions()
        print(f"✓ PyTorch backend set to: {resolved}")
        if versions:
            for pkg, ver in versions.items():
                print(f"   {pkg}={ver}")
        print()
        print("Run 'cg sync' to apply the new backend configuration.")

    @with_env_logging("env-config torch-backend detect")
    def env_config_torch_detect(self, args: argparse.Namespace, logger=None) -> None:
        """Auto-detect recommended PyTorch backend using uv probe."""
        from comfygit_core.utils.pytorch_prober import PyTorchProbeError, probe_pytorch_versions

        env = self._get_env(args)
        backend_file = env.pytorch_manager.backend_file

        # Read python version from file
        python_version_file = env.cec_path / ".python-version"
        python_version = (
            python_version_file.read_text(encoding="utf-8").strip()
            if python_version_file.exists()
            else "3.12"
        )

        # Probe for recommended backend
        print(f"🔍 Probing PyTorch compatibility for Python {python_version}...")
        try:
            _, detected = probe_pytorch_versions(python_version, "auto")
        except PyTorchProbeError as e:
            print(f"✗ Error probing PyTorch: {e}")
            sys.exit(1)

        # Get current backend (if any)
        if env.pytorch_manager.has_backend():
            current = env.pytorch_manager.get_backend()
        else:
            current = "(not configured)"

        print(f"Detected backend: {detected}")
        print(f"Current backend:  {current}")

        if backend_file.exists():
            print(f"   Source: {backend_file}")
        else:
            print("   Source: not configured")

        if current != detected and current != "(not configured)":
            print()
            print(f"💡 Consider updating: cg env-config torch-backend set {detected}")
        elif current == "(not configured)":
            print()
            print(f"💡 Set the backend: cg env-config torch-backend set {detected}")

    @with_env_logging("env-config extras show")
    def env_config_extras_show(self, args: argparse.Namespace, logger=None) -> None:
        """Show default optional extras installed during sync."""
        env = self._get_env(args)
        extras = env.get_sync_extras()

        if not extras:
            print("No default sync extras configured")
            return

        print("Default sync extras:")
        for extra in extras:
            print(f"  • {extra}")

    @with_env_logging("env-config extras add")
    def env_config_extras_add(self, args: argparse.Namespace, logger=None) -> None:
        """Add default optional extras to install during sync."""
        env = self._get_env(args)
        added = []
        skipped = []

        for extra in args.extras:
            if env.add_sync_extra(extra):
                added.append(extra)
            else:
                skipped.append(extra)

        if added:
            print(f"✓ Added default extras: {', '.join(added)}")
        if skipped:
            print(f"ℹ️  Already present: {', '.join(skipped)}")

    @with_env_logging("env-config extras remove")
    def env_config_extras_remove(self, args: argparse.Namespace, logger=None) -> None:
        """Remove default optional extras from sync."""
        env = self._get_env(args)
        removed = []
        missing = []

        for extra in args.extras:
            if env.remove_sync_extra(extra):
                removed.append(extra)
            else:
                missing.append(extra)

        if removed:
            print(f"✓ Removed default extras: {', '.join(removed)}")
        if missing:
            print(f"ℹ️  Not configured: {', '.join(missing)}")

    @with_env_logging("overlay list")
    def overlay_list(self, args: argparse.Namespace, logger=None) -> None:
        """List overlays available in the environment."""
        env = self._get_env(args)
        overlays = env.overlay_manager.list_overlays()

        if not overlays:
            print("No overlays found")
            return

        print("Available overlays:")
        for overlay in overlays:
            active_marker = "active" if overlay.is_active else "inactive"
            scope = "local" if overlay.is_local else "shared"
            details = f"{scope}, {active_marker}"
            if overlay.requires:
                details += f", requires: {', '.join(overlay.requires)}"
            suffix = f" - {overlay.description}" if overlay.description else ""
            print(f"  • {overlay.name} ({details}){suffix}")

    @with_env_logging("overlay show")
    def overlay_show(self, args: argparse.Namespace, logger=None) -> None:
        """Show a single overlay TOML file."""
        env = self._get_env(args)

        try:
            resolved_name = env.overlay_manager.resolve_overlay_name(args.name)
            overlay = env.overlay_manager.load_overlay(resolved_name)
        except Exception as e:
            print(f"✗ {e}")
            sys.exit(1)

        scope = "local" if overlay.is_local else "shared"
        print(f"Overlay: {overlay.name} ({scope})")
        print(f"Path: {overlay.path}")
        print()
        print(overlay.path.read_text(encoding="utf-8"))

    @with_env_logging("overlay enable")
    def overlay_enable(self, args: argparse.Namespace, logger=None) -> None:
        """Enable an overlay in local activation config."""
        env = self._get_env(args)
        manager = env.overlay_manager

        try:
            resolved_name = manager.resolve_overlay_name(args.name)
            active_names = manager.get_active_names()
            active_keys = {name.lower() for name in active_names}
            if resolved_name.lower() in active_keys:
                print(f"Overlay already enabled: {resolved_name}")
                return

            manager.set_active_names(active_names + [resolved_name])
            if not manager.is_overlay_compatible(resolved_name):
                print(f"✓ Enabled overlay: {resolved_name} (platform requirements currently unmet)")
                return
            print(f"✓ Enabled overlay: {resolved_name}")
        except Exception as e:
            print(f"✗ {e}")
            sys.exit(1)

    @with_env_logging("overlay disable")
    def overlay_disable(self, args: argparse.Namespace, logger=None) -> None:
        """Disable an overlay in local activation config."""
        env = self._get_env(args)
        manager = env.overlay_manager

        try:
            resolved_name = manager.resolve_overlay_name(args.name)
            active_names = manager.get_active_names()
            filtered = [
                name for name in active_names
                if name.lower() != resolved_name.lower()
            ]
            if len(filtered) == len(active_names):
                print(f"Overlay is not enabled: {resolved_name}")
                return
            manager.set_active_names(filtered)
            print(f"✓ Disabled overlay: {resolved_name}")
        except Exception as e:
            print(f"✗ {e}")
            sys.exit(1)

    @with_env_logging("overlay create")
    def overlay_create(self, args: argparse.Namespace, logger=None) -> None:
        """Create an overlay template file."""
        from comfygit_core.models.overlay import OverlayConfig

        env = self._get_env(args)
        try:
            OverlayConfig.validate_name(args.name)
        except Exception as e:
            print(f"✗ {e}")
            sys.exit(1)

        overlay_path = env.cec_path / "overlays" / f"{args.name}.toml"
        if overlay_path.exists():
            print(f"✗ Overlay already exists: {args.name}")
            sys.exit(1)

        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        overlay_path.write_text(
            """[overlay]
# description = "Describe this overlay"
# kind = "pytorch"
# requires = ["cuda"]

[dependencies]
packages = []

[sources]
# package-name = { git = "https://github.com/user/repo.git" }

[settings]
no-build-isolation-package = []
override-dependencies = []
environments = []

[[dependency-metadata]]
# name = "package-name"
# version = "1.0.0"
# requires-dist = ["torch"]

[constraints]
packages = []

[[index]]
# name = "custom-index"
# url = "https://example.com/simple"
# explicit = true
""",
            encoding="utf-8",
        )

        scope = "local" if args.name.startswith(".") else "shared"
        print(f"✓ Created {scope} overlay: {args.name}")
        print(f"  {overlay_path}")

    @with_env_logging("run")
    def run(self, args: argparse.Namespace) -> None:
        """Run ComfyUI in the specified environment."""
        RESTART_EXIT_CODE = 42
        env = self._get_env(args)
        comfyui_args = args.args if hasattr(args, 'args') else []
        if comfyui_args and comfyui_args[0] == "--":
            comfyui_args = comfyui_args[1:]
        no_sync = getattr(args, 'no_sync', False)
        extras = getattr(args, 'extra', None) or []
        all_extras = getattr(args, 'all_extras', False)
        overlay_names = getattr(args, 'overlay', None) or []

        if no_sync and overlay_names:
            print("✗ Cannot use --overlay with --no-sync. Overlays require a sync to take effect.")
            sys.exit(1)

        # Handle torch-backend: use override, read from file, or probe if missing
        torch_backend_override = getattr(args, 'torch_backend', None)
        torch_backend, was_probed = self._get_or_probe_backend(env, torch_backend_override)

        if torch_backend_override:
            print(f"🔧 Using PyTorch backend override: {torch_backend}")
        elif was_probed:
            print(f"✓ Backend detected and saved: {torch_backend}")
            print("   To change: cg env-config torch-backend set <backend>")
        else:
            print(f"🔧 Using PyTorch backend: {torch_backend}")

        current_branch = env.get_current_branch()
        branch_display = f" (on {current_branch})" if current_branch else " (detached HEAD)"

        while True:
            # Sync before running (unless --no-sync)
            # Use explicit override if provided, otherwise None (backend is now in file)
            if not no_sync:
                print(f"🔄 Syncing environment: {env.name}")
                env.sync(
                    preserve_workflows=True,
                    remove_extra_nodes=False,
                    backend_override=torch_backend_override if torch_backend_override else None,
                    overlay_names=overlay_names,
                    verbose=True,
                    extras=extras,
                    all_extras=all_extras,
                )

            print(f"🎮 Starting ComfyUI in environment: {env.name}{branch_display}")
            if comfyui_args:
                print(f"   Arguments: {' '.join(comfyui_args)}")

            result = env.run(comfyui_args)

            if result.returncode == RESTART_EXIT_CODE:
                print("\n🔄 Restart requested, syncing dependencies...\n")
                no_sync = False  # Ensure sync runs on restart
                continue

            sys.exit(result.returncode)

    @with_env_logging("sync")
    def sync(self, args: argparse.Namespace, logger=None) -> None:
        """Sync environment packages and dependencies."""
        env = self._get_env(args)

        # Handle torch-backend: use override, read from file, or probe if missing
        torch_backend_override = getattr(args, 'torch_backend', None)
        torch_backend, was_probed = self._get_or_probe_backend(env, torch_backend_override)

        if torch_backend_override:
            print(f"🔧 Using PyTorch backend override: {torch_backend}")
        elif was_probed:
            print(f"✓ Backend detected and saved: {torch_backend}")
            print("   To change: cg env-config torch-backend set <backend>")
        else:
            print(f"🔧 Using PyTorch backend: {torch_backend}")

        print(f"\n🔄 Syncing environment: {env.name}")

        verbose = getattr(args, 'verbose', False)
        extras = getattr(args, 'extra', None) or []
        all_extras = getattr(args, 'all_extras', False)
        overlay_names = getattr(args, 'overlay', None) or []

        try:
            # Use explicit override if provided, otherwise None (backend is now in file)
            result = env.sync(
                dry_run=False,
                model_strategy="skip",  # Sync command focuses on packages
                remove_extra_nodes=False,  # Don't remove nodes, just sync
                verbose=verbose,
                overlay_names=overlay_names,
                extras=extras,
                all_extras=all_extras,
                backend_override=torch_backend_override if torch_backend_override else None,
            )

            if result.success:
                print("\n✓ Sync complete")
                if result.packages_synced:
                    print(f"   Packages synced: {result.packages_synced}")
                if result.dependency_groups_installed:
                    print(f"   Dependency groups: {', '.join(result.dependency_groups_installed)}")
            else:
                print("\n⚠️  Sync completed with warnings")
                for error in result.errors:
                    print(f"   • {error}")

        except Exception as e:
            if logger:
                logger.error(f"Sync failed: {e}", exc_info=True)
            print(f"\n✗ Sync failed: {e}", file=sys.stderr)
            sys.exit(1)

    def manifest(self, args: argparse.Namespace) -> None:
        """Show environment manifest (pyproject.toml configuration)."""
        env = self._get_env(args)

        # Handle --ide flag: open in editor and exit
        if hasattr(args, 'ide') and args.ide:
            import os
            import subprocess
            editor = args.ide if args.ide != "auto" else os.environ.get("EDITOR", "code")
            subprocess.run([editor, str(env.pyproject.path)])
            return

        import tomlkit
        import yaml

        # Load raw TOML config
        config = env.pyproject.load()

        # Handle section filtering if requested
        if hasattr(args, 'section') and args.section:
            # Navigate to requested section using dot notation
            keys = args.section.split('.')
            current = config
            try:
                for key in keys:
                    current = current[key]
                config = {args.section: current}
            except (KeyError, TypeError):
                print(f"✗ Section not found: {args.section}")
                print("\nAvailable sections:")
                print("  • project")
                print("  • tool.comfygit")
                print("  • tool.comfygit.nodes")
                print("  • tool.comfygit.workflows")
                print("  • tool.comfygit.models")
                print("  • tool.uv")
                print("  • dependency-groups")
                sys.exit(1)

        # Output format
        if hasattr(args, 'pretty') and args.pretty:
            # Convert tomlkit objects to plain Python types recursively
            def to_plain(obj):
                """Recursively convert tomlkit objects to plain Python types."""
                if isinstance(obj, dict):
                    return {k: to_plain(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [to_plain(item) for item in obj]
                elif hasattr(obj, 'unwrap'):  # tomlkit items have unwrap()
                    return to_plain(obj.unwrap())
                else:
                    return obj

            plain_dict = to_plain(config)
            print(yaml.dump(plain_dict, default_flow_style=False, sort_keys=False))
        else:
            # Default: raw TOML (exact file representation)
            print(tomlkit.dumps(config))

    @with_env_logging("status")
    def status(self, args: argparse.Namespace) -> None:
        """Show environment status using semantic methods."""
        env = self._get_env(args)

        status = env.status()

        # Always show git state - never leave it blank
        if status.git.current_branch:
            branch_info = f" (on {status.git.current_branch})"
        else:
            branch_info = " (detached HEAD)"

        # Clean state - everything is good (but check for detached HEAD)
        if status.is_synced and not status.git.has_changes and status.workflow.sync_status.total_count == 0:
            # Determine status indicator
            if status.git.current_branch is None:
                status_indicator = "⚠️"  # Warning for detached HEAD even when clean
            else:
                status_indicator = "✓"   # All good

            print(f"Environment: {env.name}{branch_info} {status_indicator}")

            # Show detached HEAD warning even in clean state
            if status.git.current_branch is None:
                print("⚠️  You are in detached HEAD state")
                print("   Any commits you make will not be saved to a branch!")
                print("   Create a branch: cg checkout -b <branch-name>")
                print()  # Extra spacing before clean state messages

            print("\n✓ No workflows")
            print("✓ No uncommitted changes")

            # Show legacy manager notice even in clean state
            self._show_legacy_manager_notice(env)
            return

        # Show environment name with branch
        print(f"Environment: {env.name}{branch_info}")

        # Detached HEAD warning (shown prominently at top)
        if status.git.current_branch is None:
            print("⚠️  You are in detached HEAD state")
            print("   Any commits you make will not be saved to a branch!")
            print("   Create a branch: cg checkout -b <branch-name>")
            print()  # Extra spacing

        # Workflows section - consolidated with issues
        if status.workflow.sync_status.total_count > 0 or status.workflow.sync_status.has_changes:
            print("\n📋 Workflows:")

            # Group workflows by state and show with issues inline
            all_workflows = {}

            # Build workflow map with their analysis
            for wf_analysis in status.workflow.analyzed_workflows:
                all_workflows[wf_analysis.name] = {
                    'state': wf_analysis.sync_state,
                    'has_issues': wf_analysis.has_issues,
                    'analysis': wf_analysis
                }

            # Show workflows with inline issue details
            verbose = args.verbose
            for name in status.workflow.sync_status.synced:
                if name in all_workflows:
                    wf = all_workflows[name]['analysis']
                    # Check if workflow has missing models (from direct repo query, not cache)
                    missing_for_wf = [m for m in status.missing_models if name in m.workflow_names]
                    # Show warning if has issues OR path sync needed OR missing models
                    if wf.has_issues or wf.has_path_sync_issues:
                        print(f"  ⚠️  {name} (synced)")
                        self._print_workflow_issues(wf, verbose)
                    elif missing_for_wf:
                        print(f"  ⚠️  {name} (synced, {len(missing_for_wf)} missing models)")
                    else:
                        print(f"  ✓ {name}")

            for name in status.workflow.sync_status.new:
                if name in all_workflows:
                    wf = all_workflows[name]['analysis']
                    # Check if workflow has missing models (from direct repo query, not cache)
                    missing_for_wf = [m for m in status.missing_models if name in m.workflow_names]
                    # Show warning if has issues OR path sync needed OR missing models
                    if wf.has_issues or wf.has_path_sync_issues:
                        print(f"  ⚠️  {name} (new)")
                        self._print_workflow_issues(wf, verbose)
                    elif missing_for_wf:
                        print(f"  ⚠️  {name} (new, {len(missing_for_wf)} missing models)")
                    else:
                        print(f"  🆕 {name} (new, ready to commit)")

            for name in status.workflow.sync_status.modified:
                if name in all_workflows:
                    wf = all_workflows[name]['analysis']
                    # Check if workflow has missing models
                    missing_for_wf = [m for m in status.missing_models if name in m.workflow_names]

                    # Show warning if has issues OR path sync needed
                    if wf.has_issues or wf.has_path_sync_issues:
                        print(f"  ⚠️  {name} (modified)")
                        self._print_workflow_issues(wf, verbose)
                    elif missing_for_wf:
                        print(f"  ⬇️  {name} (modified, missing models)")
                        print(f"      {len(missing_for_wf)} model(s) need downloading")
                    else:
                        print(f"  📝 {name} (modified)")

            for name in status.workflow.sync_status.deleted:
                print(f"  🗑️  {name} (deleted)")

        # Environment drift (manual edits)
        if not status.comparison.is_synced:
            print("\n⚠️  Environment needs repair:")

            if status.comparison.missing_nodes:
                print(f"  • {len(status.comparison.missing_nodes)} nodes in pyproject.toml not installed")

            if status.comparison.extra_nodes:
                print(f"  • {len(status.comparison.extra_nodes)} untracked nodes on filesystem:")
                limit = None if args.verbose else 5
                nodes_to_show = status.comparison.extra_nodes if limit is None else status.comparison.extra_nodes[:limit]
                for node_name in nodes_to_show:
                    print(f"    - {node_name}")
                if limit and len(status.comparison.extra_nodes) > limit:
                    print(f"    ... and {len(status.comparison.extra_nodes) - limit} more")

            if status.comparison.version_mismatches:
                print(f"  • {len(status.comparison.version_mismatches)} version mismatches")

            if not status.comparison.packages_in_sync:
                print("  • Python packages out of sync")

        # Disabled nodes (informational, not a warning)
        if status.comparison.disabled_nodes:
            print("\n📴 Disabled nodes:")
            for node_name in status.comparison.disabled_nodes:
                print(f"  • {node_name}")

        # Git changes
        if status.git.has_changes:
            has_specific_changes = (
                status.git.nodes_added or
                status.git.nodes_removed or
                status.git.workflow_changes
            )

            if has_specific_changes:
                print("\n📦 Uncommitted changes:")
                limit = None if args.verbose else 3

                if status.git.nodes_added:
                    nodes_to_show = status.git.nodes_added if limit is None else status.git.nodes_added[:limit]
                    for node in nodes_to_show:
                        name = node['name'] if isinstance(node, dict) else node
                        print(f"  • Added node: {name}")
                    if limit and len(status.git.nodes_added) > limit:
                        print(f"  • ... and {len(status.git.nodes_added) - limit} more nodes")

                if status.git.nodes_removed:
                    nodes_to_show = status.git.nodes_removed if limit is None else status.git.nodes_removed[:limit]
                    for node in nodes_to_show:
                        name = node['name'] if isinstance(node, dict) else node
                        print(f"  • Removed node: {name}")
                    if limit and len(status.git.nodes_removed) > limit:
                        print(f"  • ... and {len(status.git.nodes_removed) - limit} more nodes")

                if status.git.workflow_changes:
                    count = len(status.git.workflow_changes)
                    print(f"  • {count} workflow(s) changed")

                # Show other changes if present
                if status.git.has_other_changes:
                    print("  • Other files modified in .cec/")
            else:
                # Generic message for other changes (e.g., model resolutions)
                print("\n📦 Uncommitted changes:")
                if status.git.has_other_changes:
                    print("  • Other files modified in .cec/")
                else:
                    print("  • Configuration updated")

        # Suggested actions - smart and contextual
        self._show_smart_suggestions(status)

        # Show legacy manager notice if applicable
        self._show_legacy_manager_notice(env)

    # Removed: _has_uninstalled_packages - this logic is now in core's WorkflowAnalysisStatus

    def _print_workflow_issues(self, wf_analysis: WorkflowAnalysisStatus, verbose: bool = False) -> None:
        """Print compact workflow issues summary using model properties only."""
        # Build compact summary using WorkflowAnalysisStatus properties (no pyproject access!)
        parts = []
        resolution = wf_analysis.resolution
        nodes_version_gated = getattr(resolution, "nodes_version_gated", [])
        nodes_uninstallable = getattr(resolution, "nodes_uninstallable", [])
        nodes_unresolved = getattr(resolution, "nodes_unresolved", [])
        models_unresolved = getattr(resolution, "models_unresolved", [])
        models_ambiguous = getattr(resolution, "models_ambiguous", [])
        models_resolved = getattr(resolution, "models_resolved", [])
        node_guidance = getattr(resolution, "node_guidance", {})

        # Path sync warnings (FIRST - most actionable fix)
        if wf_analysis.models_needing_path_sync_count > 0:
            parts.append(f"{wf_analysis.models_needing_path_sync_count} model paths need syncing")

        # Category mismatch (blocking - model in wrong directory for loader)
        if wf_analysis.models_with_category_mismatch_count > 0:
            parts.append(f"{wf_analysis.models_with_category_mismatch_count} models in wrong directory")

        # Use the uninstalled_count property (populated by core)
        if wf_analysis.uninstalled_count > 0:
            parts.append(f"{wf_analysis.uninstalled_count} packages needed for installation")

        # Resolution issues
        if nodes_version_gated:
            parts.append(f"{len(nodes_version_gated)} nodes require newer ComfyUI")
        if nodes_uninstallable:
            parts.append(f"{len(nodes_uninstallable)} nodes matched uninstallable mappings")
        if nodes_unresolved:
            parts.append(f"{len(nodes_unresolved)} nodes couldn't be resolved")
        if models_unresolved:
            parts.append(f"{len(models_unresolved)} models not found")
        if models_ambiguous:
            parts.append(f"{len(models_ambiguous)} ambiguous models")

        # Show download intents as pending work (not blocking but needs attention)
        download_intents = [m for m in models_resolved if m.match_type == "download_intent"]
        if download_intents:
            parts.append(f"{len(download_intents)} models queued for download")

        # Print compact issue line
        if parts:
            print(f"      {', '.join(parts)}")

        # Version-gated/uninstallable node guidance
        if node_guidance:
            items = list(node_guidance.items())
            limit = len(items) if verbose else 3
            for node_type, message in items[:limit]:
                print(f"        ↳ {node_type}: {message}")
            if not verbose and len(items) > limit:
                print(f"        ↳ ... and {len(items) - limit} more guidance item(s)")

        # Detailed category mismatch info (always show brief, verbose shows full details)
        if wf_analysis.has_category_mismatch_issues:
            for model in models_resolved:
                if model.has_category_mismatch:
                    expected = model.expected_categories[0] if model.expected_categories else "unknown"
                    if verbose:
                        print(f"        ↳ {model.name}")
                        print(f"          Node: {model.reference.node_type} expects {expected}/")
                        print(f"          Actual: {model.actual_category}/")
                        print(f"          Fix: Move file to models/{expected}/ or re-download")
                    else:
                        print(f"        ↳ {model.name}: in {model.actual_category}/, needs {expected}/")

    def _show_smart_suggestions(self, status: EnvironmentStatus) -> None:
        """Show contextual suggestions based on current state."""
        suggestions = []

        # Differentiate workflow-related nodes from orphan nodes
        uninstalled_workflow_nodes = set()
        for wf in status.workflow.analyzed_workflows:
            uninstalled_workflow_nodes.update(wf.uninstalled_nodes)

        orphan_missing_nodes = set(status.comparison.missing_nodes) - uninstalled_workflow_nodes
        has_orphan_nodes = bool(orphan_missing_nodes or status.comparison.extra_nodes)

        # Missing models + environment drift: check if repair needed first
        if status.missing_models and has_orphan_nodes:
            suggestions.append("Install missing nodes: cg repair")

            # Group workflows with missing models
            workflows_with_missing = {}
            for missing_info in status.missing_models:
                for wf_name in missing_info.workflow_names:
                    if wf_name not in workflows_with_missing:
                        workflows_with_missing[wf_name] = []
                    workflows_with_missing[wf_name].append(missing_info)

            if len(workflows_with_missing) == 1:
                wf_name = list(workflows_with_missing.keys())[0]
                suggestions.append(f"Then resolve workflow: cg workflow resolve \"{wf_name}\"")
            else:
                suggestions.append("Then resolve workflow (pick one):")
                for wf_name in list(workflows_with_missing.keys())[:2]:
                    suggestions.append(f"  cg workflow resolve \"{wf_name}\"")

            print("\n💡 Next:")
            for s in suggestions:
                print(f"  {s}")
            return

        # Missing models only (no orphan nodes) - workflow resolve handles everything
        if status.missing_models:
            workflows_with_missing = {}
            for missing_info in status.missing_models:
                for wf_name in missing_info.workflow_names:
                    if wf_name not in workflows_with_missing:
                        workflows_with_missing[wf_name] = []
                    workflows_with_missing[wf_name].append(missing_info)

            if len(workflows_with_missing) == 1:
                wf_name = list(workflows_with_missing.keys())[0]
                suggestions.append(f"Resolve workflow: cg workflow resolve \"{wf_name}\"")
            else:
                suggestions.append("Resolve workflows with missing models (pick one):")
                for wf_name in list(workflows_with_missing.keys())[:3]:
                    suggestions.append(f"  cg workflow resolve \"{wf_name}\"")
                if len(workflows_with_missing) > 3:
                    suggestions.append(f"  ... and {len(workflows_with_missing) - 3} more")

            print("\n💡 Next:")
            for s in suggestions:
                print(f"  {s}")
            return

        # Environment drift only (no workflow issues)
        if not status.comparison.is_synced:
            # If only extra nodes, suggest tracking them as dev nodes
            if status.comparison.extra_nodes and not status.comparison.missing_nodes and not status.comparison.version_mismatches and status.comparison.packages_in_sync:
                if len(status.comparison.extra_nodes) == 1:
                    node_name = status.comparison.extra_nodes[0]
                    suggestions.append(f"Track as dev node: cg node add {node_name} --dev")
                else:
                    suggestions.append("Track as dev nodes:")
                    for node_name in status.comparison.extra_nodes[:3]:
                        suggestions.append(f"  cg node add {node_name} --dev")
                    if len(status.comparison.extra_nodes) > 3:
                        suggestions.append(f"  ... and {len(status.comparison.extra_nodes) - 3} more")
                suggestions.append("Or remove untracked: cg repair")
            else:
                suggestions.append("Run: cg repair")
            print("\n💡 Next:")
            for s in suggestions:
                print(f"  {s}")
            return

        # Category mismatch (blocking - model in wrong directory for loader)
        workflows_with_category_mismatch = [
            w for w in status.workflow.analyzed_workflows
            if w.has_category_mismatch_issues
        ]

        if workflows_with_category_mismatch:
            suggestions.append("Models in wrong directory (move files manually):")
            for wf in workflows_with_category_mismatch[:2]:
                for m in wf.resolution.models_resolved:
                    if m.has_category_mismatch:
                        expected = m.expected_categories[0] if m.expected_categories else "unknown"
                        suggestions.append(f"  {m.actual_category}/{m.name} → {expected}/")

            print("\n💡 Next:")
            for s in suggestions:
                print(f"  {s}")
            return

        # Path sync warnings (prioritize - quick fix!)
        workflows_needing_sync = [
            w for w in status.workflow.analyzed_workflows
            if w.has_path_sync_issues
        ]

        if workflows_needing_sync:
            workflow_names = [w.name for w in workflows_needing_sync]
            if len(workflow_names) == 1:
                suggestions.append(f"Sync model paths: cg workflow resolve \"{workflow_names[0]}\"")
            else:
                suggestions.append(f"Sync model paths in {len(workflow_names)} workflows: cg workflow resolve \"<name>\"")

        # Check for workflows with download intents
        workflows_with_downloads = []
        for wf in status.workflow.analyzed_workflows:
            download_intents = [m for m in wf.resolution.models_resolved if m.match_type == "download_intent"]
            if download_intents:
                workflows_with_downloads.append(wf.name)

        # Workflows with issues (unresolved/ambiguous)
        workflows_with_issues = [w.name for w in status.workflow.workflows_with_issues]
        if workflows_with_issues:
            if len(workflows_with_issues) == 1:
                suggestions.append(f"Fix issues: cg workflow resolve \"{workflows_with_issues[0]}\"")
            else:
                suggestions.append("Fix workflows (pick one):")
                for wf_name in workflows_with_issues[:3]:
                    suggestions.append(f"  cg workflow resolve \"{wf_name}\"")
                if len(workflows_with_issues) > 3:
                    suggestions.append(f"  ... and {len(workflows_with_issues) - 3} more")

            # Only suggest committing if there are uncommitted changes
            if status.git.has_changes:
                suggestions.append("Or commit anyway: cg commit -m \"...\" --allow-issues")

        # Workflows with queued downloads (no other issues)
        elif workflows_with_downloads:
            if len(workflows_with_downloads) == 1:
                suggestions.append(f"Complete downloads: cg workflow resolve \"{workflows_with_downloads[0]}\"")
            else:
                suggestions.append("Complete downloads (pick one):")
                for wf_name in workflows_with_downloads[:3]:
                    suggestions.append(f"  cg workflow resolve \"{wf_name}\"")

        # Ready to commit (workflow changes OR git changes)
        elif status.workflow.sync_status.has_changes and status.workflow.is_commit_safe:
            suggestions.append("Commit workflows: cg commit -m \"<message>\"")
        elif status.git.has_changes:
            # Uncommitted pyproject changes without workflow issues
            suggestions.append("Commit changes: cg commit -m \"<message>\"")

        # Show suggestions if any
        if suggestions:
            print("\n💡 Next:")
            for s in suggestions:
                print(f"  {s}")

    def _show_git_changes(self, status: EnvironmentStatus) -> None:
        """Helper method to show git changes in a structured way."""
        # Show node changes
        if status.git.nodes_added or status.git.nodes_removed:
            print("\n  Custom Nodes:")
            for node in status.git.nodes_added:
                if isinstance(node, dict):
                    name = node['name']
                    suffix = ' (development)' if node.get('is_development') else ''
                    print(f"    + {name}{suffix}")
                else:
                    # Backwards compatibility for string format
                    print(f"    + {node}")
            for node in status.git.nodes_removed:
                if isinstance(node, dict):
                    name = node['name']
                    suffix = ' (development)' if node.get('is_development') else ''
                    print(f"    - {name}{suffix}")
                else:
                    # Backwards compatibility for string format
                    print(f"    - {node}")

        # Show dependency changes
        if status.git.dependencies_added or status.git.dependencies_removed or status.git.dependencies_updated:
            print("\n  Python Packages:")
            for dep in status.git.dependencies_added:
                version = dep.get('version', 'any')
                source = dep.get('source', '')
                if source:
                    print(f"    + {dep['name']} ({version}) [{source}]")
                else:
                    print(f"    + {dep['name']} ({version})")
            for dep in status.git.dependencies_removed:
                version = dep.get('version', 'any')
                print(f"    - {dep['name']} ({version})")
            for dep in status.git.dependencies_updated:
                old = dep.get('old_version', 'any')
                new = dep.get('new_version', 'any')
                print(f"    ~ {dep['name']}: {old} → {new}")

        # Show constraint changes
        if status.git.constraints_added or status.git.constraints_removed:
            print("\n  Constraint Dependencies:")
            for constraint in status.git.constraints_added:
                print(f"    + {constraint}")
            for constraint in status.git.constraints_removed:
                print(f"    - {constraint}")

        # Show workflow changes (tracking and content)
        workflow_changes_shown = False

        # Workflow tracking no longer needed - all workflows are automatically managed

        # Show workflow file changes
        if status.git.workflow_changes:
            if not workflow_changes_shown:
                print("\n  Workflows:")
                workflow_changes_shown = True
            for workflow_name, git_status in status.git.workflow_changes.items():
                if git_status == "modified":
                    print(f"    ~ {workflow_name}.json")
                elif git_status == "added":
                    print(f"    + {workflow_name}.json")
                elif git_status == "deleted":
                    print(f"    - {workflow_name}.json")

    @with_env_logging("log")
    def log(self, args: argparse.Namespace, logger=None) -> None:
        """Show commit history for this environment."""
        env = self._get_env(args)

        try:
            limit = args.limit if hasattr(args, 'limit') else 20
            history = env.get_commit_history(limit=limit)

            if not history:
                print("No commits yet")
                print("\nTip: Run 'cg commit' to create your first commit")
                return

            print(f"Commit history for environment '{env.name}':\n")

            if not args.verbose:
                # Compact: hash + refs + message + relative date
                for commit in history:  # Already newest first
                    refs_display = f" ({commit['refs']})" if commit['refs'] else ""
                    print(f"{commit['hash']}{refs_display}  {commit['message']} ({commit['date_relative']})")
                print()
            else:
                # Verbose: multi-line with full info
                for commit in history:
                    refs_display = f" ({commit['refs']})" if commit['refs'] else ""
                    print(f"Commit:  {commit['hash']}{refs_display}")
                    print(f"Date:    {commit['date'][:19]}")
                    print(f"Message: {commit['message']}")
                    print()

            # Show detached HEAD status if applicable
            current_branch = env.get_current_branch()
            if current_branch is None:
                print()
                print("⚠️  You are currently in detached HEAD state")
                print("   Commits will not be saved to any branch!")
                print("   Create a branch: cg checkout -b <branch-name>")
                print()

            print("Use 'cg checkout <hash>' to view a specific commit")
            print("Use 'cg revert <hash>' to undo changes from a commit (safe)")
            print("Use 'cg checkout -b <branch> <hash>' to create branch from commit")

        except Exception as e:
            if logger:
                logger.error(f"Failed to read commit history for environment '{env.name}': {e}", exc_info=True)
            print(f"✗ Could not read commit history: {e}", file=sys.stderr)
            sys.exit(1)

    # === Node management ===

    @with_env_logging("node add")
    def node_add(self, args: argparse.Namespace, logger=None) -> None:
        """Add custom node(s) - directly modifies pyproject.toml."""
        env = self._get_env(args)
        extras = getattr(args, 'extra', None) or []
        all_extras = getattr(args, 'all_extras', False)

        # Batch mode: multiple nodes
        if len(args.node_names) > 1:
            print(f"📦 Adding {len(args.node_names)} nodes...")

            # Create callbacks for progress display
            def on_node_start(node_id, idx, total):
                print(f"  [{idx}/{total}] Installing {node_id}...", end=" ", flush=True)

            def on_node_complete(node_id, success, error):
                if success:
                    print("✓")
                else:
                    print(f"✗ ({error})")

            from comfygit_core.models.workflow import NodeInstallCallbacks
            callbacks = NodeInstallCallbacks(
                on_node_start=on_node_start,
                on_node_complete=on_node_complete
            )

            # Install nodes with progress feedback
            installed_count, failed_nodes = env.install_nodes_with_progress(
                args.node_names,
                callbacks=callbacks,
                extras=extras,
                all_extras=all_extras,
            )

            if installed_count > 0:
                print(f"\n✅ Installed {installed_count}/{len(args.node_names)} nodes")

            if failed_nodes:
                print(f"\n⚠️  Failed to install {len(failed_nodes)} nodes:")
                for node_id, error in failed_nodes:
                    print(f"  • {node_id}: {error}")

            print(f"\nRun 'cg -e {env.name} status' to review changes")
            return

        # Single node mode (original behavior)
        node_name = args.node_names[0]

        if args.dev:
            print(f"📦 Adding development node: {node_name}")
        else:
            print(f"📦 Adding node: {node_name}")

        # Create confirmation strategy for dev node replacement
        from comfygit_core.strategies.confirmation import InteractiveConfirmStrategy
        confirmation_strategy = InteractiveConfirmStrategy()

        # Directly add the node
        try:
            node_info = env.add_node(
                node_name,
                is_development=args.dev,
                no_test=args.no_test,
                force=args.force,
                confirmation_strategy=confirmation_strategy,
                strict=getattr(args, "strict", False),
                extras=extras,
                all_extras=all_extras,
            )
        except CDRegistryDataError as e:
            # Registry data unavailable
            formatted = NodeErrorFormatter.format_registry_error(e)
            if logger:
                logger.error(f"Registry data unavailable for node add: {e}", exc_info=True)
            print("✗ Cannot add node - registry data unavailable", file=sys.stderr)
            print(formatted, file=sys.stderr)
            sys.exit(1)
        except CDDependencyConflictError as e:
            # Dependency conflict with enhanced formatting
            formatted = NodeErrorFormatter.format_dependency_conflict_error(e, verbose=args.verbose)
            if logger:
                logger.error(f"Dependency conflict for '{node_name}': {e}", exc_info=True)
            print(formatted, file=sys.stderr)
            sys.exit(1)
        except CDNodeConflictError as e:
            # Use formatter to render error with CLI commands
            formatted = NodeErrorFormatter.format_conflict_error(e)
            if logger:
                logger.error(f"Node conflict for '{node_name}': {e}", exc_info=True)
            print(f"✗ Cannot add node '{node_name}'", file=sys.stderr)
            print(formatted, file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            if logger:
                logger.error(f"Node add failed for '{node_name}': {e}", exc_info=True)
            print(f"✗ Failed to add node '{node_name}'", file=sys.stderr)
            print(f"   {e}", file=sys.stderr)
            sys.exit(1)

        if args.dev:
            print(f"✓ Development node '{node_info.name}' added and tracked")
        else:
            print(f"✓ Node '{node_info.name}' added to pyproject.toml")

        print(f"\nRun 'cg -e {env.name} status' to review changes")

    @with_env_logging("node remove")
    def node_remove(self, args: argparse.Namespace, logger=None) -> None:
        """Remove custom node(s) - handles filesystem immediately."""
        env = self._get_env(args)

        # Batch mode: multiple nodes
        if len(args.node_names) > 1:
            print(f"🗑 Removing {len(args.node_names)} nodes...")

            # Create callbacks for progress display
            def on_node_start(node_id, idx, total):
                print(f"  [{idx}/{total}] Removing {node_id}...", end=" ", flush=True)

            def on_node_complete(node_id, success, error):
                if success:
                    print("✓")
                else:
                    print(f"✗ ({error})")

            from comfygit_core.models.workflow import NodeInstallCallbacks
            callbacks = NodeInstallCallbacks(
                on_node_start=on_node_start,
                on_node_complete=on_node_complete
            )

            # Remove nodes with progress feedback
            removed_count, failed_nodes = env.remove_nodes_with_progress(
                args.node_names,
                callbacks=callbacks
            )

            if removed_count > 0:
                print(f"\n✅ Removed {removed_count}/{len(args.node_names)} nodes")

            if failed_nodes:
                print(f"\n⚠️  Failed to remove {len(failed_nodes)} nodes:")
                for node_id, error in failed_nodes:
                    print(f"  • {node_id}: {error}")

            print(f"\nRun 'cg -e {env.name} status' to review changes")
            return

        # Single node mode (original behavior)
        node_name = args.node_names[0]
        untrack_only = getattr(args, 'untrack', False)

        if untrack_only:
            print(f"🔓 Untracking node: {node_name}")
        else:
            print(f"🗑 Removing node: {node_name}")

        # Remove the node (handles filesystem imperatively)
        try:
            result = env.remove_node(node_name, untrack_only=untrack_only)
        except Exception as e:
            if logger:
                logger.error(f"Node remove failed for '{node_name}': {e}", exc_info=True)
            print(f"✗ Failed to remove node '{node_name}'", file=sys.stderr)
            print(f"   {e}", file=sys.stderr)
            sys.exit(1)

        # Render result based on node type and action
        if result.filesystem_action == "none":
            # Untrack mode - no filesystem changes
            print(f"✓ Node '{result.name}' removed from tracking")
            print("   (filesystem unchanged)")
        elif result.source == "development":
            if result.filesystem_action == "disabled":
                print(f"ℹ️  Development node '{result.name}' removed from tracking")
                print(f"   Files preserved at: custom_nodes/{result.name}.disabled/")
            else:
                print(f"✓ Development node '{result.name}' removed from tracking")
        else:
            print(f"✓ Node '{result.name}' removed from environment")
            if result.filesystem_action == "deleted":
                print("   (cached globally, can reinstall)")

        print(f"\nRun 'cg -e {env.name} status' to review changes")

    @with_env_logging("node prune")
    def node_prune(self, args: argparse.Namespace, logger=None) -> None:
        """Remove unused custom nodes from environment."""
        env = self._get_env(args)

        # Get unused nodes
        exclude = args.exclude if hasattr(args, 'exclude') and args.exclude else None
        try:
            unused = env.get_unused_nodes(exclude=exclude)
        except Exception as e:
            if logger:
                logger.error(f"Failed to get unused nodes: {e}", exc_info=True)
            print(f"✗ Failed to get unused nodes: {e}", file=sys.stderr)
            sys.exit(1)

        if not unused:
            print("✓ No unused nodes found")
            return

        # Display table
        print(f"\nFound {len(unused)} unused node(s):\n")
        for node in unused:
            node_id = node.registry_id or node.name
            print(f"  • {node_id}")

        # Confirm unless --yes flag
        if not args.yes:
            try:
                confirm = input(f"\nRemove {len(unused)} node(s)? [y/N]: ")
                if confirm.lower() != 'y':
                    print("Cancelled")
                    return
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled")
                return

        # Remove with progress
        print(f"\n🗑 Pruning {len(unused)} unused nodes...")

        def on_node_start(node_id, idx, total):
            print(f"  [{idx}/{total}] Removing {node_id}...", end=" ", flush=True)

        def on_node_complete(node_id, success, error):
            if success:
                print("✓")
            else:
                print(f"✗ ({error})")

        from comfygit_core.models.workflow import NodeInstallCallbacks
        callbacks = NodeInstallCallbacks(
            on_node_start=on_node_start,
            on_node_complete=on_node_complete
        )

        try:
            success_count, failed = env.prune_unused_nodes(exclude=exclude, callbacks=callbacks)
        except Exception as e:
            if logger:
                logger.error(f"Prune failed: {e}", exc_info=True)
            print(f"\n✗ Prune failed: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"\n✓ Removed {success_count} node(s)")
        if failed:
            print(f"✗ Failed to remove {len(failed)} node(s):")
            for node_id, error in failed:
                print(f"  • {node_id}: {error}")
            sys.exit(1)

    @with_env_logging("node list")
    def node_list(self, args: argparse.Namespace) -> None:
        """List custom nodes in the environment."""
        env = self._get_env(args)

        nodes = env.list_nodes()

        if not nodes:
            print("No custom nodes installed")
            return

        print(f"Custom nodes in '{env.name}':")
        for node in nodes:
            # Format version display based on source type
            version_suffix = ""
            if node.version:
                if node.source == "git":
                    version_suffix = f" @ {node.version[:8]}"
                elif node.source == "registry":
                    version_suffix = f" v{node.version}"
                elif node.source == "development":
                    version_suffix = " (dev)"

            print(f"  • {node.registry_id or node.name} ({node.source}){version_suffix}")

    @with_env_logging("node update")
    def node_update(self, args: argparse.Namespace, logger=None) -> None:
        """Update a custom node."""
        from comfygit_core.strategies.confirmation import (
            AutoConfirmStrategy,
            InteractiveConfirmStrategy,
        )

        env = self._get_env(args)

        print(f"🔄 Updating node: {args.node_name}")

        # Choose confirmation strategy
        strategy = AutoConfirmStrategy() if args.yes else InteractiveConfirmStrategy()

        try:
            result = env.update_node(
                args.node_name,
                confirmation_strategy=strategy,
                no_test=args.no_test
            )

            if result.changed:
                print(f"✓ {result.message}")

                if result.source == 'development':
                    if result.requirements_added:
                        print("  Added dependencies:")
                        for dep in result.requirements_added:
                            print(f"    + {dep}")
                    if result.requirements_removed:
                        print("  Removed dependencies:")
                        for dep in result.requirements_removed:
                            print(f"    - {dep}")

                print("\nRun 'cg status' to review changes")
            else:
                print(f"ℹ️  {result.message}")

        except Exception as e:
            if logger:
                logger.error(f"Node update failed for '{args.node_name}': {e}", exc_info=True)
            print(f"✗ Failed to update node '{args.node_name}'", file=sys.stderr)
            print(f"   {e}", file=sys.stderr)
            sys.exit(1)

    # === Constraint management ===

    @with_env_logging("constraint add")
    def constraint_add(self, args: argparse.Namespace, logger=None) -> None:
        """Add constraint dependencies to [tool.uv]."""
        env = self._get_env(args)

        print(f"📦 Adding constraints: {' '.join(args.packages)}")

        # Add each constraint
        try:
            for package in args.packages:
                env.add_constraint(package)
        except Exception as e:
            if logger:
                logger.error(f"Constraint add failed: {e}", exc_info=True)
            print("✗ Failed to add constraints", file=sys.stderr)
            print(f"   {e}", file=sys.stderr)
            sys.exit(1)

        print(f"✓ Added {len(args.packages)} constraint(s) to pyproject.toml")
        print(f"\nRun 'cg -e {env.name} constraint list' to view all constraints")

    @with_env_logging("constraint list")
    def constraint_list(self, args: argparse.Namespace) -> None:
        """List constraint dependencies from [tool.uv]."""
        env = self._get_env(args)

        # Get constraints from pyproject.toml
        constraints = env.list_constraints()

        if not constraints:
            print("No constraint dependencies configured")
            return

        print(f"Constraint dependencies in '{env.name}':")
        for constraint in constraints:
            print(f"  • {constraint}")

    @with_env_logging("constraint remove")
    def constraint_remove(self, args: argparse.Namespace, logger=None) -> None:
        """Remove constraint dependencies from [tool.uv]."""
        env = self._get_env(args)

        print(f"🗑 Removing constraints: {' '.join(args.packages)}")

        # Remove each constraint
        removed_count = 0
        try:
            for package in args.packages:
                if env.remove_constraint(package):
                    removed_count += 1
                else:
                    print(f"   Warning: constraint '{package}' not found")
        except Exception as e:
            if logger:
                logger.error(f"Constraint remove failed: {e}", exc_info=True)
            print("✗ Failed to remove constraints", file=sys.stderr)
            print(f"   {e}", file=sys.stderr)
            sys.exit(1)

        if removed_count > 0:
            print(f"✓ Removed {removed_count} constraint(s) from pyproject.toml")
        else:
            print("No constraints were removed")

        print(f"\nRun 'cg -e {env.name} constraint list' to view remaining constraints")

    # === Python dependency management ===

    @with_env_logging("py add")
    def py_add(self, args: argparse.Namespace, logger=None) -> None:
        """Add Python dependencies to the environment."""
        env = self._get_env(args)

        # Validate arguments: must provide either packages or requirements file
        if not args.packages and not args.requirements:
            print("✗ Error: Must specify packages or use -r/--requirements", file=sys.stderr)
            print("Examples:", file=sys.stderr)
            print("  cg py add requests pillow", file=sys.stderr)
            print("  cg py add -r requirements.txt", file=sys.stderr)
            sys.exit(1)

        if args.packages and args.requirements:
            print("✗ Error: Cannot specify both packages and -r/--requirements", file=sys.stderr)
            sys.exit(1)

        if getattr(args, 'optional', None):
            if getattr(args, 'group', None) or getattr(args, 'dev', False):
                print("✗ Error: --optional cannot be combined with --group or --dev", file=sys.stderr)
                sys.exit(1)
            if args.requirements:
                print("✗ Error: --optional requires explicit package specifications (not -r/--requirements)", file=sys.stderr)
                sys.exit(1)

        # Resolve requirements file path to absolute path (UV runs in .cec directory)
        requirements_file = None
        if args.requirements:
            requirements_file = args.requirements.resolve()
            if not requirements_file.exists():
                print(f"✗ Error: Requirements file not found: {args.requirements}", file=sys.stderr)
                sys.exit(1)

        # Display what we're doing
        upgrade_text = " (with upgrade)" if args.upgrade else ""
        if requirements_file:
            print(f"📦 Adding packages from {args.requirements}{upgrade_text}...")
        else:
            print(f"📦 Adding {len(args.packages)} package(s){upgrade_text}...")

        try:
            result = env.add_dependencies(
                packages=args.packages or None,
                requirements_file=requirements_file,
                upgrade=args.upgrade,
                group=getattr(args, 'group', None),
                dev=getattr(args, 'dev', False),
                optional=getattr(args, 'optional', None),
                editable=getattr(args, 'editable', False),
                bounds=getattr(args, 'bounds', None),
                no_build_isolation=getattr(args, 'no_build_isolation', False)
            )
        except UVCommandError as e:
            if logger:
                logger.error(f"Failed to add dependencies: {e}", exc_info=True)
                if e.stderr:
                    logger.error(f"UV stderr:\n{e.stderr}")
            print("✗ Failed to add packages", file=sys.stderr)
            if e.stderr:
                print(f"\n{e.stderr}", file=sys.stderr)
            else:
                print(f"   {e}", file=sys.stderr)
            sys.exit(1)

        # Display any package substitutions that were applied
        substitutions = result.get("substitutions", {})
        if substitutions:
            print()
            for original, substituted in substitutions.items():
                print(f"  ℹ️  {original} → {substituted} (per package_config.toml)")

        if requirements_file:
            print(f"\n✓ Added packages from {args.requirements}")
        else:
            print(f"\n✓ Added {len(args.packages)} package(s) to dependencies")
        print(f"\nRun 'cg -e {env.name} status' to review changes")

    @with_env_logging("py remove")
    def py_remove(self, args: argparse.Namespace, logger=None) -> None:
        """Remove Python dependencies from the environment."""
        env = self._get_env(args)

        # Handle --group flag (remove from dependency group)
        if hasattr(args, 'group') and args.group:
            group_name = args.group
            print(f"🗑 Removing {len(args.packages)} package(s) from group '{group_name}'...")

            try:
                result = env.pyproject.dependencies.remove_from_group(group_name, args.packages)
            except ValueError as e:
                print(f"✗ {e}", file=sys.stderr)
                sys.exit(1)

            # Show results
            if not result['removed']:
                if len(result['skipped']) == 1:
                    print(f"\nℹ️  Package '{result['skipped'][0]}' is not in group '{group_name}'")
                else:
                    print(f"\nℹ️  None of the specified packages are in group '{group_name}':")
                    for pkg in result['skipped']:
                        print(f"  • {pkg}")
                return

            print(f"\n✓ Removed {len(result['removed'])} package(s) from group '{group_name}'")

            if result['skipped']:
                print(f"\nℹ️  Skipped {len(result['skipped'])} package(s) not in group:")
                for pkg in result['skipped']:
                    print(f"  • {pkg}")

            print(f"\nRun 'cg -e {env.name} py list --all' to view remaining groups")
            return

        # Default behavior: remove from main dependencies
        print(f"🗑 Removing {len(args.packages)} package(s)...")

        try:
            result = env.remove_dependencies(args.packages)
        except UVCommandError as e:
            if logger:
                logger.error(f"Failed to remove dependencies: {e}", exc_info=True)
                if e.stderr:
                    logger.error(f"UV stderr:\n{e.stderr}")
            print("✗ Failed to remove packages", file=sys.stderr)
            if e.stderr:
                print(f"\n{e.stderr}", file=sys.stderr)
            else:
                print(f"   {e}", file=sys.stderr)
            sys.exit(1)

        # If nothing was removed, show appropriate message
        if not result['removed']:
            if len(result['skipped']) == 1:
                print(f"\nℹ️  Package '{result['skipped'][0]}' is not in dependencies (already removed or never added)")
            else:
                print("\nℹ️  None of the specified packages are in dependencies:")
                for pkg in result['skipped']:
                    print(f"  • {pkg}")
            return

        # Show successful removals
        print(f"\n✓ Removed {len(result['removed'])} package(s) from dependencies")

        # Show skipped packages if any
        if result['skipped']:
            print(f"\nℹ️  Skipped {len(result['skipped'])} package(s) not in dependencies:")
            for pkg in result['skipped']:
                print(f"  • {pkg}")

        print(f"\nRun 'cg -e {env.name} status' to review changes")

    @with_env_logging("py remove-group")
    def py_remove_group(self, args: argparse.Namespace, logger=None) -> None:
        """Remove an entire dependency group."""
        env = self._get_env(args)
        group_name = args.group

        print(f"🗑 Removing dependency group: {group_name}")

        try:
            env.pyproject.dependencies.remove_group(group_name)
        except ValueError as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(1)

        print(f"\n✓ Removed dependency group '{group_name}'")
        print(f"\nRun 'cg -e {env.name} py list --all' to view remaining groups")

    @with_env_logging("py uv")
    def py_uv(self, args: argparse.Namespace, logger=None) -> None:
        """Direct UV command passthrough for advanced users."""
        env = self._get_env(args)

        if not args.uv_args:
            # Show helpful usage message
            print("Usage: cg py uv <uv-command> [uv-args...]")
            print("Example: cg py uv add --group optional-cuda sageattention")
            print("\nThis is direct UV access. See 'uv --help' for options.")
            sys.exit(1)

        # Build UV command with environment context
        cmd = [env.uv_manager.uv._binary] + args.uv_args

        # Execute with environment context (cwd and env vars)
        result = subprocess.run(
            cmd,
            cwd=env.cec_path,
            env={
                **os.environ,
                "UV_PROJECT_ENVIRONMENT": str(env.venv_path),
                "UV_CACHE_DIR": str(env.workspace_paths.cache / "uv_cache"),
            }
        )
        sys.exit(result.returncode)

    @with_env_logging("py list")
    def py_list(self, args: argparse.Namespace) -> None:
        """List Python dependencies."""
        env = self._get_env(args)

        all_deps = env.list_dependencies(all=args.all)

        # Check if there are any dependencies at all
        total_count = sum(len(deps) for deps in all_deps.values())
        if total_count == 0:
            print("No project dependencies or dependency groups")
            return

        # Display dependencies grouped by section
        first_group = True
        for group_name, group_deps in all_deps.items():
            if not group_deps:
                continue

            if not first_group:
                print()  # Blank line between groups
            first_group = False

            # Format the header
            if group_name == "dependencies":
                print(f"Dependencies ({len(group_deps)}):")
                for dep in group_deps:
                    print(f"  • {dep}")
            else:
                print(f"{group_name} ({len(group_deps)}):")
                for dep in group_deps:
                    print(f"  • {dep}")

        # Show tip if not showing all groups
        if not args.all and len(all_deps) == 1:
            print("\nTip: Use --all to see dependency groups")

    # === Git-based operations ===

    @with_env_logging("repair")
    def repair(self, args: argparse.Namespace, logger=None) -> None:
        """Repair environment to match pyproject.toml (for manual edits or git operations)."""
        env = self._get_env(args)

        # Get status first
        status = env.status()

        if status.is_synced:
            print("✓ No changes to apply")
            return

        # Get preview for display and later use
        preview: dict[str, Any] = status.get_sync_preview()

        # Confirm unless --yes
        if not args.yes:

            # Check if there are actually any changes to show
            has_changes = (
                preview['nodes_to_install'] or
                preview['nodes_to_remove'] or
                preview['nodes_to_update'] or
                preview['packages_to_sync'] or
                preview['workflows_to_add'] or
                preview['workflows_to_update'] or
                preview['workflows_to_remove'] or
                preview.get('models_downloadable') or
                preview.get('models_unavailable')
            )

            if not has_changes:
                print("✓ No changes to apply (environment is synced)")
                return

            print("This will apply the following changes:")

            if preview['nodes_to_install']:
                print(f"  • Install {len(preview['nodes_to_install'])} missing nodes:")
                for node in preview['nodes_to_install']:
                    print(f"    - {node}")

            if preview['nodes_to_remove']:
                print(f"  • Remove {len(preview['nodes_to_remove'])} extra nodes:")
                for node in preview['nodes_to_remove']:
                    print(f"    - {node}")

            if preview['nodes_to_update']:
                print(f"  • Update {len(preview['nodes_to_update'])} nodes to correct versions:")
                for mismatch in preview['nodes_to_update']:
                    print(f"    - {mismatch['name']}: {mismatch['actual']} → {mismatch['expected']}")

            if preview['packages_to_sync']:
                print("  • Sync Python packages")

            # Show workflow changes categorized by operation
            if preview['workflows_to_add']:
                print(f"  • Add {len(preview['workflows_to_add'])} new workflow(s) to ComfyUI:")
                for workflow_name in preview['workflows_to_add']:
                    print(f"    - {workflow_name}")

            if preview['workflows_to_update']:
                print(f"  • Update {len(preview['workflows_to_update'])} workflow(s) in ComfyUI:")
                for workflow_name in preview['workflows_to_update']:
                    print(f"    - {workflow_name}")

            if preview['workflows_to_remove']:
                print(f"  • Remove {len(preview['workflows_to_remove'])} workflow(s) from ComfyUI:")
                for workflow_name in preview['workflows_to_remove']:
                    print(f"    - {workflow_name}")

            # Show model download preview with URLs and paths
            if preview.get('models_downloadable'):
                print("\n  Models:")
                count = len(preview['models_downloadable'])
                print(f"    • Download {count} missing model(s):\n")
                for idx, missing_info in enumerate(preview['models_downloadable'][:5], 1):
                    print(f"      [{idx}/{min(count, 5)}] {missing_info.model.filename} ({missing_info.criticality})")
                    # Show source URL
                    if missing_info.model.sources:
                        source_url = missing_info.model.sources[0]
                        # Truncate long URLs
                        if len(source_url) > 70:
                            display_url = source_url[:67] + "..."
                        else:
                            display_url = source_url
                        print(f"         From: {display_url}")
                    # Show target path
                    print(f"           To: {missing_info.model.relative_path}")
                if count > 5:
                    print(f"\n      ... and {count - 5} more")

            if preview.get('models_unavailable'):
                print("\n  ⚠️  Models unavailable:")
                for missing_info in preview['models_unavailable'][:3]:
                    print(f"      - {missing_info.model.filename} (no sources)")

            response = input("\nContinue? (y/N): ")
            if response.lower() != 'y':
                print("Cancelled")
                return

        print(f"⚙️ Applying changes to: {env.name}")

        # Create callbacks for node and model progress
        from comfygit_core.models.workflow import BatchDownloadCallbacks, NodeInstallCallbacks

        from .utils.progress import create_progress_callback

        # Node installation callbacks
        def on_node_start(node_id, idx, total):
            print(f"  [{idx}/{total}] Installing {node_id}...", end=" ", flush=True)

        def on_node_complete(node_id, success, error):
            if success:
                print("✓")
            else:
                print(f"✗ ({error})")

        node_callbacks = NodeInstallCallbacks(
            on_node_start=on_node_start,
            on_node_complete=on_node_complete
        )

        # Model download callbacks
        def on_file_start(filename, idx, total):
            print(f"   [{idx}/{total}] Downloading {filename}...")

        def on_file_complete(filename, success, error):
            print()  # New line after progress bar
            if success:
                print(f"   ✓ {filename}")
            else:
                print(f"   ✗ {filename}: {error}")

        model_callbacks = BatchDownloadCallbacks(
            on_file_start=on_file_start,
            on_file_progress=create_progress_callback(),
            on_file_complete=on_file_complete
        )

        # Apply changes with node and model callbacks
        try:
            # Show header if nodes to install
            if preview['nodes_to_install']:
                print("\n⬇️  Installing nodes...")

            model_strategy = getattr(args, 'models', 'all')
            sync_result = env.sync(
                model_strategy=model_strategy,
                model_callbacks=model_callbacks,
                node_callbacks=node_callbacks
            )

            # Show completion message if nodes were installed
            if preview['nodes_to_install']:
                print()  # Blank line after node installation

            # Check for errors
            if not sync_result.success:
                for error in sync_result.errors:
                    print(f"⚠️  {error}", file=sys.stderr)

            # Show model download summary
            if sync_result.models_downloaded:
                print(f"\n✓ Downloaded {len(sync_result.models_downloaded)} model(s)")

            if sync_result.models_failed:
                print(f"\n⚠️  {len(sync_result.models_failed)} model(s) failed:")
                for filename, error in sync_result.models_failed[:3]:
                    print(f"   • {filename}: {error}")

        except Exception as e:
            if logger:
                logger.error(f"Sync failed for environment '{env.name}': {e}", exc_info=True)
            print(f"✗ Failed to apply changes: {e}", file=sys.stderr)
            sys.exit(1)

        print("✓ Changes applied successfully!")
        print(f"\nEnvironment '{env.name}' is ready to use")

    @with_env_logging("doctor")
    def doctor(self, args: argparse.Namespace, logger=None) -> None:
        """Diagnose and (optionally) repair essential tooling for the environment venv.

        Initial scope: ensure `uv` is importable in the environment's `.venv`.
        """
        from comfygit_core.utils.filesystem import get_venv_python

        env = self._get_env(args)
        check_only = bool(getattr(args, "check_only", False))

        venv_python = get_venv_python(env.path)
        if not venv_python or not venv_python.exists():
            system_uv = shutil.which("uv")
            if system_uv and not check_only:
                python_version = self._get_python_version(env)
                print(f"⚙️ Creating missing venv for: {env.name}")
                result = subprocess.run(
                    [system_uv, "venv", str(env.venv_path), "--python", python_version, "--seed"],
                    text=True,
                    capture_output=True,
                )
                if result.returncode != 0:
                    print("✗ Failed to create venv using system uv.", file=sys.stderr)
                    if result.stderr:
                        print(result.stderr.strip(), file=sys.stderr)
                    sys.exit(1)
                venv_python = get_venv_python(env.path)

            if not venv_python or not venv_python.exists():
                print(f"✗ No environment venv python found for: {env.name}", file=sys.stderr)
                print(f"  Expected: {env.path / '.venv'}", file=sys.stderr)
                print("  Fix: install system uv and re-run `cg doctor`.", file=sys.stderr)
                sys.exit(1)

        def _check_uv_installed() -> tuple[bool, str | None]:
            check = subprocess.run(
                [str(venv_python), "-c", "import uv; print(getattr(uv, '__version__', 'unknown'))"],
                text=True,
                capture_output=True,
            )
            if check.returncode == 0:
                return True, (check.stdout.strip() or None)
            return False, None

        ok, version = _check_uv_installed()
        if ok:
            ver = f" ({version})" if version else ""
            print(f"✓ uv is installed in {env.name} venv{ver}")
            return

        print(f"✗ uv is missing from {env.name} venv", file=sys.stderr)
        if check_only:
            sys.exit(1)

        system_uv = shutil.which("uv")
        if system_uv:
            print("⚙️ Repair: using system uv to reinstall uv into the environment venv")
            install = subprocess.run(
                [system_uv, "pip", "install", "--python", str(venv_python), "uv>=0.7"],
                text=True,
                capture_output=True,
            )
            if install.returncode != 0:
                print("✗ Failed to reinstall uv using system uv.", file=sys.stderr)
                if install.stderr:
                    print(install.stderr.strip(), file=sys.stderr)
                sys.exit(1)
        else:
            print("⚙️ Repair: reinstalling uv using the environment venv pip")

            pip_check = subprocess.run(
                [str(venv_python), "-m", "pip", "--version"],
                text=True,
                capture_output=True,
            )
            if pip_check.returncode != 0:
                ensurepip = subprocess.run(
                    [str(venv_python), "-m", "ensurepip", "--upgrade"],
                    text=True,
                    capture_output=True,
                )
                if ensurepip.returncode != 0:
                    print("✗ pip is not available in the environment venv, and ensurepip failed.", file=sys.stderr)
                    if ensurepip.stderr:
                        print(ensurepip.stderr.strip(), file=sys.stderr)
                    print("  Fix: install system uv and re-run `cg doctor`.", file=sys.stderr)
                    sys.exit(1)

            install = subprocess.run(
                [str(venv_python), "-m", "pip", "install", "uv>=0.7"],
                text=True,
                capture_output=True,
            )
            if install.returncode != 0:
                print("✗ Failed to reinstall uv using pip.", file=sys.stderr)
                if install.stderr:
                    print(install.stderr.strip(), file=sys.stderr)
                sys.exit(1)

        ok, version = _check_uv_installed()
        if not ok:
            print("✗ Repair attempted, but uv is still not importable in the environment venv.", file=sys.stderr)
            sys.exit(1)

        ver = f" ({version})" if version else ""
        print(f"✓ Reinstalled uv into {env.name} venv{ver}")
        print("  Next: re-run your update/sync command (e.g. `cg sync` or node update).")

    @with_env_logging("checkout")
    def checkout(self, args: argparse.Namespace, logger=None) -> None:
        """Checkout commits, branches, or files."""
        from .strategies.rollback import AutoRollbackStrategy, InteractiveRollbackStrategy

        env = self._get_env(args)

        try:
            if args.branch:
                # Create new branch and switch (git checkout -b semantics)
                start_point = args.ref if args.ref is not None else "HEAD"
                print(f"Creating and switching to branch '{args.branch}'...")
                env.create_and_switch_branch(args.branch, start_point=start_point)
                print(f"✓ Switched to new branch '{args.branch}'")
            else:
                # Just checkout ref - ref is required when not using -b
                if args.ref is None:
                    print("✗ Error: ref argument is required when not using -b", file=sys.stderr)
                    sys.exit(1)

                print(f"Checking out '{args.ref}'...")

                # Choose strategy
                strategy = AutoRollbackStrategy() if args.yes or args.force else InteractiveRollbackStrategy()

                env.checkout(args.ref, strategy=strategy, force=args.force)

                # Check if detached HEAD
                current_branch = env.get_current_branch()
                if current_branch is None:
                    print(f"✓ HEAD is now at {args.ref} (detached)")
                    print("  You are in 'detached HEAD' state. To keep changes:")
                    print("    cg checkout -b <new-branch-name>")
                else:
                    print(f"✓ Switched to branch '{current_branch}'")
        except Exception as e:
            if logger:
                logger.error(f"Checkout failed: {e}", exc_info=True)
            print(f"✗ Checkout failed: {e}", file=sys.stderr)
            sys.exit(1)

    @with_env_logging("branch")
    def branch(self, args: argparse.Namespace, logger=None) -> None:
        """Manage branches."""
        env = self._get_env(args)

        try:
            if args.name is None:
                # List branches
                branches = env.list_branches()
                if not branches:
                    print("No branches found")
                    return

                print("Branches:")
                is_detached = False
                for name, is_current in branches:
                    marker = "* " if is_current else "  "
                    print(f"{marker}{name}")
                    if is_current and 'detached' in name.lower():
                        is_detached = True

                # Show help if in detached HEAD
                if is_detached:
                    print()
                    print("⚠️  You are in detached HEAD state")
                    print("   To save your work, create a branch:")
                    print("   cg checkout -b <branch-name>")
            elif args.delete or args.force_delete:
                # Delete branch
                force = args.force_delete
                print(f"Deleting branch '{args.name}'...")
                env.delete_branch(args.name, force=force)
                print(f"✓ Deleted branch '{args.name}'")
            else:
                # Create branch (don't switch)
                print(f"Creating branch '{args.name}'...")
                env.create_branch(args.name)
                print(f"✓ Created branch '{args.name}'")
        except Exception as e:
            if logger:
                logger.error(f"Branch operation failed: {e}", exc_info=True)
            print(f"✗ Branch operation failed: {e}", file=sys.stderr)
            sys.exit(1)

    @with_env_logging("switch")
    def switch(self, args: argparse.Namespace, logger=None) -> None:
        """Switch to branch."""
        env = self._get_env(args)

        try:
            print(f"Switching to branch '{args.branch}'...")
            env.switch_branch(args.branch, create=args.create)
            print(f"✓ Switched to branch '{args.branch}'")
        except Exception as e:
            if logger:
                logger.error(f"Switch failed: {e}", exc_info=True)
            print(f"✗ Switch failed: {e}", file=sys.stderr)
            sys.exit(1)

    @with_env_logging("reset")
    def reset_git(self, args: argparse.Namespace, logger=None) -> None:
        """Reset HEAD to ref (git-native reset)."""
        from .strategies.rollback import InteractiveRollbackStrategy

        env = self._get_env(args)

        # Determine mode
        if args.hard:
            mode = "hard"
        elif args.soft:
            mode = "soft"
        else:
            mode = "mixed"  # default

        try:
            # Choose strategy for hard mode
            strategy = None
            if mode == "hard" and not args.yes:
                strategy = InteractiveRollbackStrategy()

            print(f"Resetting to '{args.ref}' (mode: {mode})...")
            env.reset(args.ref, mode=mode, strategy=strategy, force=args.yes)
            print(f"✓ Reset to '{args.ref}'")
        except Exception as e:
            if logger:
                logger.error(f"Reset failed: {e}", exc_info=True)
            print(f"✗ Reset failed: {e}", file=sys.stderr)
            sys.exit(1)

    @with_env_logging("merge")
    def merge(self, args: argparse.Namespace, logger=None) -> None:
        """Merge branch into current with atomic conflict resolution."""
        env = self._get_env(args)

        try:
            current = env.get_current_branch()
            if current is None:
                print("✗ Cannot merge while in detached HEAD state")
                sys.exit(1)

            # Phase 1: Preview
            diff = env.preview_merge(args.branch)

            if not diff.has_changes:
                if diff.is_already_merged:
                    print(f"\n✓ '{args.branch}' is already merged into '{current}'.")
                elif diff.is_fast_forward:
                    print(f"\n✓ '{args.branch}' has commits but no ComfyGit changes.")
                    print("   Merge will bring in commits without affecting nodes/models/workflows.")
                else:
                    print(f"\n✓ No ComfyGit configuration changes to merge from '{args.branch}'.")
                return

            # Preview mode - read-only, just show what would change
            if getattr(args, "preview", False):
                self._display_diff_preview(diff)
                if diff.has_conflicts:
                    print("\n⚠️  Conflicts will occur. Review before merging.")
                return

            self._display_diff_preview(diff)

            # Phase 2: Collect resolutions if conflicts exist
            resolutions: dict = {}
            strategy_option: str | None = None
            auto_resolve = getattr(args, "auto_resolve", None)
            strategy = getattr(args, "strategy", None)

            if strategy:
                # Global strategy flag - use for all conflicts
                strategy_option = strategy
            elif auto_resolve:
                # Auto-resolve flag
                from .strategies.conflict_resolver import AutoConflictResolver
                resolver = AutoConflictResolver(auto_resolve)
                resolutions = resolver.resolve_all(diff)
                strategy_option = "theirs" if auto_resolve == "theirs" else "ours"
            elif diff.has_conflicts:
                # Interactive conflict resolution - ONLY workflow conflicts shown
                from .strategies.conflict_resolver import InteractiveConflictResolver

                print("\n⚠️  Conflicts detected:")
                resolver = InteractiveConflictResolver()
                resolutions = resolver.resolve_all(diff)

                # All conflicts must be resolved - no skip option
                if not resolutions and diff.has_conflicts:
                    print("\n✗ No conflicts were resolved. Merge aborted.")
                    sys.exit(1)

                # Determine strategy from resolutions
                unique_resolutions = set(resolutions.values())
                if unique_resolutions == {"take_target"}:
                    strategy_option = "theirs"
                elif unique_resolutions == {"take_base"}:
                    strategy_option = "ours"
                # Mixed: no global strategy, rely on per-file resolution

            # Phase 3: Execute merge
            print(f"\nMerging '{args.branch}' into '{current}'...")

            # Use atomic merge when we have per-file resolutions (mixed mine/theirs)
            # Otherwise use standard merge with global strategy
            if resolutions and strategy_option is None:
                # Mixed resolutions - use atomic executor for per-file resolution
                result = env.execute_atomic_merge(args.branch, resolutions)
                if not result.success:
                    print(f"✗ Merge failed: {result.error}", file=sys.stderr)
                    sys.exit(1)
            else:
                # Global strategy or no resolutions - use standard merge
                env.merge_branch(
                    args.branch,
                    message=getattr(args, "message", None),
                    strategy_option=strategy_option,
                )

            print(f"✓ Merged '{args.branch}' into '{current}'")
        except Exception as e:
            if logger:
                logger.error(f"Merge failed: {e}", exc_info=True)
            print(f"✗ Merge failed: {e}", file=sys.stderr)
            sys.exit(1)

    @with_env_logging("revert")
    def revert(self, args: argparse.Namespace, logger=None) -> None:
        """Revert a commit."""
        env = self._get_env(args)

        try:
            print(f"Reverting commit '{args.commit}'...")
            env.revert_commit(args.commit)
            print(f"✓ Reverted commit '{args.commit}'")
        except Exception as e:
            if logger:
                logger.error(f"Revert failed: {e}", exc_info=True)
            print(f"✗ Revert failed: {e}", file=sys.stderr)
            sys.exit(1)

    @with_env_logging("commit")
    def commit(self, args: argparse.Namespace, logger=None) -> None:
        """Commit workflows with optional issue resolution."""
        env = self._get_env(args)

        # Warn if in detached HEAD before allowing commit
        current_branch = env.get_current_branch()
        if current_branch is None and not args.yes:
            print("⚠️  Warning: You are in detached HEAD state!")
            print("   Commits made here will not be saved to any branch.")
            print()
            print("Options:")
            print("  • Create a branch first: cg checkout -b <branch-name>")
            print("  • Commit anyway (not recommended): use --yes flag")
            print()
            response = input("Continue with commit in detached HEAD? (y/N): ")
            if response.lower() != 'y':
                print("Commit cancelled. Create a branch first.")
                sys.exit(0)
            print()  # Extra spacing before commit output

        print("📋 Analyzing workflows...")

        # Get workflow status (read-only analysis)
        try:
            workflow_status = env.workflow_manager.get_workflow_status()

            if logger:
                logger.debug(f"Workflow status: {workflow_status.sync_status}")

            # Check if there are ANY committable changes (workflows OR git)
            if not env.has_committable_changes():
                print("✓ No changes to commit")
                return

        except Exception as e:
            if logger:
                logger.error(f"Workflow analysis failed: {e}", exc_info=True)
            print(f"✗ Failed to analyze workflows: {e}", file=sys.stderr)
            sys.exit(1)

        # Check commit safety
        if not workflow_status.is_commit_safe and not getattr(args, 'allow_issues', False):
            print("\n⚠ Cannot commit - workflows have unresolved issues:\n")
            for wf in workflow_status.workflows_with_issues:
                print(f"  • {wf.name}: {wf.issue_summary}")

            print("\n💡 Options:")
            print("  1. Resolve issues: cg workflow resolve \"<name>\"")
            print("  2. Force commit: cg commit -m 'msg' --allow-issues")
            sys.exit(1)

        # Execute commit with chosen strategies
        try:
            env.execute_commit(
                workflow_status=workflow_status,
                message=args.message,
                allow_issues=getattr(args, 'allow_issues', False)
            )
        except Exception as e:
            if logger:
                logger.error(f"Commit failed for environment '{env.name}': {e}", exc_info=True)
            print(f"✗ Commit failed: {e}", file=sys.stderr)
            sys.exit(1)

        # Display results on success
        print(f"✅ Commit successful: {args.message if args.message else 'Update workflows'}")

        # Show what was done
        new_count = len(workflow_status.sync_status.new)
        modified_count = len(workflow_status.sync_status.modified)
        deleted_count = len(workflow_status.sync_status.deleted)

        if new_count > 0:
            print(f"  • Added {new_count} workflow(s)")
        if modified_count > 0:
            print(f"  • Updated {modified_count} workflow(s)")
        if deleted_count > 0:
            print(f"  • Deleted {deleted_count} workflow(s)")


    # === Git remote operations ===

    @with_env_logging("pull")
    def pull(self, args: argparse.Namespace, logger=None) -> None:
        """Pull from remote and repair environment."""
        env = self._get_env(args)

        # Check remote exists
        if not env.git_manager.has_remote(args.remote):
            print(f"✗ Remote '{args.remote}' not configured")
            print()
            # Check if other remotes exist
            remotes = env.git_manager.list_remotes()
            if remotes:
                remote_names = list({r[0] for r in remotes})  # Unique names
                print("💡 Use an existing remote:")
                print(f"   cg pull -r {remote_names[0]}")
            else:
                print("💡 Set up a remote first:")
                print(f"   cg remote add {args.remote} <url>")
            sys.exit(1)

        # Preview mode - read-only, just show what would change
        branch = getattr(args, 'branch', None)
        if getattr(args, "preview", False):
            try:
                print(f"Fetching from {args.remote}...")
                diff = env.preview_pull(remote=args.remote, branch=branch)

                if not diff.has_changes:
                    if diff.is_already_merged:
                        print("\n✓ Already up to date.")
                    elif diff.is_fast_forward:
                        print("\n✓ Remote has commits but no ComfyGit changes.")
                        print("   Pull will bring in commits without affecting nodes/models/workflows.")
                    else:
                        print("\n✓ No ComfyGit configuration changes to pull.")
                    return

                self._display_diff_preview(diff)

                if diff.has_conflicts:
                    print("\n⚠️  Conflicts will occur. Resolve before pulling.")
                return  # Preview is read-only, don't continue to actual pull
            except Exception as e:
                if logger:
                    logger.error(f"Preview failed: {e}", exc_info=True)
                print(f"✗ Preview failed: {e}", file=sys.stderr)
                sys.exit(1)

        # Check for uncommitted changes first
        if env.has_committable_changes() and not getattr(args, 'force', False):
            print("⚠️  You have uncommitted changes")
            print()
            print("💡 Options:")
            print("  • Commit: cg commit -m 'message'")
            print("  • Discard: cg reset --hard")
            print("  • Force: cg pull origin --force")
            sys.exit(1)

        try:
            # Determine merge strategy
            strategy_option: str | None = None
            auto_resolve = getattr(args, "auto_resolve", None)

            if auto_resolve:
                # Use git -X strategy based on auto-resolve choice
                strategy_option = "theirs" if auto_resolve == "theirs" else "ours"
            else:
                # Check for conflicts before pull
                print(f"Checking for conflicts with {args.remote}...")
                diff = env.preview_pull(remote=args.remote, branch=branch)
                if diff.has_conflicts:
                    # Interactive conflict resolution
                    from .strategies.conflict_resolver import InteractiveConflictResolver

                    current = env.get_current_branch() or "HEAD"
                    print(f"\n⚠️  Conflicts detected between '{current}' and '{args.remote}':")
                    self._display_diff_preview(diff)

                    resolver = InteractiveConflictResolver()
                    resolutions = resolver.resolve_all(diff)

                    # Check if any conflicts were skipped
                    skipped = [k for k, v in resolutions.items() if v == "skip"]
                    if skipped:
                        print(f"\n⚠️  {len(skipped)} conflict(s) will be skipped.")
                        print("   You may need to resolve them manually after pull.")

                    # Determine strategy from resolutions
                    non_skip = [v for v in resolutions.values() if v != "skip"]
                    unique_resolutions = set(non_skip)
                    if unique_resolutions == {"take_target"}:
                        strategy_option = "theirs"
                    elif unique_resolutions == {"take_base"}:
                        strategy_option = "ours"
                    # Mixed or empty: no strategy, git decides

            print(f"📥 Pulling from {args.remote}...")

            # Handle torch-backend: use override, read from file, or probe if missing
            torch_backend_override = getattr(args, 'torch_backend', None)
            torch_backend, was_probed = self._get_or_probe_backend(env, torch_backend_override)

            if torch_backend_override:
                print(f"🔧 Using PyTorch backend override: {torch_backend}")
            elif was_probed:
                print(f"🔧 Auto-detected PyTorch backend: {torch_backend}")
                print(f"   To save: cg env-config torch-backend set {torch_backend}")
            else:
                print(f"🔧 Using PyTorch backend: {torch_backend}")

            # Create callbacks for node and model progress (reuse repair command patterns)
            from comfygit_core.models.workflow import BatchDownloadCallbacks, NodeInstallCallbacks

            from .utils.progress import create_progress_callback

            # Node installation callbacks
            def on_node_start(_node_id: str, idx: int, total: int) -> None:
                print(f"  [{idx}/{total}] Installing {_node_id}...", end=" ", flush=True)

            def on_node_complete(_node_id: str, success: bool, error: str | None) -> None:
                if success:
                    print("✓")
                else:
                    print(f"✗ ({error})")

            node_callbacks = NodeInstallCallbacks(
                on_node_start=on_node_start,
                on_node_complete=on_node_complete
            )

            # Model download callbacks
            def on_file_start(filename: str, idx: int, total: int) -> None:
                print(f"   [{idx}/{total}] Downloading {filename}...")

            def on_file_complete(filename: str, success: bool, error: str | None) -> None:
                print()  # New line after progress bar
                if success:
                    print(f"   ✓ {filename}")
                else:
                    print(f"   ✗ {filename}: {error}")

            model_callbacks = BatchDownloadCallbacks(
                on_file_start=on_file_start,
                on_file_progress=create_progress_callback(),
                on_file_complete=on_file_complete
            )

            # Pull and repair with progress callbacks
            force = getattr(args, 'force', False)
            result = env.pull_and_repair(
                remote=args.remote,
                branch=branch,
                model_strategy=getattr(args, 'models', 'all'),
                model_callbacks=model_callbacks,
                node_callbacks=node_callbacks,
                strategy_option=strategy_option,
                force=force,
                backend_override=torch_backend,
            )

            # Extract sync result for summary
            sync_result = result.get('sync_result')

            print(f"\n✓ Pulled changes from {args.remote}")

            # Show summary of what was synced (like repair command)
            if sync_result:
                summary_items = []
                if sync_result.nodes_installed:
                    summary_items.append(f"Installed {len(sync_result.nodes_installed)} node(s)")
                if sync_result.nodes_removed:
                    summary_items.append(f"Removed {len(sync_result.nodes_removed)} node(s)")
                if sync_result.models_downloaded:
                    summary_items.append(f"Downloaded {len(sync_result.models_downloaded)} model(s)")

                if summary_items:
                    for item in summary_items:
                        print(f"   • {item}")

            print("\n⚙️  Environment synced successfully")

        except KeyboardInterrupt:
            # User pressed Ctrl+C - git changes already rolled back by core
            if logger:
                logger.warning("Pull interrupted by user")
            print("\n⚠️  Pull interrupted - git changes rolled back", file=sys.stderr)
            sys.exit(1)
        except ValueError as e:
            # Merge conflicts
            if logger:
                logger.error(f"Pull failed: {e}", exc_info=True)

            # Check if it's a merge conflict
            error_str = str(e)
            if "Merge conflict" in error_str or "conflict" in error_str.lower():
                print("\n✗ Merge conflict detected", file=sys.stderr)
                print()
                print("💡 To resolve:")
                print(f"   1. cd {env.cec_path}")
                print("   2. git status  # See conflicted files")
                print("   3. Edit conflicts and resolve")
                print("   4. git add <resolved-files>")
                print("   5. git commit")
                print("   6. cg repair  # Sync environment")
            else:
                print(f"✗ Pull failed: {e}", file=sys.stderr)
            sys.exit(1)
        except OSError as e:
            # Network, auth, or other git errors
            if logger:
                logger.error(f"Pull failed: {e}", exc_info=True)

            # Check if it's a merge conflict (OSError from git_merge)
            error_str = str(e)
            if "Merge conflict" in error_str or "conflict" in error_str.lower():
                print("\n✗ Merge conflict detected", file=sys.stderr)
                print()
                print("💡 To resolve:")
                print(f"   1. cd {env.cec_path}")
                print("   2. git status  # See conflicted files")
                print("   3. Edit conflicts and resolve")
                print("   4. git add <resolved-files>")
                print("   5. git commit")
                print("   6. cg repair  # Sync environment")
            else:
                print(f"✗ Pull failed: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            if logger:
                logger.error(f"Pull failed: {e}", exc_info=True)
            print(f"✗ Pull failed: {e}", file=sys.stderr)
            sys.exit(1)

    @with_env_logging("push")
    def push(self, args: argparse.Namespace, logger=None) -> None:
        """Push commits to remote."""
        env = self._get_env(args)

        # Check for uncommitted changes
        if env.has_committable_changes():
            print("⚠️  You have uncommitted changes")
            print()
            print("💡 Commit first:")
            print("   cg commit -m 'your message'")
            sys.exit(1)

        # Check remote exists
        if not env.git_manager.has_remote(args.remote):
            print(f"✗ Remote '{args.remote}' not configured")
            print()
            # Check if other remotes exist
            remotes = env.git_manager.list_remotes()
            if remotes:
                remote_names = list({r[0] for r in remotes})  # Unique names
                print("💡 Use an existing remote:")
                print(f"   cg push -r {remote_names[0]}")
            else:
                print("💡 Set up a remote first:")
                print(f"   cg remote add {args.remote} <url>")
            sys.exit(1)

        try:
            force = getattr(args, 'force', False)

            if force:
                print(f"📤 Force pushing to {args.remote}...")
            else:
                print(f"📤 Pushing to {args.remote}...")

            # Push (with force flag if specified)
            env.push_commits(remote=args.remote, force=force)

            if force:
                print(f"   ✓ Force pushed commits to {args.remote}")
            else:
                print(f"   ✓ Pushed commits to {args.remote}")

            # Show remote URL
            from comfygit_core.utils.git import git_remote_get_url
            remote_url = git_remote_get_url(env.cec_path, args.remote)
            if remote_url:
                print()
                print(f"💾 Remote: {remote_url}")

        except ValueError as e:
            # No remote or workflow issues
            if logger:
                logger.error(f"Push failed: {e}", exc_info=True)
            print(f"✗ Push failed: {e}", file=sys.stderr)
            sys.exit(1)
        except OSError as e:
            # Network, auth, or git errors
            if logger:
                logger.error(f"Push failed: {e}", exc_info=True)
            print(f"✗ Push failed: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            if logger:
                logger.error(f"Push failed: {e}", exc_info=True)
            print(f"✗ Push failed: {e}", file=sys.stderr)
            sys.exit(1)

    @with_env_logging("remote")
    def remote(self, args: argparse.Namespace, logger=None) -> None:
        """Manage git remotes."""
        env = self._get_env(args)

        subcommand = args.remote_command

        try:
            if subcommand == "add":
                # Add remote
                if not args.name or not args.url:
                    print("✗ Usage: cg remote add <name> <url>")
                    sys.exit(1)

                env.git_manager.add_remote(args.name, args.url)
                print(f"✓ Added remote '{args.name}': {args.url}")

            elif subcommand == "remove":
                # Remove remote
                if not args.name:
                    print("✗ Usage: cg remote remove <name>")
                    sys.exit(1)

                env.git_manager.remove_remote(args.name)
                print(f"✓ Removed remote '{args.name}'")

            elif subcommand == "list":
                # List remotes
                remotes = env.git_manager.list_remotes()

                if not remotes:
                    print("No remotes configured")
                    print()
                    print("💡 Add a remote:")
                    print("   cg remote add origin <url>")
                else:
                    print("Remotes:")
                    for name, url, remote_type in remotes:
                        print(f"  {name}\t{url} ({remote_type})")

            else:
                print(f"✗ Unknown remote command: {subcommand}")
                print("   Usage: cg remote [add|remove|list]")
                sys.exit(1)

        except ValueError as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(1)
        except OSError as e:
            if logger:
                logger.error(f"Remote operation failed: {e}", exc_info=True)
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(1)

    # === Workflow management ===

    @with_env_logging("workflow list", get_env_name=lambda self, args: self._get_env(args).name)
    def workflow_list(self, args: argparse.Namespace) -> None:
        """List all workflows with their sync status."""
        env = self._get_env(args)

        workflows = env.list_workflows()

        if workflows.total_count == 0:
            print("No workflows found")
            return

        print(f"Workflows in '{env.name}':")

        if workflows.synced:
            print("\n✓ Synced (up to date):")
            for name in workflows.synced:
                print(f"  📋 {name}")

        if workflows.modified:
            print("\n⚠ Modified (changed since last commit):")
            for name in workflows.modified:
                print(f"  📝 {name}")

        if workflows.new:
            print("\n🆕 New (not committed yet):")
            for name in workflows.new:
                print(f"  ➕ {name}")

        if workflows.deleted:
            print("\n🗑 Deleted (removed from ComfyUI):")
            for name in workflows.deleted:
                print(f"  ➖ {name}")

        # Show commit suggestion if there are changes
        if workflows.has_changes:
            print("\nRun 'cg commit' to save current state")

    @with_env_logging("workflow model importance", get_env_name=lambda self, args: self._get_env(args).name)
    def workflow_model_importance(self, args: argparse.Namespace, logger=None) -> None:
        """Update model importance (criticality) for workflow models."""
        env = self._get_env(args)

        # Determine workflow name (direct or interactive)
        if hasattr(args, 'workflow_name') and args.workflow_name:
            workflow_name = args.workflow_name
        else:
            # Interactive: select workflow
            workflow_name = self._select_workflow_interactive(env)
            if not workflow_name:
                print("✗ No workflow selected")
                return

        # Get workflow models
        models = env.pyproject.workflows.get_workflow_models(workflow_name)
        if not models:
            print(f"✗ No models found in workflow '{workflow_name}'")
            return

        # Determine model (direct or interactive)
        if hasattr(args, 'model_identifier') and args.model_identifier:
            # Direct mode: update single model
            model_identifier = args.model_identifier
            new_importance = args.importance

            success = env.workflow_manager.update_model_criticality(
                workflow_name=workflow_name,
                model_identifier=model_identifier,
                new_criticality=new_importance
            )

            if success:
                print(f"✓ Updated '{model_identifier}' importance to: {new_importance}")
            else:
                print(f"✗ Model '{model_identifier}' not found in workflow '{workflow_name}'")
                sys.exit(1)
        else:
            # Interactive: loop over all models
            print(f"\n📋 Setting model importance for workflow: {workflow_name}")
            print(f"   Found {len(models)} model(s)\n")

            updated_count = 0
            for model in models:
                current_importance = model.criticality
                display_name = model.filename
                if model.hash:
                    display_name += f" ({model.hash[:8]}...)"

                print(f"\nModel: {display_name}")
                print(f"  Current: {current_importance}")
                print("  Options: [r]equired, [f]lexible, [o]ptional, [s]kip")

                # Prompt for new importance
                try:
                    choice = input("  Choice: ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print("\n✗ Cancelled")
                    return

                # Map choice to importance level
                importance_map = {
                    'r': 'required',
                    'f': 'flexible',
                    'o': 'optional',
                    's': None  # Skip
                }

                new_importance = importance_map.get(choice)
                if new_importance is None:
                    if choice == 's':
                        print("  → Skipped")
                        continue
                    else:
                        print("  → Invalid choice, skipping")
                        continue

                # Update model importance
                identifier = model.hash if model.hash else model.filename
                success = env.workflow_manager.update_model_criticality(
                    workflow_name=workflow_name,
                    model_identifier=identifier,
                    new_criticality=new_importance
                )

                if success:
                    print(f"  ✓ Updated to: {new_importance}")
                    updated_count += 1
                else:
                    print("  ✗ Failed to update")

            print(f"\n✓ Updated {updated_count}/{len(models)} model(s)")

    def _select_workflow_interactive(self, env) -> str | None:
        """Interactive workflow selection from available workflows.

        Returns:
            Selected workflow name or None if cancelled
        """
        status = env.workflow_manager.get_workflow_sync_status()
        all_workflows = status.new + status.modified + status.synced

        if not all_workflows:
            print("✗ No workflows found")
            return None

        print("\n📋 Available workflows:")
        for i, name in enumerate(all_workflows, 1):
            # Show sync state
            if name in status.new:
                state = "new"
            elif name in status.modified:
                state = "modified"
            else:
                state = "synced"
            print(f"  {i}. {name} ({state})")

        print()
        try:
            choice = input("Select workflow (number or name): ").strip()
        except (KeyboardInterrupt, EOFError):
            return None

        # Try to parse as number
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(all_workflows):
                return all_workflows[idx]
        except ValueError:
            # Try as name
            if choice in all_workflows:
                return choice

        print(f"✗ Invalid selection: {choice}")
        return None

    @with_env_logging("workflow resolve", get_env_name=lambda self, args: self._get_env(args).name)
    def workflow_resolve(self, args: argparse.Namespace, logger=None) -> None:
        """Resolve workflow dependencies interactively."""
        env = self._get_env(args)

        # Choose strategy
        if args.auto:
            from comfygit_core.strategies.auto import AutoModelStrategy, AutoNodeStrategy
            node_strategy = AutoNodeStrategy()
            model_strategy = AutoModelStrategy()
        else:
            node_strategy = InteractiveNodeStrategy()
            model_strategy = InteractiveModelStrategy()

        # Phase 1: Resolve dependencies (updates pyproject.toml)
        print("\n🔧 Resolving dependencies...")
        try:
            from comfygit_cli.utils.progress import create_batch_download_callbacks

            result = env.resolve_workflow(
                name=args.name,
                node_strategy=node_strategy,
                model_strategy=model_strategy,
                download_callbacks=create_batch_download_callbacks()
            )
        except CDRegistryDataError as e:
            # Registry data unavailable
            formatted = NodeErrorFormatter.format_registry_error(e)
            if logger:
                logger.error(f"Registry data unavailable for workflow resolve: {e}", exc_info=True)
            print("✗ Cannot resolve workflow - registry data unavailable", file=sys.stderr)
            print(formatted, file=sys.stderr)
            sys.exit(1)
        except FileNotFoundError as e:
            if logger:
                logger.error(f"Resolution failed for '{args.name}': {e}", exc_info=True)
            workflow_path = env.workflow_manager.comfyui_workflows / f"{args.name}.json"
            print(f"✗ Workflow '{args.name}' not found at {workflow_path}")
            sys.exit(1)
        except Exception as e:
            if logger:
                logger.error(f"Resolution failed for '{args.name}': {e}", exc_info=True)
            print(f"✗ Failed to resolve dependencies: {e}", file=sys.stderr)
            sys.exit(1)

        # Phase 2: Check for uninstalled nodes and prompt for installation
        uninstalled_nodes = env.get_uninstalled_nodes(workflow_name=args.name)

        if uninstalled_nodes:
            print(f"\n📦 Found {len(uninstalled_nodes)} missing node packs:")
            for node_id in uninstalled_nodes:
                print(f"  • {node_id}")

            # Determine if we should install
            should_install = False

            if hasattr(args, 'install') and args.install:
                # Auto-install mode
                should_install = True
            elif hasattr(args, 'no_install') and args.no_install:
                # Skip install mode
                should_install = False
            else:
                # Interactive prompt (default)
                try:
                    response = input("\nInstall missing nodes? (Y/n): ").strip().lower()
                    should_install = response in ['', 'y', 'yes']
                except KeyboardInterrupt:
                    print("\nSkipped node installation")
                    should_install = False

            if should_install:
                from comfygit_core.models.workflow import NodeInstallCallbacks

                print("\n⬇️  Installing nodes...")

                # Create callbacks for progress display
                def on_node_start(node_id, idx, total):
                    print(f"  [{idx}/{total}] Installing {node_id}...", end=" ", flush=True)

                def on_node_complete(node_id, success, error):
                    if success:
                        print("✓")
                    else:
                        # Handle UV-specific errors
                        if "UVCommandError" in str(error) and logger:
                            try:
                                # Try to extract meaningful error
                                user_msg = error.split(":", 1)[1].strip() if ":" in error else error
                                print(f"✗ ({user_msg})")
                            except:
                                print(f"✗ ({error})")
                        else:
                            print(f"✗ ({error})")

                callbacks = NodeInstallCallbacks(
                    on_node_start=on_node_start,
                    on_node_complete=on_node_complete
                )

                # Install nodes with progress feedback
                installed_count, failed_nodes = env.install_nodes_with_progress(
                    uninstalled_nodes,
                    callbacks=callbacks
                )

                if installed_count > 0:
                    print(f"\n✅ Installed {installed_count}/{len(uninstalled_nodes)} nodes")

                if failed_nodes:
                    print(f"\n⚠️  Failed to install {len(failed_nodes)} nodes:")
                    for node_id, _error in failed_nodes:
                        print(f"  • {node_id}")
                    print("\n💡 For detailed error information:")
                    log_file = self.workspace.paths.logs / env.name / "full.log"
                    print(f"   {log_file}")
                    print("\nYou can try installing them manually:")
                    print("  cg node add <node-id>")
            else:
                print("\nℹ️  Skipped node installation")
                # print("\nℹ️  Skipped node installation. To install later:")
                # print(f"  • Re-run: cg workflow resolve \"{args.name}\"")
                # print("  • Or install individually: cg node add <node-id>")

        # Display final results - check issues first
        uninstalled = env.get_uninstalled_nodes(workflow_name=args.name)

        # Check for category mismatch (blocking issue that resolve can't fix)
        category_mismatches = [m for m in result.models_resolved if m.has_category_mismatch]

        if result.has_issues or uninstalled:
            print("\n⚠️  Partial resolution - issues remain:")

            # Show what was resolved
            if result.models_resolved:
                print(f"  ✓ Resolved {len(result.models_resolved)} models")
            if result.nodes_resolved:
                print(f"  ✓ Resolved {len(result.nodes_resolved)} nodes")

            # Show what's still broken
            if result.nodes_version_gated:
                print(f"  ✗ {len(result.nodes_version_gated)} nodes require newer ComfyUI")
            if result.nodes_uninstallable:
                print(f"  ✗ {len(result.nodes_uninstallable)} nodes matched uninstallable mappings")
            if result.nodes_unresolved:
                print(f"  ✗ {len(result.nodes_unresolved)} nodes couldn't be resolved")
            if result.models_unresolved:
                print(f"  ✗ {len(result.models_unresolved)} models not found")
            if result.models_ambiguous:
                print(f"  ✗ {len(result.models_ambiguous)} ambiguous models")
            if uninstalled:
                print(f"  ✗ {len(uninstalled)} packages need installation")
            if category_mismatches:
                print(f"  ✗ {len(category_mismatches)} models in wrong directory")

            print("\n💡 Next:")
            if category_mismatches:
                print("  Models in wrong directory (move files manually):")
                for m in category_mismatches:
                    expected = m.expected_categories[0] if m.expected_categories else "unknown"
                    print(f"    {m.actual_category}/{m.name} → {expected}/")
            else:
                if result.node_guidance:
                    print("  Node guidance:")
                    for _node_type, message in result.node_guidance.items():
                        print(f"    {message}")
                print(f"  Re-run: cg workflow resolve \"{args.name}\"")
            print("  Or commit with issues: cg commit -m \"...\" --allow-issues")

        elif result.models_resolved or result.nodes_resolved:
            # Check for failed download intents by querying current state (not stale result)
            # Downloads execute AFTER result is created, so we need fresh state
            current_models = env.pyproject.workflows.get_workflow_models(args.name)
            failed_downloads = [
                m for m in current_models
                if m.status == 'unresolved' and m.sources  # Has download intent but still unresolved
            ]

            if failed_downloads:
                print("\n⚠️  Resolution partially complete:")
                # Count successful resolutions (not download intents or successful downloads)
                successful_models = [
                    m for m in result.models_resolved
                    if m.match_type != 'download_intent' or m.resolved_model is not None
                ]
                if successful_models:
                    print(f"  ✓ Resolved {len(successful_models)} models")
                if result.nodes_resolved:
                    print(f"  ✓ Resolved {len(result.nodes_resolved)} nodes")

                print(f"  ⚠️  {len(failed_downloads)} model(s) queued for download (failed to fetch)")
                for m in failed_downloads:
                    print(f"      • {m.filename}")

                print("\n💡 Next:")
                print("  Add Civitai API key: cg config --civitai-key <your-token>")
                print(f"  Try again: cg workflow resolve \"{args.name}\"")
                print("  Or commit anyway: cg commit -m \"...\" --allow-issues")
            else:
                # Check for category mismatch even in "success" case
                if category_mismatches:
                    print("\n⚠️  Resolution complete but models in wrong directory:")
                    if result.models_resolved:
                        print(f"  ✓ Resolved {len(result.models_resolved)} models")
                    if result.nodes_resolved:
                        print(f"  ✓ Resolved {len(result.nodes_resolved)} nodes")
                    print(f"  ✗ {len(category_mismatches)} models in wrong directory")
                    print("\n💡 Next (move files manually):")
                    for m in category_mismatches:
                        expected = m.expected_categories[0] if m.expected_categories else "unknown"
                        print(f"    {m.actual_category}/{m.name} → {expected}/")
                else:
                    print("\n✅ Resolution complete!")
                    if result.models_resolved:
                        print(f"  • Resolved {len(result.models_resolved)} models")
                    if result.nodes_resolved:
                        print(f"  • Resolved {len(result.nodes_resolved)} nodes")
                    print("\n💡 Next:")
                    print(f"  Commit workflows: cg commit -m \"Resolved {args.name}\"")
        else:
            # No changes case - still check for category mismatch
            if category_mismatches:
                print("\n⚠️  No resolution changes but models in wrong directory:")
                print(f"  ✗ {len(category_mismatches)} models in wrong directory")
                print("\n💡 Next (move files manually):")
                for m in category_mismatches:
                    expected = m.expected_categories[0] if m.expected_categories else "unknown"
                    print(f"    {m.actual_category}/{m.name} → {expected}/")
            else:
                print("✓ No changes needed - all dependencies already resolved")

    # ================================================================================
    # Manager Commands - Per-environment comfygit-manager management
    # ================================================================================

    @with_env_logging("manager status")
    def manager_status(self, args: argparse.Namespace, logger: Any = None) -> None:
        """Show manager version and update availability."""
        env = self._get_env(args)

        status = env.get_manager_status()

        print("comfygit-manager")
        print(f"   Current: {status.current_version or 'not installed'}")
        print(f"   Latest:  {status.latest_version or 'unknown'}")

        if status.status == "headless":
            print("   Mode: headless (--no-manager)")
            print(f"   Install manager: cg -e {env.name} manager update")
        elif status.is_legacy:
            print("   Legacy installation (symlinked)")
            print(f"   Run 'cg -e {env.name} manager update' to migrate")
        elif not status.is_tracked:
            print("   Not installed")
            print(f"   Run 'cg -e {env.name} manager update' to install")
        elif status.update_available:
            print("   Update available!")
        else:
            print("   Up to date")

    @with_env_logging("manager update")
    def manager_update(self, args: argparse.Namespace, logger: Any = None) -> None:
        """Update or migrate comfygit-manager."""
        from comfygit_core.strategies.confirmation import (
            AutoConfirmStrategy,
            InteractiveConfirmStrategy,
        )

        env = self._get_env(args)
        version = getattr(args, 'version', None) or "latest"
        use_yes = getattr(args, 'yes', False)

        # Ensure backend is configured (same as sync/run commands)
        had_backend = env.pytorch_manager.has_backend()
        if not had_backend:
            print("⚠️  No PyTorch backend configured. Auto-detecting...")
            python_version = self._get_python_version(env)
            backend = env.pytorch_manager.ensure_backend(python_version)
            print(f"✓ Backend detected and saved: {backend}")
            print("   To change: cg env-config torch-backend set <backend>\n")

        status = env.get_manager_status()

        if status.is_legacy:
            print("Migrating comfygit-manager to per-environment installation...")
        elif not status.is_tracked:
            print("Installing comfygit-manager...")
        else:
            print("Updating comfygit-manager...")

        strategy = AutoConfirmStrategy() if use_yes else InteractiveConfirmStrategy()

        try:
            result = env.update_manager(version=version, confirmation_strategy=strategy)

            if result.changed:
                print(f"   {result.message}")
                print("\n   Restart this environment to use the new version")
            else:
                print(f"   {result.message}")

        except Exception as e:
            print(f"   Failed to update manager: {e}", file=sys.stderr)
            if logger:
                logger.error(f"Manager update failed: {e}", exc_info=True)
            sys.exit(1)

    # ================================================================================
    # Metadata Commands - Environment metadata management
    # ================================================================================

    @with_env_logging("metadata refresh")
    def metadata_refresh(self, args: argparse.Namespace, logger: Any = None) -> None:
        """Refresh extracted metadata from ComfyUI installation.

        Re-extracts builtins and folder paths for the current environment.
        Useful after upgrading ComfyUI or to fix missing metadata files.
        """
        env = self._get_env(args)

        print(f"Refreshing metadata for environment '{env.name}'...")

        try:
            result = env.refresh_metadata()

            if result["builtins_refreshed"]:
                print(f"   Refreshed comfyui_builtins.json ({result['builtins_count']} nodes)")
            else:
                print("   Failed to refresh comfyui_builtins.json")

            if result["folder_paths_refreshed"]:
                print(f"   Refreshed comfyui_folder_paths.json ({result['folder_mappings_count']} folder types)")
            else:
                print("   Failed to refresh comfyui_folder_paths.json")

            if result["builtins_refreshed"] or result["folder_paths_refreshed"]:
                print("\nMetadata refreshed successfully")
            else:
                print("\nNo metadata was refreshed", file=sys.stderr)
                sys.exit(1)

        except ValueError as e:
            print(f"   Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"   Failed to refresh metadata: {e}", file=sys.stderr)
            if logger:
                logger.error(f"Metadata refresh failed: {e}", exc_info=True)
            sys.exit(1)
