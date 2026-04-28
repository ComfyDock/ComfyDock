"""Global workspace-level commands for ComfyGit CLI."""

import argparse
import sys
from functools import cached_property
from pathlib import Path

from comfygit_core.core.workspace import Workspace
from comfygit_core.factories.workspace_factory import WorkspaceFactory
from comfygit_core.models.protocols import ImportCallbacks

from .cli_utils import get_workspace_optional, get_workspace_or_exit
from .logging.environment_logger import WorkspaceLogger, with_workspace_logging
from .logging.logging_config import get_logger
from .utils import create_progress_callback, paginate, show_civitai_auth_help, show_download_stats

logger = get_logger(__name__)



class GlobalCommands:
    """Handler for global workspace commands."""

    def __init__(self) -> None:
        """Initialize global commands handler."""
        pass

    @cached_property
    def workspace(self) -> Workspace:
        return get_workspace_or_exit()

    def _get_or_create_workspace(self, args: argparse.Namespace) -> Workspace:
        """Get existing workspace or initialize a new one with user confirmation.

        Args:
            args: Command arguments, must have 'yes' attribute for non-interactive mode

        Returns:
            Workspace instance (existing or newly created)
        """
        from comfygit_core.factories.workspace_factory import WorkspaceFactory
        from comfygit_core.models.exceptions import CDWorkspaceNotFoundError

        try:
            workspace = WorkspaceFactory.find()
            WorkspaceLogger.set_workspace_path(workspace.path)
            return workspace

        except CDWorkspaceNotFoundError:
            # Determine if we should auto-init
            use_yes = getattr(args, 'yes', False)

            if not use_yes:
                # Interactive: ask user
                response = input("\n✗ Workspace not initialized. Initialize now? [Y/n]: ").strip().lower()
                if response in ['n', 'no']:
                    print("Operation cancelled. Run 'cg init' to initialize workspace manually.")
                    sys.exit(1)
            else:
                # Non-interactive: inform user
                print("\n📦 No workspace found. Initializing with defaults...")

            # Run init flow
            init_args = argparse.Namespace(
                path=None,  # Use default (or COMFYGIT_HOME)
                models_dir=None,
                yes=use_yes  # Pass through --yes flag
            )

            self.init(init_args)

            # Get the newly created workspace
            workspace = WorkspaceFactory.find()
            WorkspaceLogger.set_workspace_path(workspace.path)

            print("\n✓ Workspace initialized! Continuing with command...\n")
            return workspace

    def init(self, args: argparse.Namespace) -> None:
        """Initialize a new ComfyGit workspace.

        Creates:
        - ~/comfygit/ (or custom path)
        - .metadata/ for workspace state
        - uv_cache/ for package management
        - environments/ for ComfyUI environments
        """

        # Validate models directory if provided (before creating workspace)
        explicit_models_dir = getattr(args, 'models_dir', None)
        if explicit_models_dir:
            models_path = explicit_models_dir.resolve()
            if not models_path.exists() or not models_path.is_dir():
                print(f"✗ Models directory not found: {models_path}", file=sys.stderr)
                print("   Falling back to default models directory\n")
                # Clear the flag and enable --yes to avoid interactive prompt
                args.models_dir = None
                args.yes = True

        # Determine workspace path
        path = args.path if (hasattr(args, "path") and args.path) else None

        workspace_paths = WorkspaceFactory.get_paths(path)

        print(f"\n🎯 Initializing ComfyGit workspace at: {workspace_paths.root}")

        try:
            # Create workspace
            workspace = WorkspaceFactory.create(workspace_paths.root)

            # Set workspace path for logging after creation
            WorkspaceLogger.set_workspace_path(workspace.path)

            # Now log this command with the workspace logger
            with WorkspaceLogger.log_command("init", arg_path=path if path else "default"):
                logger.info(f"Workspace initialized at {workspace.path}")

                # Fetch registry data for the new workspace
                print("📦 Fetching latest registry data...")
                success = workspace.update_registry_data()
                if success:
                    print("✓ Registry data downloaded")
                    logger.info("Registry data downloaded successfully")
                else:
                    print("⚠️  Could not fetch registry data")
                    print("   Some features will be limited until registry data is available:")
                    print("   • Automatic node resolution from workflow files")
                    print("   • Node package search and discovery")
                    print("")
                    print("   Download later with: cg registry update")
                    logger.warning("Failed to fetch initial registry data")

            print(f"✓ Workspace initialized at {workspace.path}")

            # Handle models directory setup
            self._setup_models_directory(workspace, args)

            # Show environment variable setup if custom path was used
            if path:
                self._show_workspace_env_setup(workspace.path)

            print("\nNext steps:")
            print("  1. Create an environment: cg create <name>")
            print("  2. Add custom nodes: cg -e <name> node add <node>")
            print("  3. Run ComfyUI: cg -e <name> run")
        except Exception as e:
            print(f"✗ Failed to initialize workspace: {e}", file=sys.stderr)
            sys.exit(1)

    def _show_workspace_env_setup(self, workspace_path: Path) -> None:
        """Show instructions for setting COMFYGIT_HOME for custom workspace location."""
        import os

        print("\n" + "="*70)
        print("⚠️  CUSTOM WORKSPACE LOCATION")
        print("="*70)
        print(f"\nWorkspace created at: {workspace_path}")
        print("\nTo use this workspace in future sessions, set COMFYGIT_HOME:")

        # Detect shell and suggest appropriate config file
        shell = os.environ.get('SHELL', '')
        if 'bash' in shell:
            config_file = "~/.bashrc"
        elif 'zsh' in shell:
            config_file = "~/.zshrc"
        elif 'fish' in shell:
            config_file = "~/.config/fish/config.fish"
        else:
            config_file = "your shell profile"

        print(f"\nAdd to {config_file}:")
        print(f'  export COMFYGIT_HOME="{workspace_path}"')
        print("\nOr set temporarily in current session:")
        print(f'  export COMFYGIT_HOME="{workspace_path}"')
        print("\n" + "="*70)

    def _setup_models_directory(self, workspace: Workspace, args: argparse.Namespace) -> None:
        """Handle interactive or automatic models directory setup during init.

        Args:
            workspace: The newly created workspace
            args: CLI arguments containing models_dir and yes flags
        """
        from pathlib import Path


        # Check for explicit flags
        use_interactive = not getattr(args, 'yes', False)
        explicit_models_dir = getattr(args, 'models_dir', None)

        # If explicit models dir provided via flag (already validated in init)
        if explicit_models_dir:
            models_path = explicit_models_dir.resolve()
            print(f"\n📁 Setting models directory: {models_path}")
            self._scan_and_set_models_dir(workspace, models_path)
            return

        # If --yes flag, use default silently
        if not use_interactive:
            self._show_default_models_dir(workspace)
            return

        # Interactive mode
        print("\n📦 Model Directory Setup")
        print("\nComfyGit needs a directory to index your models.")
        print("\nOptions:")
        print("  1. Point to an existing ComfyUI models directory (recommended)")
        print("     → Access all your existing models immediately")
        print("     → Example: ~/ComfyUI/models")
        print("\n  2. Use the default empty directory")
        print(f"     → ComfyGit created: {workspace.paths.models}")
        print("     → Download models as needed later")

        has_existing = input("\nDo you have an existing ComfyUI models directory? (y/N): ").strip().lower()

        if has_existing == 'y':
            while True:
                models_input = input("Enter path to models directory: ").strip()

                if not models_input:
                    print("Using default directory instead")
                    self._show_default_models_dir(workspace)
                    return

                models_path = Path(models_input).expanduser().resolve()

                # Validate directory exists
                if not models_path.exists():
                    print(f"✗ Directory not found: {models_path}")
                    retry = input("Try another path? (y/N): ").strip().lower()
                    if retry != 'y':
                        print("Using default directory instead")
                        self._show_default_models_dir(workspace)
                        return
                    continue

                if not models_path.is_dir():
                    print(f"✗ Not a directory: {models_path}")
                    retry = input("Try another path? (y/N): ").strip().lower()
                    if retry != 'y':
                        print("Using default directory instead")
                        self._show_default_models_dir(workspace)
                        return
                    continue

                # Auto-detect if they entered ComfyUI root instead of models subdir
                if (models_path / "models").exists() and models_path.name != "models":
                    print(f"\n⚠️  Detected ComfyUI installation at: {models_path}")
                    use_subdir = input("Use models/ subdirectory instead? (Y/n): ").strip().lower()
                    if use_subdir != 'n':
                        models_path = models_path / "models"
                        print(f"Using: {models_path}")

                # Scan and confirm
                print(f"\nScanning {models_path}...")
                self._scan_and_set_models_dir(workspace, models_path)
                return
        else:
            # User chose default
            self._show_default_models_dir(workspace)

    def _show_default_models_dir(self, workspace: Workspace) -> None:
        """Show the default models directory message."""
        models_dir = workspace.get_models_directory()
        print(f"\n✓ Using default models directory: {models_dir}")
        print("   (Change later with: cg model index dir <path>)")

    def _scan_and_set_models_dir(self, workspace: Workspace, models_path: Path) -> None:
        """Scan a models directory and set it as the workspace models directory.

        Args:
            workspace: The workspace instance
            models_path: Path to the models directory to scan
        """
        from comfygit_core.utils.common import format_size

        from comfygit_cli.utils.progress import create_model_sync_progress

        try:
            progress = create_model_sync_progress()
            workspace.set_models_directory(models_path, progress=progress)

            # Get stats to show summary
            stats = workspace.get_model_stats()
            total_models = stats.get('total_models', 0)

            if total_models > 0:
                # Calculate total size
                models = workspace.list_models()
                total_size = sum(m.file_size for m in models)

                print(f"\n✓ Models directory set: {models_path}")
                print(f"  Found {total_models} models ({format_size(total_size)})")
            else:
                print(f"\n✓ Models directory set: {models_path}")
                print("  (No models found - directory is empty)")
        except Exception as e:
            logger.error(f"Failed to set models directory: {e}")
            print(f"✗ Failed to scan models directory: {e}", file=sys.stderr)
            print("   Using default models directory instead")
            self._show_default_models_dir(workspace)

    @with_workspace_logging("list")
    def list_envs(self, args: argparse.Namespace) -> None:
        """List all environments in the workspace."""
        logger.info("Listing environments in workspace")

        try:
            environments = self.workspace.list_environments()
            active_env = self.workspace.get_active_environment()
            active_name = active_env.name if active_env else None

            logger.info(f"Found {len(environments)} environments, active: {active_name or 'none'}")

            if not environments:
                print("No environments found.")
                print("Create one with: cg create <name>")
                return

            print("Environments:")
            for env in environments:
                marker = "✓" if env.name == active_name else " "
                status = "(active)" if env.name == active_name else ""
                print(f"  {marker} {env.name:15} {status}")

        except Exception as e:
            logger.error(f"Failed to list environments: {e}")
            print(f"✗ Failed to list environments: {e}", file=sys.stderr)
            sys.exit(1)

    def analyze(self, args: argparse.Namespace) -> None:
        """Analyze a workflow file without requiring a workspace."""
        import json

        import tomlkit

        from comfygit_core.services.workflow_analysis_service import WorkflowAnalysisService

        workspace = get_workspace_optional()
        if workspace:
            service = WorkflowAnalysisService.create_from_workspace(workspace)
        else:
            service = WorkflowAnalysisService.create_standalone()

        try:
            report = service.analyze(args.workflow, online=getattr(args, "online", False))
        except Exception as e:
            print(f"✗ Failed to analyze workflow: {e}", file=sys.stderr)
            sys.exit(1)

        if args.json_output:
            print(json.dumps(report.to_dict(), indent=2, default=str))
            return

        if args.draft_spec:
            print(tomlkit.dumps(report.draft_spec))
            return

        if args.quiet:
            if not report.unresolved_items:
                print("No unresolved items.")
                return
            for item in report.unresolved_items:
                print(
                    f"{item['type']}: {item['name']} - "
                    f"{item['suggestion']} ({item['next_action']})"
                )
            return

        format_name = {
            "ui_list": "ComfyUI UI (list-based)",
            "ui_dict": "ComfyUI UI (dict-based)",
            "api": "ComfyUI API prompt",
            "api_wrapped": "ComfyUI API prompt (wrapped)",
        }.get(report.input_format, report.input_format)

        total_node_types = report.total_unique_node_types
        resolved_node_types = len(report.builtin_nodes) + len(report.resolution.nodes_resolved)

        print(f"Workflow Analysis: {args.workflow.name}")
        print()
        print(f"Format: {format_name}")
        print(f"Nodes:  {report.total_nodes} total, {total_node_types} unique types")
        print(f"Models: {report.total_model_refs} references")
        print()
        print("Node Resolution")
        print(f"  ✓ {len(report.builtin_nodes)} builtin node types")
        print(f"  ✓ {len(report.resolution.nodes_resolved)} custom node types resolved")
        if report.resolution.nodes_version_gated:
            print(f"  ⚠ {len(report.resolution.nodes_version_gated)} version-gated node types")
        unresolved_node_count = (
            len(report.resolution.nodes_uninstallable)
            + len(report.resolution.nodes_unresolved)
            + len(report.resolution.nodes_ambiguous)
        )
        if unresolved_node_count:
            print(f"  ✗ {unresolved_node_count} unresolved/ambiguous node types")
        print()
        print("Model Resolution")
        print(f"  ✓ {len(report.resolution.models_resolved)} models resolved")
        if report.models_with_embedded_urls:
            print(f"  ✓ {report.models_with_embedded_urls} models with embedded URLs")
        if report.models_without_sources:
            print(f"  ⚠ {report.models_without_sources} models without source URLs")
        unresolved_model_count = (
            len(report.resolution.models_unresolved)
            + len(report.resolution.models_ambiguous)
        )
        if unresolved_model_count:
            print(f"  ✗ {unresolved_model_count} unresolved/ambiguous models")
        print()
        print("Summary")
        print(
            f"  Node resolution:  {report.node_resolution_rate:.0f}% "
            f"({resolved_node_types}/{total_node_types})"
        )
        print(
            f"  Model resolution: {report.model_resolution_rate:.0f}% "
            f"({len(report.resolution.models_resolved)}/{report.total_model_refs})"
        )
        print(f"  Confidence: {report.overall_confidence}")

        if args.verbose and report.unresolved_items:
            print()
            print("Unresolved Items")
            for item in report.unresolved_items:
                print(
                    f"  • {item['type']}: {item['name']} - "
                    f"{item['suggestion']} ({item['next_action']})"
                )

    def debug(self, args: argparse.Namespace) -> None:
        """Show application debug logs with smart environment detection."""
        import re

        # Smart detection: workspace flag > -e flag > active env > workspace fallback
        if args.workspace:
            log_file = self.workspace.paths.logs / "workspace" / "full.log"
            log_source = "workspace"
        elif hasattr(args, 'target_env') and args.target_env:
            log_file = self.workspace.paths.logs / args.target_env / "full.log"
            log_source = args.target_env
        else:
            active_env = self.workspace.get_active_environment()
            if active_env:
                log_file = self.workspace.paths.logs / active_env.name / "full.log"
                log_source = active_env.name
            else:
                log_file = self.workspace.paths.logs / "workspace" / "full.log"
                log_source = "workspace"

        if not log_file.exists():
            print(f"✗ No logs found for {log_source}")
            print(f"   Expected at: {log_file}")
            return

        # Read log lines
        try:
            with open(log_file, encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            print(f"✗ Failed to read log file: {e}", file=sys.stderr)
            sys.exit(1)

        # Group lines into complete log records (header + continuation lines)
        log_pattern = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} - ')
        records = []
        current_record = []

        for line in lines:
            if log_pattern.match(line):
                if current_record:
                    records.append(current_record)
                current_record = [line]
            else:
                if current_record:
                    current_record.append(line)
                else:
                    current_record = [line]

        if current_record:
            records.append(current_record)

        # Filter by level if specified
        if args.level:
            records = [r for r in records if r and f" - {args.level} - " in r[0]]

        # Apply line limit to records
        if not args.full:
            records = records[-args.lines:]

        if not records:
            print("No logs found matching criteria")
            return

        # Display
        total_lines = sum(len(record) for record in records)
        print(f"=== Logs for {log_source} ===")
        print(f"Log file: {log_file}")
        if args.level:
            print(f"Level filter: {args.level}")
        print(f"Showing: {len(records)} log records ({total_lines} lines)\n")

        for record in records:
            for line in record:
                print(line.rstrip())

        print("\n=== End of logs ===")
        if not args.full and len(records) == args.lines:
            print("Tip: Use --full to see all logs, or increase --lines to see more")

    @with_workspace_logging("migrate")
    def migrate(self, args: argparse.Namespace) -> None:
        """Migrate an existing ComfyUI installation (not implemented in MVP)."""
        print("⚠️  Migration is not yet implemented in this MVP")
        print("\nFor now, you can:")
        print("  1. Create a new environment: cg create <name>")
        print("  2. Manually add your custom nodes:")
        print("     cg -e <name> node add <node-name-or-url>")
        print("  3. Apply changes: cg -e <name> sync")

        # Still do a basic scan if requested
        if args.scan_only:
            source_path = Path(args.source_path)
            if source_path.exists():
                print(f"\n📋 Basic scan of: {source_path}")

                # Check for ComfyUI
                if (source_path / "main.py").exists():
                    print("  ✓ ComfyUI detected")

                # Check for custom nodes
                custom_nodes = source_path / "custom_nodes"
                if custom_nodes.exists():
                    node_count = len([d for d in custom_nodes.iterdir() if d.is_dir()])
                    print(f"  ✓ Found {node_count} custom nodes")

                # Check for models
                models = source_path / "models"
                if models.exists():
                    print("  ✓ Models directory found")
            else:
                print(f"✗ Path not found: {source_path}")

    @with_workspace_logging("import")
    def import_env(self, args: argparse.Namespace) -> None:
        """Import a ComfyGit environment from a tarball or git repository."""
        from pathlib import Path

        from comfygit_core.utils.git import is_git_url

        # Ensure workspace exists, creating it if necessary
        workspace = self._get_or_create_workspace(args)

        if not args.path:
            print("✗ Please specify path to import tarball or git URL")
            print("  Usage: cg import <path.tar.gz|git-url>")
            sys.exit(1)

        # Detect if this is a git URL or local tarball
        is_git = is_git_url(args.path)

        if is_git:
            print("📦 Importing environment from git repository")
            print(f"   URL: {args.path}")
            if hasattr(args, 'branch') and args.branch:
                print(f"   Branch/Tag: {args.branch}")
            print()
        else:
            tarball_path = Path(args.path)
            if not tarball_path.exists():
                print(f"✗ File not found: {tarball_path}")
                sys.exit(1)
            print(f"📦 Importing environment from {tarball_path.name}")
            print()

        # Get environment name from args or prompt
        if hasattr(args, 'name') and args.name:
            env_name = args.name
        else:
            env_name = input("Environment name: ").strip()
            if not env_name:
                print("✗ Environment name required")
                sys.exit(1)

        # Determine model download strategy
        if hasattr(args, 'models') and args.models:
            strategy = args.models
        elif hasattr(args, 'yes') and args.yes:
            strategy = "all"  # Default to 'all' in non-interactive mode
        else:
            print("\nModel download strategy:")
            print("  1. all      - Download all models with sources")
            print("  2. required - Download only required models")
            print("  3. skip     - Skip all downloads (can resolve later)")
            strategy_choice = input("Choice (1-3) [1]: ").strip() or "1"
            strategy_map = {"1": "all", "2": "required", "3": "skip"}
            strategy = strategy_map.get(strategy_choice, "all")

        # CLI callbacks for progress updates
        class CLIImportCallbacks(ImportCallbacks):
            def __init__(self):
                self.manifest = None
                self.dep_group_successes = []
                self.dep_group_failures = []

            def on_phase(self, phase: str, description: str):
                # Add emojis based on phase
                emoji_map = {
                    "clone_repo": "📥",
                    "clone_comfyui": "🔧",
                    "restore_comfyui": "🔧",
                    "configure_pytorch": "🔧",
                    "install_deps": "🔧",
                    "init_git": "🔧",
                    "copy_workflows": "📝",
                    "sync_nodes": "📦",
                    "resolve_models": "🔄"
                }

                # First phase shows initialization header
                if phase == "clone_repo":
                    print(f"\n📥 {description}")
                elif phase in ["clone_comfyui", "restore_comfyui"]:
                    print("\n🔧 Initializing environment...")
                    print(f"   {description}")
                elif phase in ["install_deps", "init_git", "configure_pytorch"]:
                    print(f"   {description}")
                elif phase == "copy_workflows":
                    print("\n📝 Setting up workflows...")
                elif phase == "sync_nodes":
                    print("\n📦 Syncing custom nodes...")
                elif phase == "resolve_models":
                    print(f"\n🔄 {description}")
                else:
                    emoji = emoji_map.get(phase, "")
                    print(f"\n{emoji} {description}" if emoji else f"\n{description}")

            def on_dependency_group_start(self, group_name: str, is_optional: bool):
                """Show which dependency group is being installed."""
                optional_marker = " (optional)" if is_optional else ""
                print(f"      Installing {group_name}{optional_marker}...", end="", flush=True)

            def on_dependency_group_complete(self, group_name: str, success: bool, error: str | None = None):
                """Mark group as succeeded or failed."""
                if success:
                    print(" ✓")
                    self.dep_group_successes.append(group_name)
                else:
                    print(" ✗")
                    self.dep_group_failures.append((group_name, error or "Unknown error"))

            def on_workflow_copied(self, workflow_name: str):
                print(f"   Copied: {workflow_name}")

            def on_node_installed(self, node_name: str):
                print(f"   Installed: {node_name}")

            def on_workflow_resolved(self, workflow_name: str, downloads: int):
                print(f"   • {workflow_name}", end="")
                if downloads:
                    print(f" (downloaded {downloads} models)")
                else:
                    print()

            def on_error(self, error: str):
                print(f"   ⚠️  {error}")

            def on_download_failures(self, failures: list[tuple[str, str]]):
                if not failures:
                    return

                print(f"\n⚠️  {len(failures)} model(s) failed to download:")
                for workflow_name, model_name in failures:
                    print(f"   • {model_name} (from {workflow_name})")

                print("\nModels are saved as download intents - you can download them later with:")
                print("   cg workflow resolve <workflow>")
                print("\nIf you see 401 Unauthorized errors, add your Civitai API key:")
                print("   cg config --civitai-key <your-token>")

            def on_download_batch_start(self, count: int):
                """Show batch download start."""
                print(f"\n⬇️  Downloading {count} model(s)...")

            def on_download_file_start(self, name: str, idx: int, total: int):
                """Show individual file download start."""
                print(f"\n[{idx}/{total}] {name}")

            def on_download_file_progress(self, downloaded: int, total: int | None):
                """Show download progress bar."""
                downloaded_mb = downloaded / (1024 * 1024)
                if total:
                    total_mb = total / (1024 * 1024)
                    pct = (downloaded / total) * 100
                    print(f"\rDownloading... {downloaded_mb:.1f} MB / {total_mb:.1f} MB ({pct:.0f}%)", end='', flush=True)
                else:
                    print(f"\rDownloading... {downloaded_mb:.1f} MB", end='', flush=True)

            def on_download_file_complete(self, name: str, success: bool, error: str | None):
                """Show file download completion."""
                if success:
                    print("  ✓ Complete")
                else:
                    print(f"  ✗ Failed: {error}")

            def on_download_batch_complete(self, success: int, total: int):
                """Show batch download completion."""
                if success == total:
                    print(f"\n✅ Downloaded {total} model(s)")
                elif success > 0:
                    print(f"\n⚠️  Downloaded {success}/{total} models (some failed)")
                else:
                    print(f"\n❌ All downloads failed (0/{total})")

        callbacks_instance = CLIImportCallbacks()

        try:
            if is_git:
                env = workspace.import_from_git(
                    git_url=args.path,
                    name=env_name,
                    model_strategy=strategy,
                    branch=getattr(args, 'branch', None),
                    callbacks=callbacks_instance,
                    torch_backend=args.torch_backend,
                    no_manager=getattr(args, "no_manager", False),
                )
            else:
                env = workspace.import_environment(
                    tarball_path=Path(args.path),
                    name=env_name,
                    model_strategy=strategy,
                    callbacks=callbacks_instance,
                    torch_backend=args.torch_backend,
                    no_manager=getattr(args, "no_manager", False),
                )

            print(f"\n✅ Import complete: {env.name}")

            # Show dependency group summary if any failed
            if callbacks_instance.dep_group_failures:
                print("\n⚠️  Some optional dependency groups failed to install:")
                for group_name, _error in callbacks_instance.dep_group_failures:
                    print(f"   ✗ {group_name}")
                print("\nSome functionality may be degraded or some nodes may not work properly.")
                print("The environment will still function with reduced capabilities.")
            else:
                print("   Environment ready to use!")

            # Set as active if --use flag provided
            if hasattr(args, 'use') and args.use:
                workspace.set_active_environment(env.name)
                print(f"   '{env.name}' set as active environment")
            else:
                print(f"\nActivate with: cg use {env_name}")

        except Exception as e:
            print(f"\n✗ Import failed: {e}")
            sys.exit(1)

        sys.exit(0)

    @with_workspace_logging("export")
    def export_env(self, args: argparse.Namespace) -> None:
        """Export a ComfyGit environment to a package."""
        from datetime import datetime
        from pathlib import Path

        # Get active environment or from -e flag
        try:
            if hasattr(args, 'target_env') and args.target_env:
                env = self.workspace.get_environment(args.target_env)
            else:
                env = self.workspace.get_active_environment()
                if not env:
                    print("✗ No active environment. Use: cg use <name>")
                    print("   Or specify with: cg -e <name> export")
                    sys.exit(1)
        except Exception as e:
            print(f"✗ Error getting environment: {e}")
            sys.exit(1)

        # Determine output path
        if args.path:
            output_path = Path(args.path)
        else:
            # Default: <env_name>_export_<date>.tar.gz in current directory
            timestamp = datetime.now().strftime("%Y%m%d")
            output_path = Path.cwd() / f"{env.name}_export_{timestamp}.tar.gz"

        print(f"📦 Exporting environment: {env.name}")
        print()

        from comfygit_core.services.environment_readiness import build_environment_readiness

        readiness = build_environment_readiness(env, include_blocking=True)
        blocking_issues = [
            issue
            for issue in readiness.blocking_issues
            if issue.type != "unresolved_issues" or not args.allow_issues
        ]

        if blocking_issues:
            print("✗ Export blocked:")
            for issue in blocking_issues:
                print(f"  • {issue.message}")
                if issue.details:
                    for detail in issue.details:
                        print(f"    - {detail}")

            issue_types = {issue.type for issue in blocking_issues}
            if "uncommitted_workflows" in issue_types or "uncommitted_git_changes" in issue_types:
                print("\n💡 Commit first:")
                print("   cg commit -m 'Pre-export checkpoint'")
            if "unresolved_issues" in issue_types:
                print("\n💡 Resolve workflow issues first:")
                print("   cg workflow resolve <workflow_name>")
                print("   Or export anyway with: cg export --allow-issues")
            sys.exit(1)

        warnings = readiness.warnings
        warning_count = (
            len(warnings.models_without_sources)
            + len(warnings.nodes_without_provenance)
        )

        if warning_count > 0 and not args.allow_issues:
            print("⚠️  Export reproducibility warnings:")
            print(f"\n{warning_count} dependency detail(s) are missing.\n")

            if warnings.models_without_sources:
                print("Models without download sources:")
                for warning in warnings.models_without_sources[:3]:
                    print(f"  • {warning.filename}")
                    if warning.workflows:
                        workflows_str = ", ".join(warning.workflows)
                        print(f"    Used by: {workflows_str}")
                remaining = len(warnings.models_without_sources) - 3
                if remaining > 0:
                    print(f"  ... and {remaining} more model(s)")

            if warnings.nodes_without_provenance:
                if warnings.models_without_sources:
                    print()
                print("Custom nodes without portable source metadata:")
                for warning in warnings.nodes_without_provenance[:3]:
                    print(f"  • {warning.name} ({warning.source}, {warning.criticality})")
                    print(f"    {warning.reason}")
                remaining = len(warnings.nodes_without_provenance) - 3
                if remaining > 0:
                    print(f"  ... and {remaining} more node(s)")

            print("\n⚠️  Another machine or ComfyGit Cloud may not rebuild this exactly.")
            print("   Add model sources or mark local-only development nodes optional.")

            response = input("\nContinue export? (y/N): ").strip().lower()
            if response != "y":
                print("\n✗ Export cancelled")
                sys.exit(1)

        try:
            tarball_path = env.export_environment(
                output_path,
                callbacks=None,
                allow_issues=args.allow_issues,
            )

            size_mb = tarball_path.stat().st_size / (1024 * 1024)
            print(f"\n✅ Export complete: {tarball_path.name} ({size_mb:.1f} MB)")
            print("\nShare this file to distribute your complete environment!")

        except Exception as e:
            # Handle CDExportError with rich context
            from comfygit_core.models.exceptions import CDExportError

            if isinstance(e, CDExportError):
                print(f"✗ {str(e)}")

                # Show context-specific details
                if e.context:
                    if e.context.uncommitted_workflows:
                        print("\n📋 Uncommitted workflows:")
                        for wf in e.context.uncommitted_workflows:
                            print(f"  • {wf}")
                        print("\n💡 Commit first:")
                        print("   cg commit -m 'Pre-export checkpoint'")
                    elif e.context.uncommitted_git_changes:
                        print("\n💡 Commit git changes first:")
                        print("   cg commit -m 'Pre-export checkpoint'")
                    elif e.context.has_unresolved_issues:
                        print("\n💡 Resolve workflow issues first:")
                        print("   cg workflow resolve <workflow_name>")
                sys.exit(1)

            # Generic error handling
            print(f"✗ Export failed: {e}")
            sys.exit(1)

        sys.exit(0)

    # === Model Management Commands ===

    @with_workspace_logging("model index list")
    def model_index_list(self, args: argparse.Namespace) -> None:
        """List all indexed models."""
        from collections import defaultdict
        from pathlib import Path

        from comfygit_core.utils.common import format_size

        logger.info("Listing all indexed models")

        try:
            # Get all models from the index
            models = self.workspace.list_models()

            logger.info(f"Retrieved {len(models)} models from index")

            if not models:
                print("📦 All indexed models:")
                print("   No models found")
                print("   Run 'cg model index dir <path>' to set your models directory")
                return

            # Group models by hash to find duplicates
            grouped = defaultdict(lambda: {'model': None, 'paths': []})
            for model in models:
                grouped[model.hash]['model'] = model
                if model.base_directory:
                    full_path = Path(model.base_directory) / model.relative_path
                else:
                    full_path = Path(model.relative_path)
                grouped[model.hash]['paths'].append(full_path)

            # Filter to duplicates if requested
            if args.duplicates:
                grouped = {h: g for h, g in grouped.items() if len(g['paths']) > 1}
                if not grouped:
                    print("📦 No duplicate models found")
                    print("   All models exist in a single location")
                    return

            # Convert to list for pagination
            results = list(grouped.values())

            # Define how to render a single model
            def render_model(group):
                model = group['model']
                paths = group['paths']
                size_str = format_size(model.file_size)
                print(f"\n   {model.filename}")
                print(f"   Size: {size_str}")
                print(f"   Hash: {model.hash[:12]}...")
                if len(paths) == 1:
                    print(f"   Path: {paths[0]}")
                else:
                    print(f"   Locations ({len(paths)}):")
                    for path in paths:
                        print(f"     • {path}")

            # Build header
            stats = self.workspace.get_model_stats()
            total_models = stats.get('total_models', 0)
            total_locations = stats.get('total_locations', 0)

            if args.duplicates:
                duplicate_count = len(results)
                duplicate_files = sum(len(g['paths']) for g in results)
                header = f"📦 Duplicate models ({duplicate_count} models, {duplicate_files} files):"
            else:
                header = f"📦 All indexed models ({total_models} unique, {total_locations} files):"

            paginate(results, render_model, page_size=5, header=header)

        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            print(f"✗ Failed to list models: {e}", file=sys.stderr)
            sys.exit(1)

    @with_workspace_logging("model index find")
    def model_index_find(self, args: argparse.Namespace) -> None:
        """Search for models by hash or filename."""
        from comfygit_core.utils.common import format_size

        query = args.query
        logger.info(f"Searching models for query: '{query}'")

        try:
            # Search for models
            results = self.workspace.search_models(query)

            logger.info(f"Found {len(results)} models matching query")

            if not results:
                print(f"No models found matching: {query}")
                return

            # Group models by hash (same file in different locations)
            from collections import defaultdict
            from pathlib import Path
            from typing import Any

            grouped: defaultdict[str, dict[str, Any]] = defaultdict(lambda: {'model': None, 'paths': []})
            for model in results:
                grouped[model.hash]['model'] = model
                if model.base_directory:
                    full_path = Path(model.base_directory) / model.relative_path
                else:
                    full_path = Path(model.relative_path)
                grouped[model.hash]['paths'].append(full_path)

            # Convert to list for pagination
            grouped_results = list(grouped.values())

            # Define how to render a single model with all its locations
            def render_model(group):
                model = group['model']
                paths = group['paths']
                size_str = format_size(model.file_size)
                print(f"\n   {model.filename}")
                print(f"   Size: {size_str}")
                print(f"   Hash: {model.hash}")
                if len(paths) == 1:
                    print(f"   Location: {paths[0]}")
                else:
                    print(f"   Locations ({len(paths)}):")
                    for path in paths:
                        print(f"     • {path}")

            # Use pagination for results
            unique_count = len(grouped_results)
            total_count = len(results)
            if unique_count == total_count:
                header = f"🔍 Found {unique_count} model(s) matching '{query}':"
            else:
                header = f"🔍 Found {unique_count} unique model(s) ({total_count} locations) matching '{query}':"
            paginate(grouped_results, render_model, page_size=5, header=header)

        except Exception as e:
            logger.error(f"Model search failed for query '{query}': {e}")
            print(f"✗ Search failed: {e}", file=sys.stderr)
            sys.exit(1)

    @with_workspace_logging("model index show")
    def model_index_show(self, args: argparse.Namespace) -> None:
        """Show detailed information about a specific model."""
        from datetime import datetime

        from comfygit_core.utils.common import format_size

        identifier = args.identifier
        logger.info(f"Showing details for model: '{identifier}'")

        try:
            details = self.workspace.get_model_details(identifier)
            model = details.model
            sources = details.sources
            locations = details.all_locations

            # Display detailed information
            print(f"📦 Model Details: {model.filename}\n")

            # Core identification
            print(f"  Hash:           {model.hash}")
            print(f"  Blake3:         {model.blake3_hash or 'Not computed'}")
            print(f"  SHA256:         {model.sha256_hash or 'Not computed'}")
            print(f"  Size:           {format_size(model.file_size)}")
            print(f"  Category:       {model.category}")

            # Timestamps
            first_seen = datetime.fromtimestamp(model.last_seen).strftime("%Y-%m-%d %H:%M:%S")
            print(f"  Last Seen:      {first_seen}")

            # Locations
            print(f"\n  Locations ({len(locations)}):")
            for loc in locations:
                from pathlib import Path
                mtime = datetime.fromtimestamp(loc['mtime']).strftime("%Y-%m-%d %H:%M:%S")
                if loc.get('base_directory'):
                    full_path = Path(loc['base_directory']) / loc['relative_path']
                    print(f"    • {full_path}")
                else:
                    print(f"    • {loc['relative_path']}")
                print(f"      Modified: {mtime}")

            # Sources
            if sources:
                print(f"\n  Sources ({len(sources)}):")
                for source in sources:
                    print(f"    • {source['type'].title()}")
                    print(f"      URL: {source['url']}")
                    if source['metadata']:
                        for key, value in source['metadata'].items():
                            print(f"      {key}: {value}")
                    added = datetime.fromtimestamp(source['added_time']).strftime("%Y-%m-%d %H:%M:%S")
                    print(f"      Added: {added}")
            else:
                print("\n  Sources: None")
                print(f"    Add with: cg model add-source {model.hash[:12]}")

            # Metadata (if any)
            if model.metadata:
                print("\n  Metadata:")
                for key, value in model.metadata.items():
                    print(f"    {key}: {value}")

        except KeyError:
            print(f"No model found matching: {identifier}")
        except ValueError:
            # Handle ambiguous matches - group by hash to show unique models
            from collections import defaultdict
            results = self.workspace.search_models(identifier)

            grouped = defaultdict(list)
            for model in results:
                grouped[model.hash].append(model)

            print(f"Multiple models found matching '{identifier}':\n")
            for idx, (hash_val, models) in enumerate(grouped.items(), 1):
                model = models[0]  # Use first for display
                location_count = f" ({len(models)} locations)" if len(models) > 1 else ""
                print(f"  {idx}. {model.filename}{location_count}")
                print(f"      Hash: {hash_val[:12]}...")
                print(f"      Path: {model.relative_path}")

            print("\nUse more specific identifier:")
            first_model = list(grouped.values())[0][0]
            print(f"  Full hash: cg model index show {first_model.hash}")
            print(f"  Filename: cg model index show {first_model.filename}")
        except Exception as e:
            logger.error(f"Failed to show model details for '{identifier}': {e}")
            print(f"✗ Failed to show model: {e}", file=sys.stderr)
            sys.exit(1)

    # === Model Directory Commands ===

    # === Registry Commands ===

    @with_workspace_logging("registry status")
    def registry_status(self, args: argparse.Namespace) -> None:
        """Show registry cache status."""
        try:
            info = self.workspace.get_registry_info()

            if not info['exists']:
                print("✗ No registry data cached")
                print("   Run 'cg index registry update' to fetch")
                return

            print("📦 Registry Cache Status:")
            print(f"   Path: {info['path']}")
            print(f"   Age: {info['age_hours']} hours")
            print(f"   Stale: {'Yes' if info['stale'] else 'No'} (>24 hours)")
            if info['version']:
                print(f"   Version: {info['version']}")

        except Exception as e:
            logger.error(f"Failed to get registry status: {e}")
            print(f"✗ Failed to get registry status: {e}", file=sys.stderr)
            sys.exit(1)

    @with_workspace_logging("registry update")
    def registry_update(self, args: argparse.Namespace) -> None:
        """Update registry data from GitHub."""
        try:
            print("🔄 Updating registry data from GitHub...")

            success = self.workspace.update_registry_data()

            if success:
                info = self.workspace.get_registry_info()
                print("✓ Registry data updated successfully")
                if info['version']:
                    print(f"   Version: {info['version']}")
            else:
                print("✗ Failed to update registry data")
                print("   Using existing cache if available")

        except Exception as e:
            logger.error(f"Failed to update registry: {e}")
            print(f"✗ Failed to update registry: {e}", file=sys.stderr)
            sys.exit(1)

    @with_workspace_logging("model index dir")
    def model_dir_add(self, args: argparse.Namespace) -> None:
        """Set the global models directory."""
        from comfygit_cli.utils.progress import create_model_sync_progress

        directory_path = args.path.resolve()
        logger.info(f"Setting models directory: {directory_path}")

        try:
            print(f"📁 Setting global models directory: {directory_path}")

            if not directory_path.exists():
                print(f"✗ Directory does not exist: {directory_path}")
                sys.exit(1)

            if not directory_path.is_dir():
                print(f"✗ Path is not a directory: {directory_path}")
                sys.exit(1)

            # Set the models directory and perform initial scan with progress
            progress = create_model_sync_progress()
            self.workspace.set_models_directory(directory_path, progress=progress)

            print(f"\n✓ Models directory set successfully: {directory_path}")
            print("   Use 'cg model index sync' to rescan when models change")

        except Exception as e:
            logger.error(f"Failed to set models directory '{directory_path}': {e}")
            print(f"✗ Failed to set models directory: {e}", file=sys.stderr)
            sys.exit(1)

    @with_workspace_logging("model index sync")
    def model_index_sync(self, args: argparse.Namespace) -> None:
        """Scan models directory and update index."""
        from comfygit_cli.utils.progress import create_model_sync_progress

        logger.info("Syncing models directory")

        try:
            progress = create_model_sync_progress()
            result = self.workspace.sync_model_directory(progress=progress)

            if result is None:
                print("✗ No models directory configured")
                print("   Run 'cg model index dir <path>' to set your models directory")
                return

            # Progress callback already handled display

        except Exception as e:
            logger.error(f"Failed to sync models: {e}")
            print(f"✗ Failed to sync: {e}", file=sys.stderr)
            sys.exit(1)

    @with_workspace_logging("model index status")
    def model_index_status(self, args: argparse.Namespace) -> None:
        """Show model index status and statistics."""
        logger.info("Getting model status")

        try:
            # Get models directory info
            models_dir = self.workspace.get_models_directory()

            # Get stats
            stats = self.workspace.get_model_stats()

            print("📊 Model Index Status:")
            print()

            if models_dir:
                exists = "✓" if models_dir.exists() else "✗"
                print(f"   Models Directory: {exists} {models_dir}")
            else:
                print("   Models Directory: Not configured")
                print("   Run 'cg model index dir <path>' to set your models directory")
                return

            total_models = stats.get('total_models', 0)
            total_locations = stats.get('total_locations', 0)
            print(f"   Total Models: {total_models} unique models")
            print(f"   Total Files: {total_locations} files indexed")

            if total_locations > total_models:
                duplicates = total_locations - total_models
                print(f"   Duplicates: {duplicates} duplicate files detected")

        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            print(f"✗ Failed to get status: {e}", file=sys.stderr)
            sys.exit(1)

    @with_workspace_logging("model download")
    def model_download(self, args: argparse.Namespace) -> None:
        """Download model from URL with interactive path confirmation."""
        from comfygit_core.services.model_downloader import DownloadRequest

        url = args.url
        logger.info(f"Downloading model from: {url}")

        try:
            # Get models directory
            models_dir = self.workspace.get_models_directory()
            downloader = self.workspace.model_downloader

            # Determine target path
            if args.path:
                # User specified explicit path
                suggested_path = Path(args.path)
            elif args.category:
                # User specified category - extract filename from URL
                filename = downloader._extract_filename(url, None)
                suggested_path = Path(args.category) / filename
            else:
                # Auto-suggest based on URL/filename
                suggested_path = downloader.suggest_path(url, node_type=None, filename_hint=None)

            # Path confirmation loop (unless --yes)
            while not args.yes:
                print(f"\n📥 Downloading from: {url}")
                print(f"   Model will be saved to: {suggested_path}")
                print("\n   [Y] Continue  [m] Change path  [c] Cancel")

                choice = input("Choice [Y]/m/c: ").strip().lower()

                if choice == 'c':
                    print("✗ Download cancelled")
                    return
                elif choice == 'm':
                    new_path = input("\nEnter path (relative to models dir): ").strip()
                    if new_path:
                        suggested_path = Path(new_path)
                        continue  # Show menu again with updated path
                    else:
                        print("✗ Download cancelled")
                        return
                elif choice in ['y', '']:
                    break  # Confirmed, proceed to download
                else:
                    print("Invalid choice. Please enter Y, m, or c.")

            # Create download request
            target_path = models_dir / suggested_path
            request = DownloadRequest(
                url=url,
                target_path=target_path,
                workflow_name=None
            )

            # Download with progress callback
            print(f"\n📥 Downloading to: {suggested_path}")
            progress_callback = create_progress_callback()
            result = downloader.download(request, progress_callback=progress_callback)
            print()  # New line after progress

            # Handle result
            if not result.success:
                print(f"✗ Download failed: {result.error}")

                # Show Civitai auth help if needed
                if "civitai.com" in url.lower() and result.error and (
                    "401" in str(result.error) or "unauthorized" in str(result.error).lower()
                ):
                    show_civitai_auth_help()

                sys.exit(1)

            # Success - show stats
            if result.model:
                print()
                show_download_stats(result.model)
                logger.info(f"Successfully downloaded model to {result.model.relative_path}")
            else:
                print("✓ Download complete")

        except Exception as e:
            logger.error(f"Model download failed: {e}")
            print(f"✗ Download failed: {e}", file=sys.stderr)
            sys.exit(1)

    # === Model Source Management ===

    @with_workspace_logging("model add-source")
    def model_add_source(self, args: argparse.Namespace) -> None:
        """Add download source URLs to models."""
        env = self.workspace.get_active_environment()

        # Mode detection: direct vs interactive
        if args.model and args.url:
            # Direct mode
            self._add_source_direct(env, args.model, args.url)
        else:
            # Interactive mode
            self._add_source_interactive(env)

    def _add_source_direct(self, env, identifier: str, url: str):
        """Direct mode: add source to specific model."""
        result = env.add_model_source(identifier, url)

        if result.success:
            print(f"✓ Added source to {result.model.filename}")
            print(f"  {url}")
        else:
            # Handle errors
            if result.error == "model_not_found":
                print(f"✗ Model not found: {identifier}", file=sys.stderr)
                print("\nHint: Use hash prefix or exact filename", file=sys.stderr)
                sys.exit(1)

            elif result.error == "ambiguous_filename":
                print(f"✗ Multiple models match '{identifier}':", file=sys.stderr)
                for match in result.matches:
                    print(f"  • {match.relative_path} ({match.hash[:8]}...)", file=sys.stderr)
                print(f"\nUse full hash: cg model add-source <hash> {url}", file=sys.stderr)
                sys.exit(1)

            elif result.error == "url_exists":
                print(f"✗ URL already exists for {result.model.filename}", file=sys.stderr)
                sys.exit(1)

    def _add_source_interactive(self, env):
        """Interactive mode: go through all models without sources."""
        statuses = env.get_models_without_sources()

        if not statuses:
            print("✓ All models have download sources!")
            return

        print("\n📦 Add Model Sources\n")
        print(f"Found {len(statuses)} model(s) without download sources\n")

        added_count = 0
        skipped_count = 0

        for idx, status in enumerate(statuses, 1):
            model = status.model
            available = status.available_locally

            # Show model info
            print(f"[{idx}/{len(statuses)}] {model.filename}")
            print(f"  Hash: {model.hash[:16]}...")
            print(f"  Path: {model.relative_path}")

            # Show availability status
            if available:
                print("  Status: ✓ Available locally")
            else:
                print("  Status: ✗ Not in local index (phantom reference)")

            # Prompt for URL
            url = input("\n  URL (or 's' to skip, 'q' to quit): ").strip()
            print()

            if url.lower() == 'q':
                print("⊗ Cancelled\n")
                break
            elif url.lower() == 's' or not url:
                skipped_count += 1
                continue
            else:
                # Add source
                result = env.add_model_source(model.hash, url)

                if result.success:
                    print("  ✓ Added source\n")
                    added_count += 1
                else:
                    # Should not happen in this flow, but handle gracefully
                    print(f"  ✗ Failed to add source: {result.error}\n", file=sys.stderr)

        # Summary
        print(f"✅ Complete: {added_count}/{len(statuses)} source(s) added")

        if added_count > 0:
            print("\nYour environment is now more shareable!")
            print("  Run 'cg export' to bundle and distribute")

    # === Config Management ===

    @with_workspace_logging("config")
    def config(self, args: argparse.Namespace) -> None:
        """Manage ComfyGit configuration settings."""
        # Flag mode - direct operations
        if hasattr(args, 'civitai_key') and args.civitai_key is not None:
            self._set_civitai_key(args.civitai_key)
            return

        if hasattr(args, 'uv_cache') and args.uv_cache is not None:
            self._set_uv_cache(args.uv_cache)
            return

        if hasattr(args, 'show') and args.show:
            self._show_config()
            return

        # Interactive mode - no flags provided
        self._interactive_config()

    def _set_civitai_key(self, key: str):
        """Set Civitai API key."""
        if key == "":
            self.workspace.workspace_config_manager.set_civitai_token(None)
            print("✓ Civitai API key cleared")
        else:
            self.workspace.workspace_config_manager.set_civitai_token(key)
            print("✓ Civitai API key saved")

    def _set_uv_cache(self, path_str: str):
        """Set external UV cache path."""
        from pathlib import Path

        if path_str == "":
            self.workspace.workspace_config_manager.set_external_uv_cache(None)
            print("✓ External UV cache cleared (using workspace-local cache)")
        else:
            path = Path(path_str).expanduser().resolve()
            if not path.exists():
                print(f"Error: Path does not exist: {path}")
                return
            if not path.is_dir():
                print(f"Error: Path is not a directory: {path}")
                return
            self.workspace.workspace_config_manager.set_external_uv_cache(path)
            print(f"✓ External UV cache set to: {path}")

    def _show_config(self):
        """Display current configuration."""
        print("ComfyGit Configuration:\n")

        # Workspace path
        print(f"  Workspace Path:  {self.workspace.paths.root}")

        # Civitai API Key
        token = self.workspace.workspace_config_manager.get_civitai_token()
        if token:
            # Mask key showing last 4 chars
            masked = f"••••••••{token[-4:]}" if len(token) > 4 else "••••"
            print(f"  Civitai API Key: {masked}")
        else:
            print("  Civitai API Key: Not set")

        # External UV cache
        uv_cache = self.workspace.workspace_config_manager.get_external_uv_cache()
        if uv_cache:
            print(f"  UV Cache:        {uv_cache}")
        else:
            print("  UV Cache:        Workspace-local (default)")

    def _interactive_config(self):
        """Interactive configuration menu."""
        while True:
            # Get current config
            civitai_token = self.workspace.workspace_config_manager.get_civitai_token()

            # Display menu
            print("\nComfyGit Configuration\n")

            # Civitai key status
            if civitai_token:
                masked = f"••••••••{civitai_token[-4:]}" if len(civitai_token) > 4 else "••••"
                print(f"  1. Civitai API Key: {masked}")
            else:
                print("  1. Civitai API Key: Not set")

            # Options
            print("\n  [1] Change setting  [c] Clear a setting  [q] Quit")
            choice = input("Choice: ").strip().lower()

            if choice == 'q':
                break
            elif choice == '1':
                self._interactive_set_civitai_key()
            elif choice == 'c':
                self._interactive_clear_setting()
            else:
                print("  Invalid choice")

    def _interactive_set_civitai_key(self):
        """Interactive Civitai API key setup."""
        print("\n🔑 Civitai API Key Setup")
        print("   Get your key from: https://civitai.com/user/account")

        key = input("\nEnter API key (or blank to cancel): ").strip()
        if not key:
            print("  Cancelled")
            return

        self.workspace.workspace_config_manager.set_civitai_token(key)
        print("✓ API key saved")

    def _interactive_clear_setting(self):
        """Clear a configuration setting."""
        print("\nClear which setting?")
        print("  1. Civitai API Key")
        print("\n  [1] Clear setting  [c] Cancel")

        choice = input("Choice: ").strip().lower()

        if choice == "1":
            self.workspace.workspace_config_manager.set_civitai_token(None)
            print("✓ Civitai API key cleared")
        elif choice == "c" or choice == "":
            print("  Cancelled")
        else:
            print("  Invalid choice")

    # === Orchestrator Management ===

    def orch_status(self, args: argparse.Namespace) -> None:
        """Show orchestrator status."""
        from .utils.orchestrator import (
            format_uptime,
            get_orchestrator_uptime,
            is_orchestrator_running,
            read_switch_status,
        )

        metadata_dir = self.workspace.path / ".metadata"

        # Check orchestrator status
        is_running, pid = is_orchestrator_running(metadata_dir)

        if args.json:
            # JSON output mode
            import json
            status_data = {
                "running": is_running,
                "pid": pid,
            }

            if is_running:
                uptime = get_orchestrator_uptime(metadata_dir, pid)
                if uptime:
                    status_data["uptime_seconds"] = int(uptime)

                # Check switch status
                switch_status = read_switch_status(metadata_dir)
                if switch_status:
                    status_data["switch"] = switch_status

            print(json.dumps(status_data, indent=2))
            return

        # Human-readable output
        print("\nOrchestrator Status")
        print("━" * 70)

        if not is_running:
            if pid:
                print(f"Running:        No (stale PID {pid})")
            else:
                print("Running:        No")
            print("\nOrchestrator is not running.")
            print("Start ComfyUI to launch the orchestrator automatically.")
            print("━" * 70)
            return

        print(f"Running:        Yes (PID {pid})")

        # Show uptime
        uptime = get_orchestrator_uptime(metadata_dir, pid)
        if uptime:
            print(f"Uptime:         {format_uptime(uptime)}")

        # Show control port
        control_port_file = metadata_dir / ".control_port"
        if control_port_file.exists():
            try:
                port = control_port_file.read_text().strip()
                print(f"Control Port:   {port}")
            except OSError:
                pass

        # Check switch status
        switch_status = read_switch_status(metadata_dir)
        if switch_status:
            state = switch_status.get("state", "unknown")
            progress = switch_status.get("progress", 0)
            message = switch_status.get("message", "")
            target_env = switch_status.get("target_env", "")
            source_env = switch_status.get("source_env", "")

            print(f"\nSwitch Status:  {state.replace('_', ' ').title()} ({progress}%)")
            if message:
                print(f"                {message}")
            if source_env:
                print(f"Source Env:     {source_env}")
            if target_env:
                print(f"Target Env:     {target_env}")
        else:
            print("\nSwitch Status:  Idle")

        print("━" * 70)

    def orch_restart(self, args: argparse.Namespace) -> None:
        """Request orchestrator to restart ComfyUI."""
        import time

        from .utils.orchestrator import is_orchestrator_running, safe_write_command

        metadata_dir = self.workspace.path / ".metadata"

        # Check if orchestrator is running
        is_running, pid = is_orchestrator_running(metadata_dir)

        if not is_running:
            print("✗ Orchestrator is not running")
            print("  Start ComfyUI to launch the orchestrator")
            sys.exit(1)

        # Send restart command
        print(f"✓ Sending restart command to orchestrator (PID {pid})")
        safe_write_command(metadata_dir, {
            "command": "restart",
            "timestamp": time.time()
        })

        print("  ComfyUI will restart within 500ms...")

        if args.wait:
            print("\n  Waiting for restart to complete...")
            time.sleep(2)  # Give orchestrator time to process

            # Wait for restart (check if PID changes or process restarts)
            for _ in range(30):  # 15 second timeout
                time.sleep(0.5)
                is_running, new_pid = is_orchestrator_running(metadata_dir)
                if is_running:
                    print(f"✓ Orchestrator restarted (PID {new_pid})")
                    return

            print("⚠️  Restart may still be in progress")

    def orch_kill(self, args: argparse.Namespace) -> None:
        """Shutdown orchestrator."""
        import time

        from .utils.orchestrator import (
            is_orchestrator_running,
            kill_orchestrator_process,
            read_switch_status,
            safe_write_command,
        )

        metadata_dir = self.workspace.path / ".metadata"

        # Check if orchestrator is running
        is_running, pid = is_orchestrator_running(metadata_dir)

        if not is_running:
            print("✗ Orchestrator is not running")
            if pid:
                print(f"  (stale PID file exists: {pid})")
            return

        # Check if mid-switch (warn user)
        switch_status = read_switch_status(metadata_dir)
        if switch_status:
            state = switch_status.get("state", "")
            if state not in ["complete", "failed", "aborted"]:
                print(f"⚠️  Orchestrator is currently switching environments (state: {state})")
                if not args.force:
                    response = input("   Shutdown anyway? [y/N]: ").strip().lower()
                    if response not in ['y', 'yes']:
                        print("✗ Shutdown cancelled")
                        return

        if args.force:
            # Force kill (SIGTERM then SIGKILL if needed)
            print(f"✓ Force killing orchestrator (PID {pid})")
            # Sends SIGTERM, waits 3s for cleanup, then SIGKILL if still alive
            kill_orchestrator_process(pid, force=False)
            print("✓ Orchestrator terminated")
            print("\nNote: ComfyUI should have been shut down gracefully.")
            print("  If still running, check with: ps aux | grep 'ComfyUI/main.py'")
        else:
            # Graceful shutdown via command
            print(f"✓ Sending shutdown command to orchestrator (PID {pid})")
            safe_write_command(metadata_dir, {
                "command": "shutdown",
                "timestamp": time.time()
            })
            print("  Orchestrator will exit within 500ms...")

            # Wait for shutdown
            time.sleep(1)
            is_running, _ = is_orchestrator_running(metadata_dir)
            if not is_running:
                print("✓ Orchestrator shut down")
            else:
                print("⚠️  Orchestrator may still be shutting down")

    def orch_clean(self, args: argparse.Namespace) -> None:
        """Clean orchestrator state files."""
        from .utils.orchestrator import (
            cleanup_orchestrator_state,
            is_orchestrator_running,
            kill_orchestrator_process,
        )

        metadata_dir = self.workspace.path / ".metadata"

        # Check if orchestrator is running
        is_running, pid = is_orchestrator_running(metadata_dir)

        # Show what will be cleaned
        files_to_show = [
            ".orchestrator.pid",
            ".control_port",
            ".cmd",
            ".switch_request.json",
            ".switch_status.json",
            ".switch.lock",
            ".startup_state.json",
            ".cmd.tmp.* (temp files)"
        ]

        if args.dry_run:
            print("\n🧹 Files that would be cleaned:")
            for filename in files_to_show:
                filepath = metadata_dir / filename.split()[0]
                if '*' in filename or filepath.exists():
                    print(f"  • {filename}")
            print("\nNote: workspace_config.json will be preserved")
            return

        # Confirm if orchestrator is running
        if is_running and not args.force:
            print(f"⚠️  Warning: Orchestrator is currently running (PID {pid})")
            print("\nThis will forcefully clean orchestrator state.")
            print("Files to remove:")
            for filename in files_to_show:
                print(f"  • {filename}")
            print("\nNote: workspace_config.json will be preserved")

            if args.kill:
                print("\n⚠️  --kill flag: Will also terminate orchestrator process")

            response = input("\nContinue? [y/N]: ").strip().lower()
            if response not in ['y', 'yes']:
                print("✗ Cleaning cancelled")
                return

        # Kill orchestrator if requested
        if is_running and args.kill:
            print(f"\n✓ Terminating orchestrator process {pid}")
            print("  (giving it a chance to shut down ComfyUI gracefully...)")
            # Use force=False to send SIGTERM first, allowing cleanup handlers to run
            # Will still SIGKILL after 3s if process doesn't exit
            kill_orchestrator_process(pid, force=False)

        # Clean up state files
        print("\n🧹 Cleaning orchestrator state...")
        removed = cleanup_orchestrator_state(metadata_dir, preserve_config=True)

        if removed:
            for filename in removed:
                print(f"  ✓ Removed {filename}")
            print(f"\n✓ Cleaned {len(removed)} file(s)")
        else:
            print("  No files to clean")

        print("\n✓ Orchestrator state cleaned")

        # Helpful next steps
        if args.kill:
            print("\nNote: If ComfyUI is still running, you can find it with:")
            print("  ps aux | grep 'ComfyUI/main.py'")
            print("\nOr restart fresh with:")
            print("  cg -e <env> run")
        else:
            print("\nYou can now:")
            print("  • Run ComfyUI manually from an environment directory")
            print("  • Start new orchestrator via ComfyUI startup")

    def orch_logs(self, args: argparse.Namespace) -> None:
        """Show orchestrator logs."""
        from .utils.orchestrator import follow_log_file, tail_log_file

        metadata_dir = self.workspace.path / ".metadata"
        log_file = metadata_dir / "orchestrator.log"

        if not log_file.exists():
            print("✗ No orchestrator log file found")
            print(f"  Expected: {log_file}")
            return

        if args.follow:
            print(f"Following {log_file} (Ctrl+C to stop)\n")
            try:
                follow_log_file(log_file)
            except KeyboardInterrupt:
                print()
        else:
            lines = tail_log_file(log_file, args.lines)
            if lines:
                print("".join(lines))
            else:
                print("(empty log file)")

    # === Workspace Management ===

    @with_workspace_logging("workspace cleanup")
    def workspace_cleanup(self, args: argparse.Namespace) -> None:
        """Clean up legacy workspace artifacts.

        Removes .metadata/system_nodes/ directory if no environments
        still use legacy symlinked manager.
        """
        force = getattr(args, 'force', False)

        result = self.workspace.cleanup_legacy_system_nodes(force=force)

        if result.success:
            print(f"Removed {result.removed_path}")
        else:
            if result.legacy_environments:
                print("Cannot cleanup: Some environments still use legacy manager")
                for env in result.legacy_environments:
                    print(f"  {env}")
                print("\nRun 'cg -e <ENV> manager update' to migrate, then retry.")
            else:
                print(f"{result.message}")
