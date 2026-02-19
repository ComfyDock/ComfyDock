"""ComfyGit MVP CLI - Workspace and Environment Management."""
# PYTHON_ARGCOMPLETE_OK

import argparse
import sys
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import argcomplete

from .completers import (
    branch_completer,
    commit_hash_completer,
    environment_completer,
    installed_node_completer,
    ref_completer,
    workflow_completer,
)
from .completion_commands import CompletionCommands
from .env_commands import EnvironmentCommands
from .global_commands import GlobalCommands
from .logging.logging_config import setup_logging
from .update_commands import UpdateCommands
from .utils.update_notice import maybe_print_update_notice, start_update_check_async


def _make_help_func(parser: argparse.ArgumentParser) -> Callable[[argparse.Namespace], None]:
    """Create a function that prints parser help and exits."""
    def show_help(args: argparse.Namespace) -> None:
        parser.print_help()
        sys.exit(1)
    return show_help

try:
    __version__ = version("comfygit")
except PackageNotFoundError:
    __version__ = "unknown"


def _get_comfygit_config_dir() -> Path:
    """Get ComfyGit config directory (creates if needed)."""
    config_dir = Path.home() / ".config" / "comfygit"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def _check_for_old_docker_installation() -> None:
    """Warn once about old Docker-based ComfyDock installation."""
    old_config = Path.home() / ".comfydock" / "environments.json"
    if not old_config.exists():
        return  # No old Docker installation detected

    # Check if we've already shown this warning
    warning_flag = _get_comfygit_config_dir() / ".docker_warning_shown"
    if warning_flag.exists():
        return  # Already warned user

    # Show warning (compact, informative)
    print("\n" + "="*70)
    print("ℹ️  OLD DOCKER-BASED COMFYDOCK DETECTED")
    print("="*70)
    print("\nYou have an old Docker-based ComfyDock (v0.3.x) at ~/.comfydock")
    print("This is the NEW ComfyGit v1.0+ (UV-based).")
    print("\nKey differences:")
    print("  • Old version: Docker containers, 'comfydock' command")
    print("  • New version: UV packages, 'comfygit' command")
    print("\nBoth versions can coexist. Your old environments are unchanged.")
    print("\nTo use old version: pip install comfydock==0.1.6")
    print("To use new version: cg init")
    print("\nMigration guide: https://github.com/comfyhub-org/comfygit/blob/main/MIGRATION.md")
    print("="*70 + "\n")

    # Mark warning as shown
    warning_flag.touch()


def main() -> None:
    """Main entry point for ComfyGit CLI."""
    # Enable readline for input() line editing (arrow keys, history)
    # Unix/Linux/macOS: provides full editing capability
    # Windows: gracefully falls back to native console editing
    try:
        import readline  # noqa: F401
    except ImportError:
        pass

    # Check for old Docker installation (show warning once)
    _check_for_old_docker_installation()

    # Initialize logging system with minimal console output
    # Environment commands will add file handlers as needed
    setup_logging(level="INFO", simple_format=True, console_level="CRITICAL")

    # Special handling for 'run' command to pass through ComfyUI args
    parser = create_parser()
    if 'run' in sys.argv:
        # Parse known args, pass unknown to ComfyUI
        args, unknown = parser.parse_known_args()
        if getattr(args, 'command', None) == 'run':
            if unknown and unknown[0] == "--":
                unknown = unknown[1:]
            args.args = unknown
        else:
            # Not actually the run command, do normal parsing
            args = parser.parse_args()
    else:
        # Normal parsing for all other commands
        args = parser.parse_args()

    if not hasattr(args, 'func'):
        parser.print_help()
        sys.exit(1)

    update_handle = start_update_check_async(args)

    try:
        # Execute the command
        args.func(args)
        maybe_print_update_notice(update_handle)
    except KeyboardInterrupt:
        print("\n✗ Interrupted")
        sys.exit(130)
    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser with hierarchical command structure."""
    parser = argparse.ArgumentParser(
        description="ComfyGit - Manage ComfyUI workspaces and environments",
        prog="cg"
    )

    # Global options
    parser.add_argument(
        '--version',
        action='version',
        version=f'ComfyGit CLI v{__version__}',
        help='Show version and exit'
    )
    parser.add_argument(
        '-e', '--env',
        help='Target environment (uses active if not specified)',
        dest='target_env'
    ).completer = environment_completer  # type: ignore[attr-defined]
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output'
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Add all commands (workspace and environment)
    _add_global_commands(subparsers)
    _add_env_commands(subparsers)

    # Enable argcomplete for tab completion
    argcomplete.autocomplete(parser)

    return parser


def _add_global_commands(subparsers: argparse._SubParsersAction) -> None:
    """Add global workspace-level commands."""
    global_cmds = GlobalCommands()
    update_cmds = UpdateCommands()

    # init - Initialize workspace
    init_parser = subparsers.add_parser("init", help="Initialize ComfyGit workspace")
    init_parser.add_argument("path", type=Path, nargs="?", help="Workspace directory (default: ~/comfygit)")
    init_parser.add_argument("--models-dir", type=Path, help="Path to existing models directory to index")
    init_parser.add_argument("--yes", "-y", action="store_true", help="Use all defaults, no interactive prompts")
    init_parser.set_defaults(func=global_cmds.init)

    # list - List all environments
    list_parser = subparsers.add_parser("list", help="List all environments")
    list_parser.set_defaults(func=global_cmds.list_envs)

    # update - Update ComfyGit CLI (self-update)
    update_parser = subparsers.add_parser("update", help="Update ComfyGit CLI")
    update_parser.add_argument("--check", action="store_true", help="Check for updates without upgrading")
    update_parser.set_defaults(func=update_cmds.update)

    # migrate - Import existing ComfyUI
    # migrate_parser = subparsers.add_parser("migrate", help="Scan and import existing ComfyUI instance")
    # migrate_parser.add_argument("source_path", type=Path, help="Path to existing ComfyUI")
    # migrate_parser.add_argument("env_name", help="New environment name")
    # migrate_parser.add_argument("--scan-only", action="store_true", help="Only scan, don't import")
    # migrate_parser.set_defaults(func=global_cmds.migrate)

    # import - Import ComfyGit environment
    import_parser = subparsers.add_parser("import", help="Import ComfyGit environment from tarball or git repository")
    import_parser.add_argument("path", type=str, nargs="?", help="Path to .tar.gz file or git repository URL (use #subdirectory for subdirectory imports)")
    import_parser.add_argument("--name", type=str, help="Name for imported environment (skip prompt)")
    import_parser.add_argument("--branch", "-b", type=str, help="Git branch, tag, or commit to import (git imports only)")
    import_parser.add_argument(
        "--torch-backend",
        default="auto",
        metavar="BACKEND",
        help=(
            "PyTorch backend. Examples: auto (detect GPU), cpu, "
            "cu128 (CUDA 12.8), cu126, cu124, rocm6.3 (AMD), xpu (Intel). "
            "Default: auto"
        ),
    )
    import_parser.add_argument(
        "--no-manager",
        action="store_true",
        help="Skip comfygit-manager installation (headless/API-only mode)",
    )
    import_parser.add_argument("--use", action="store_true", help="Set imported environment as active")
    import_parser.add_argument(
        "--models",
        choices=["all", "required", "skip"],
        help="Model download strategy: all (default with --yes), required only, or skip"
    )
    import_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts, use defaults for workspace initialization")
    import_parser.set_defaults(func=global_cmds.import_env)

    # export - Export ComfyGit environment
    export_parser = subparsers.add_parser("export", help="Export ComfyGit environment (include relevant files from .cec)")
    export_parser.add_argument("path", type=Path, nargs="?", help="Path to output file")
    export_parser.add_argument("--allow-issues", action="store_true", help="Export even with unresolved workflows or models without source URLs")
    export_parser.set_defaults(func=global_cmds.export_env)

    # Model management subcommands
    model_parser = subparsers.add_parser("model", help="Manage model index")
    model_subparsers = model_parser.add_subparsers(dest="model_command", help="Model commands")
    model_parser.set_defaults(func=_make_help_func(model_parser))

    # model index subcommands
    model_index_parser = model_subparsers.add_parser("index", help="Model index operations")
    model_index_subparsers = model_index_parser.add_subparsers(dest="model_index_command", help="Model index commands")
    model_index_parser.set_defaults(func=_make_help_func(model_index_parser))

    # model index find
    model_index_find_parser = model_index_subparsers.add_parser("find", help="Find models by hash or filename")
    model_index_find_parser.add_argument("query", help="Search query (hash prefix or filename)")
    model_index_find_parser.set_defaults(func=global_cmds.model_index_find)

    # model index list
    model_index_list_parser = model_index_subparsers.add_parser("list", help="List all indexed models")
    model_index_list_parser.add_argument("--duplicates", action="store_true", help="Show only models with multiple locations")
    model_index_list_parser.set_defaults(func=global_cmds.model_index_list)

    # model index show
    model_index_show_parser = model_index_subparsers.add_parser("show", help="Show detailed model information")
    model_index_show_parser.add_argument("identifier", help="Model hash, hash prefix, filename, or path")
    model_index_show_parser.set_defaults(func=global_cmds.model_index_show)

    # model index status
    model_index_status_parser = model_index_subparsers.add_parser("status", help="Show models directory and index status")
    model_index_status_parser.set_defaults(func=global_cmds.model_index_status)

    # model index sync
    model_index_sync_parser = model_index_subparsers.add_parser("sync", help="Scan models directory and update index")
    model_index_sync_parser.set_defaults(func=global_cmds.model_index_sync)

    # model index dir
    model_index_dir_parser = model_index_subparsers.add_parser("dir", help="Set global models directory to index")
    model_index_dir_parser.add_argument("path", type=Path, help="Path to models directory")
    model_index_dir_parser.set_defaults(func=global_cmds.model_dir_add)

    # model download
    model_download_parser = model_subparsers.add_parser("download", help="Download model from URL")
    model_download_parser.add_argument("url", help="Model download URL (Civitai, HuggingFace, or direct)")
    model_download_parser.add_argument("--path", type=str, help="Target path relative to models directory (e.g., checkpoints/model.safetensors)")
    model_download_parser.add_argument("-c", "--category", type=str, help="Model category for auto-path (e.g., checkpoints, loras, vae)")
    model_download_parser.add_argument("-y", "--yes", action="store_true", help="Skip path confirmation prompt")
    model_download_parser.set_defaults(func=global_cmds.model_download)

    # model add-source
    model_add_source_parser = model_subparsers.add_parser("add-source", help="Add download source URL to model(s)")
    model_add_source_parser.add_argument("model", nargs="?", help="Model filename or hash (omit for interactive mode)")
    model_add_source_parser.add_argument("url", nargs="?", help="Download URL")
    model_add_source_parser.set_defaults(func=global_cmds.model_add_source)

    # Registry management subcommands
    registry_parser = subparsers.add_parser("registry", help="Manage node registry cache")
    registry_subparsers = registry_parser.add_subparsers(dest="registry_command", help="Registry commands")
    registry_parser.set_defaults(func=_make_help_func(registry_parser))

    # registry status
    registry_status_parser = registry_subparsers.add_parser("status", help="Show registry cache status")
    registry_status_parser.set_defaults(func=global_cmds.registry_status)

    # registry update
    registry_update_parser = registry_subparsers.add_parser("update", help="Update registry data from GitHub")
    registry_update_parser.set_defaults(func=global_cmds.registry_update)

    # Config management - now with subcommands
    config_parser = subparsers.add_parser("config", help="Manage configuration settings")
    config_parser.add_subparsers(dest="config_command", help="Configuration commands")

    # Legacy flags - still supported at root level for backward compatibility
    config_parser.add_argument("--civitai-key", type=str, help="Set Civitai API key (use empty string to clear)")
    config_parser.add_argument("--uv-cache", type=str, help="Set external UV cache path (use empty string to clear)")
    config_parser.add_argument("--show", action="store_true", help="Show current configuration")
    config_parser.set_defaults(func=global_cmds.config)

    # debug - Show application logs for debugging
    debug_parser = subparsers.add_parser("debug", help="Show application debug logs")
    debug_parser.add_argument("-n", "--lines", type=int, default=200, help="Number of lines to show (default: 200)")
    debug_parser.add_argument("--level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Filter by log level")
    debug_parser.add_argument("--full", action="store_true", help="Show all logs (no line limit)")
    debug_parser.add_argument("--workspace", action="store_true", help="Show workspace logs instead of environment logs")
    debug_parser.set_defaults(func=global_cmds.debug)

    # Shell completion management
    completion_cmds = CompletionCommands()
    completion_parser = subparsers.add_parser("completion", help="Manage shell tab completion")
    completion_subparsers = completion_parser.add_subparsers(dest="completion_command", help="Completion commands")
    completion_parser.set_defaults(func=_make_help_func(completion_parser))

    # completion install
    completion_install_parser = completion_subparsers.add_parser("install", help="Install tab completion for your shell")
    completion_install_parser.set_defaults(func=completion_cmds.install)

    # completion uninstall
    completion_uninstall_parser = completion_subparsers.add_parser("uninstall", help="Remove tab completion from your shell")
    completion_uninstall_parser.set_defaults(func=completion_cmds.uninstall)

    # completion status
    completion_status_parser = completion_subparsers.add_parser("status", help="Show tab completion installation status")
    completion_status_parser.set_defaults(func=completion_cmds.status)

    # Orchestrator management subcommands
    orch_parser = subparsers.add_parser(
        "orch",
        aliases=["orchestrator"],
        help="Monitor and control orchestrator"
    )
    orch_subparsers = orch_parser.add_subparsers(
        dest="orch_command",
        help="Orchestrator commands"
    )
    orch_parser.set_defaults(func=_make_help_func(orch_parser))

    # orch status
    orch_status_parser = orch_subparsers.add_parser("status", help="Show orchestrator status")
    orch_status_parser.add_argument("--json", action="store_true", help="Output as JSON")
    orch_status_parser.set_defaults(func=global_cmds.orch_status)

    # orch restart
    orch_restart_parser = orch_subparsers.add_parser("restart", help="Restart ComfyUI")
    orch_restart_parser.add_argument("--wait", action="store_true", help="Wait for restart to complete")
    orch_restart_parser.set_defaults(func=global_cmds.orch_restart)

    # orch kill
    orch_kill_parser = orch_subparsers.add_parser("kill", help="Shutdown orchestrator")
    orch_kill_parser.add_argument("--force", action="store_true", help="Force kill (bypass command queue)")
    orch_kill_parser.set_defaults(func=global_cmds.orch_kill)

    # orch clean
    orch_clean_parser = orch_subparsers.add_parser("clean", help="Clean orchestrator state")
    orch_clean_parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    orch_clean_parser.add_argument("--force", action="store_true", help="Skip confirmation")
    orch_clean_parser.add_argument("--kill", action="store_true", help="Also kill orchestrator process")
    orch_clean_parser.set_defaults(func=global_cmds.orch_clean)

    # orch logs
    orch_logs_parser = orch_subparsers.add_parser("logs", help="Show orchestrator logs")
    orch_logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow logs in real-time")
    orch_logs_parser.add_argument("-n", "--lines", type=int, default=50, help="Number of lines to show (default: 50)")
    orch_logs_parser.set_defaults(func=global_cmds.orch_logs)

    # Workspace management subcommands
    workspace_parser = subparsers.add_parser("workspace", help="Workspace operations")
    workspace_subparsers = workspace_parser.add_subparsers(
        dest="workspace_command",
        help="Workspace commands"
    )
    workspace_parser.set_defaults(func=_make_help_func(workspace_parser))

    # workspace cleanup
    workspace_cleanup_parser = workspace_subparsers.add_parser(
        "cleanup",
        help="Remove legacy workspace artifacts"
    )
    workspace_cleanup_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip verification and force cleanup"
    )
    workspace_cleanup_parser.set_defaults(func=global_cmds.workspace_cleanup)


def _add_env_commands(subparsers: argparse._SubParsersAction) -> None:
    """Add environment-specific commands."""
    env_cmds = EnvironmentCommands()

    # Environment Management Commands (operate ON environments)

    # create - Create new environment
    create_parser = subparsers.add_parser("create", help="Create new environment")
    create_parser.add_argument("name", help="Environment name (letters, numbers, hyphens, underscores, dots)")
    create_parser.add_argument("--template", type=Path, help="Template manifest")
    create_parser.add_argument("--python", default="3.11", help="Python version")
    create_parser.add_argument("--comfyui", help="ComfyUI version")
    create_parser.add_argument(
        "--torch-backend",
        default="auto",
        metavar="BACKEND",
        help=(
            "PyTorch backend. Examples: auto (detect GPU), cpu, "
            "cu128 (CUDA 12.8), cu126, cu124, rocm6.3 (AMD), xpu (Intel). "
            "Default: auto"
        ),
    )
    create_parser.add_argument(
        "--no-manager",
        action="store_true",
        help="Skip comfygit-manager installation (headless/API-only mode)",
    )
    create_parser.add_argument("--use", action="store_true", help="Set active environment after creation")
    create_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts, use defaults for workspace initialization")
    create_parser.set_defaults(func=env_cmds.create)

    # use - Set active environment
    use_parser = subparsers.add_parser("use", help="Set active environment")
    use_parser.add_argument("name", help="Environment name").completer = environment_completer  # type: ignore[attr-defined]
    use_parser.set_defaults(func=env_cmds.use)

    # delete - Delete environment
    delete_parser = subparsers.add_parser("delete", help="Delete environment")
    delete_parser.add_argument("name", help="Environment name").completer = environment_completer  # type: ignore[attr-defined]
    delete_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    delete_parser.set_defaults(func=env_cmds.delete)

    # Environment Operation Commands (operate IN environments, require -e or active)

    # env-config - Environment-scoped configuration (requires -e or active env)
    env_config_parser = subparsers.add_parser("env-config", help="Manage environment-specific configuration")
    env_config_subparsers = env_config_parser.add_subparsers(dest="env_config_command", help="Environment config commands")
    env_config_parser.set_defaults(func=_make_help_func(env_config_parser))

    # env-config torch-backend - Manage PyTorch backend for this environment
    env_config_torch_parser = env_config_subparsers.add_parser("torch-backend", help="Manage PyTorch backend settings")
    env_config_torch_subparsers = env_config_torch_parser.add_subparsers(dest="torch_command", help="PyTorch backend commands")
    env_config_torch_parser.set_defaults(func=_make_help_func(env_config_torch_parser))

    # env-config torch-backend show
    env_config_torch_show_parser = env_config_torch_subparsers.add_parser("show", help="Show current PyTorch backend")
    env_config_torch_show_parser.set_defaults(func=env_cmds.env_config_torch_show)

    # env-config torch-backend set <backend>
    env_config_torch_set_parser = env_config_torch_subparsers.add_parser("set", help="Set PyTorch backend")
    env_config_torch_set_parser.add_argument("backend", help="Backend to set (e.g., cu128, cpu, rocm6.3, xpu)")
    env_config_torch_set_parser.set_defaults(func=env_cmds.env_config_torch_set)

    # env-config torch-backend detect
    env_config_torch_detect_parser = env_config_torch_subparsers.add_parser("detect", help="Auto-detect and show recommended backend")
    env_config_torch_detect_parser.set_defaults(func=env_cmds.env_config_torch_detect)

    # env-config extras - Manage default optional extras for sync
    env_config_extras_parser = env_config_subparsers.add_parser(
        "extras",
        help="Manage default optional extras for sync"
    )
    env_config_extras_subparsers = env_config_extras_parser.add_subparsers(
        dest="extras_command",
        help="Extras commands"
    )
    env_config_extras_parser.set_defaults(func=_make_help_func(env_config_extras_parser))

    # env-config extras show
    env_config_extras_show_parser = env_config_extras_subparsers.add_parser(
        "show", help="Show default sync extras"
    )
    env_config_extras_show_parser.set_defaults(func=env_cmds.env_config_extras_show)

    # env-config extras add <extra>
    env_config_extras_add_parser = env_config_extras_subparsers.add_parser(
        "add", help="Add a default sync extra"
    )
    env_config_extras_add_parser.add_argument("extras", nargs="+", help="Extra name(s) to add")
    env_config_extras_add_parser.set_defaults(func=env_cmds.env_config_extras_add)

    # env-config extras remove <extra>
    env_config_extras_remove_parser = env_config_extras_subparsers.add_parser(
        "remove", help="Remove a default sync extra"
    )
    env_config_extras_remove_parser.add_argument("extras", nargs="+", help="Extra name(s) to remove")
    env_config_extras_remove_parser.set_defaults(func=env_cmds.env_config_extras_remove)

    # overlay - Manage overlays for this environment
    overlay_parser = subparsers.add_parser("overlay", help="Manage dependency overlays")
    overlay_subparsers = overlay_parser.add_subparsers(dest="overlay_command", help="Overlay commands")
    overlay_parser.set_defaults(func=_make_help_func(overlay_parser))

    overlay_list_parser = overlay_subparsers.add_parser("list", help="List available overlays")
    overlay_list_parser.set_defaults(func=env_cmds.overlay_list)

    overlay_show_parser = overlay_subparsers.add_parser("show", help="Show overlay file contents")
    overlay_show_parser.add_argument("name", help="Overlay name")
    overlay_show_parser.set_defaults(func=env_cmds.overlay_show)

    overlay_enable_parser = overlay_subparsers.add_parser("enable", help="Enable overlay for this machine")
    overlay_enable_parser.add_argument("name", help="Overlay name")
    overlay_enable_parser.set_defaults(func=env_cmds.overlay_enable)

    overlay_disable_parser = overlay_subparsers.add_parser("disable", help="Disable overlay for this machine")
    overlay_disable_parser.add_argument("name", help="Overlay name")
    overlay_disable_parser.set_defaults(func=env_cmds.overlay_disable)

    overlay_create_parser = overlay_subparsers.add_parser("create", help="Create overlay template")
    overlay_create_parser.add_argument("name", help="Overlay name")
    overlay_create_parser.set_defaults(func=env_cmds.overlay_create)

    # run - Run ComfyUI (special handling for ComfyUI args)
    run_parser = subparsers.add_parser("run", help="Run ComfyUI")
    run_parser.add_argument("--no-sync", action="store_true", help="Skip environment sync before running")
    run_parser.add_argument(
        "--torch-backend",
        default=None,
        metavar="BACKEND",
        help=(
            "PyTorch backend override (one-time, not saved). Examples: cpu, "
            "cu128 (CUDA 12.8), cu126, cu124, rocm6.3 (AMD), xpu (Intel). "
            "Reads from .pytorch-backend file if not specified."
        ),
    )
    run_parser.add_argument(
        "--extra",
        action="append",
        help="Install optional dependency extra (can be repeated)"
    )
    run_parser.add_argument(
        "--all-extras",
        action="store_true",
        help="Install all optional dependency extras"
    )
    run_parser.add_argument(
        "--overlay",
        action="append",
        help="Apply overlay for this run sync (can be repeated)",
    )
    run_parser.set_defaults(func=env_cmds.run, args=[])

    # status - Show environment status
    status_parser = subparsers.add_parser("status", help="Show status (both sync and git status)")
    status_parser.add_argument("-v", "--verbose", action="store_true", help="Show full details")
    status_parser.set_defaults(func=env_cmds.status)

    # manifest - Show environment manifest
    manifest_parser = subparsers.add_parser("manifest", help="Show environment manifest (pyproject.toml)")
    manifest_parser.add_argument("--pretty", action="store_true", help="Output as YAML instead of TOML")
    manifest_parser.add_argument("--section", type=str, help="Show specific section (e.g., tool.comfygit.nodes)")
    manifest_parser.add_argument("--ide", nargs="?", const="auto", metavar="CMD", help="Open in editor (uses $EDITOR if no command given)")
    manifest_parser.set_defaults(func=env_cmds.manifest)

    # repair - Repair environment drift (manual edits or git operations)
    repair_parser = subparsers.add_parser("repair", help="Repair environment to match pyproject.toml")
    repair_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    repair_parser.add_argument(
        "--models",
        choices=["all", "required", "skip"],
        default="all",
        help="Model download strategy: all (default), required only, or skip"
    )
    repair_parser.set_defaults(func=env_cmds.repair)

    # doctor - Diagnose and repair core tooling (uv) in the environment venv
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Diagnose and repair environment tooling (uv)",
    )
    doctor_parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check; do not attempt repairs",
    )
    doctor_parser.set_defaults(func=env_cmds.doctor)

    # sync - Sync environment (packages, nodes, models)
    sync_parser = subparsers.add_parser("sync", help="Sync environment packages and dependencies")
    sync_parser.add_argument(
        "--torch-backend",
        default=None,
        metavar="BACKEND",
        help=(
            "PyTorch backend override (one-time, not saved). Examples: cpu, "
            "cu128 (CUDA 12.8), cu126, cu124, rocm6.3 (AMD), xpu (Intel). "
            "Reads from .pytorch-backend file if not specified."
        ),
    )
    sync_parser.add_argument(
        "--extra",
        action="append",
        help="Install optional dependency extra (can be repeated)"
    )
    sync_parser.add_argument(
        "--all-extras",
        action="store_true",
        help="Install all optional dependency extras"
    )
    sync_parser.add_argument(
        "--overlay",
        action="append",
        help="Apply overlay for this sync only (can be repeated)",
    )
    sync_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show full UV output during sync"
    )
    sync_parser.set_defaults(func=env_cmds.sync)

    # log - Show commit history
    log_parser = subparsers.add_parser("log", help="Show commit history")
    log_parser.add_argument("-n", "--limit", type=int, default=20, metavar="N", help="Number of commits to show (default: 20)")
    log_parser.add_argument("-v", "--verbose", action="store_true", help="Show full details")
    log_parser.set_defaults(func=env_cmds.log)

    # commit - Save environment changes
    commit_parser = subparsers.add_parser("commit", help="Commit environment changes")
    commit_parser.add_argument("-m", "--message", help="Commit message (auto-generated if not provided)")
    commit_parser.add_argument("--auto", action="store_true", help="Auto-resolve issues without interaction")
    commit_parser.add_argument("--allow-issues", action="store_true", help="Allow committing workflows with unresolved issues")
    commit_parser.add_argument("-y", "--yes", action="store_true", help="Skip detached HEAD warning (allow commit anyway)")
    commit_parser.set_defaults(func=env_cmds.commit)

    # checkout - Move HEAD without committing
    checkout_parser = subparsers.add_parser("checkout", help="Checkout commits, branches, or files")
    checkout_parser.add_argument("ref", nargs="?", help="Commit, branch, or tag to checkout (defaults to HEAD when using -b)").completer = ref_completer  # type: ignore[attr-defined]
    checkout_parser.add_argument("-b", "--branch", help="Create new branch and switch to it")
    checkout_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation for uncommitted changes")
    checkout_parser.add_argument("--force", action="store_true", help="Force checkout, discarding uncommitted changes")
    checkout_parser.set_defaults(func=env_cmds.checkout)

    # branch - Manage branches
    branch_parser = subparsers.add_parser("branch", help="List, create, or delete branches")
    branch_parser.add_argument("name", nargs="?", help="Branch name (list all if omitted)").completer = branch_completer  # type: ignore[attr-defined]
    branch_parser.add_argument("-d", "--delete", action="store_true", help="Delete branch")
    branch_parser.add_argument("-D", "--force-delete", action="store_true", help="Force delete branch (even if unmerged)")
    branch_parser.set_defaults(func=env_cmds.branch)

    # switch - Switch branches
    switch_parser = subparsers.add_parser("switch", help="Switch to a branch")
    switch_parser.add_argument("branch", help="Branch name to switch to").completer = branch_completer  # type: ignore[attr-defined]
    switch_parser.add_argument("-c", "--create", action="store_true", help="Create branch if it doesn't exist")
    switch_parser.set_defaults(func=env_cmds.switch)

    # reset - Reset current HEAD to ref
    reset_parser = subparsers.add_parser("reset", help="Reset current HEAD to specified state")
    reset_parser.add_argument("ref", nargs="?", default="HEAD", help="Commit to reset to (default: HEAD)").completer = commit_hash_completer  # type: ignore[attr-defined]
    reset_parser.add_argument("--hard", action="store_true", help="Discard all changes (hard reset)")
    reset_parser.add_argument("--mixed", action="store_true", help="Keep changes in working tree, unstage (default)")
    reset_parser.add_argument("--soft", action="store_true", help="Keep changes staged")
    reset_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    reset_parser.set_defaults(func=env_cmds.reset_git)

    # merge - Merge branches
    merge_parser = subparsers.add_parser("merge", help="Merge branch into current")
    merge_parser.add_argument("branch", help="Branch to merge")
    merge_parser.add_argument("-m", "--message", help="Merge commit message")
    merge_parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview changes without applying (read-only diff with conflict detection)"
    )
    merge_parser.add_argument(
        "--auto-resolve",
        choices=["mine", "theirs"],
        help="Auto-resolve conflicts: 'mine' keeps local, 'theirs' takes incoming"
    )
    merge_parser.set_defaults(func=env_cmds.merge)

    # revert - Revert commits
    revert_parser = subparsers.add_parser("revert", help="Create new commit that undoes previous commit")
    revert_parser.add_argument("commit", help="Commit to revert")
    revert_parser.set_defaults(func=env_cmds.revert)

    # pull - Pull from remote and sync
    pull_parser = subparsers.add_parser(
        "pull",
        help="Pull changes from remote and repair environment"
    )
    pull_parser.add_argument(
        "-r", "--remote",
        default="origin",
        help="Git remote name (default: origin)"
    )
    pull_parser.add_argument(
        "-b", "--branch",
        default=None,
        help="Remote branch to pull (default: current local branch). Use when remote has different default branch (e.g., master vs main)"
    )
    pull_parser.add_argument(
        "--models",
        choices=["all", "required", "skip"],
        default="all",
        help="Model download strategy (default: all)"
    )
    pull_parser.add_argument(
        "--force",
        action="store_true",
        help="Discard uncommitted changes and force pull"
    )
    pull_parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview changes without applying (read-only fetch and diff)"
    )
    pull_parser.add_argument(
        "--auto-resolve",
        choices=["mine", "theirs"],
        help="Auto-resolve conflicts: 'mine' keeps local, 'theirs' takes incoming"
    )
    pull_parser.add_argument(
        "--torch-backend",
        default=None,
        metavar="BACKEND",
        help=(
            "PyTorch backend override (one-time, not saved). Examples: cpu, "
            "cu128 (CUDA 12.8), cu126, cu124, rocm6.3 (AMD), xpu (Intel). "
            "Reads from .pytorch-backend file if not specified."
        ),
    )
    pull_parser.set_defaults(func=env_cmds.pull)

    # push - Push commits to remote
    push_parser = subparsers.add_parser(
        "push",
        help="Push committed changes to remote"
    )
    push_parser.add_argument(
        "-r", "--remote",
        default="origin",
        help="Git remote name (default: origin)"
    )
    push_parser.add_argument(
        "--force",
        action="store_true",
        help="Force push using --force-with-lease (overwrite remote)"
    )
    push_parser.set_defaults(func=env_cmds.push)

    # remote - Manage git remotes
    remote_parser = subparsers.add_parser(
        "remote",
        help="Manage git remotes"
    )
    remote_subparsers = remote_parser.add_subparsers(
        dest="remote_command",
        help="Remote commands"
    )
    remote_parser.set_defaults(func=_make_help_func(remote_parser))

    # remote add
    remote_add_parser = remote_subparsers.add_parser(
        "add",
        help="Add a git remote"
    )
    remote_add_parser.add_argument(
        "name",
        help="Remote name (e.g., origin)"
    )
    remote_add_parser.add_argument(
        "url",
        help="Remote URL"
    )
    remote_add_parser.set_defaults(func=env_cmds.remote)

    # remote remove
    remote_remove_parser = remote_subparsers.add_parser(
        "remove",
        help="Remove a git remote"
    )
    remote_remove_parser.add_argument(
        "name",
        help="Remote name to remove"
    )
    remote_remove_parser.set_defaults(func=env_cmds.remote)

    # remote list
    remote_list_parser = remote_subparsers.add_parser(
        "list",
        help="List all git remotes"
    )
    remote_list_parser.set_defaults(func=env_cmds.remote)

    # Node management subcommands
    node_parser = subparsers.add_parser("node", help="Manage custom nodes")
    node_subparsers = node_parser.add_subparsers(dest="node_command", help="Node commands")
    node_parser.set_defaults(func=_make_help_func(node_parser))

    # node add
    node_add_parser = node_subparsers.add_parser("add", help="Add custom node(s)")
    node_add_parser.add_argument("node_names", nargs="+", help="Node identifier(s): registry-id[@version], github-url[@ref], or directory name")
    node_add_parser.add_argument("--dev", action="store_true", help="Track existing local development node")
    node_add_parser.add_argument("--no-test", action="store_true", help="Don't test resolution")
    node_add_parser.add_argument("--force", action="store_true", help="Force overwrite existing directory")
    node_add_parser.add_argument("--verbose", "-v", action="store_true", help="Show full UV error output for dependency conflicts")
    node_add_parser.add_argument("--strict", action="store_true", help="Fail on dependency conflicts instead of auto-resolving")
    node_add_parser.add_argument(
        "--resolve-with-overlays",
        action="store_true",
        help="Resolve node install with all active overlays (default is pytorch-only)",
    )
    node_add_parser.add_argument(
        "--extra",
        action="append",
        help="Install optional dependency extra during sync (can be repeated)"
    )
    node_add_parser.add_argument(
        "--all-extras",
        action="store_true",
        help="Install all optional dependency extras during sync"
    )
    node_add_parser.set_defaults(func=env_cmds.node_add)

    # node remove
    node_remove_parser = node_subparsers.add_parser("remove", help="Remove custom node(s)")
    node_remove_parser.add_argument("node_names", nargs="+", help="Node registry ID(s) or name(s)").completer = installed_node_completer  # type: ignore[attr-defined]
    node_remove_parser.add_argument("--dev", action="store_true", help="Remove development node specifically")
    node_remove_parser.add_argument("--untrack", action="store_true", help="Only remove from tracking, leave filesystem unchanged")
    node_remove_parser.set_defaults(func=env_cmds.node_remove)

    # node prune
    node_prune_parser = node_subparsers.add_parser("prune", help="Remove unused custom nodes")
    node_prune_parser.add_argument("--exclude", nargs="+", metavar="PACKAGE", help="Package IDs to keep even if unused")
    node_prune_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    node_prune_parser.set_defaults(func=env_cmds.node_prune)

    # node list
    node_list_parser = node_subparsers.add_parser("list", help="List custom nodes")
    node_list_parser.set_defaults(func=env_cmds.node_list)

    # node update
    node_update_parser = node_subparsers.add_parser("update", help="Update custom node")
    node_update_parser.add_argument("node_name", help="Node identifier or name to update").completer = installed_node_completer  # type: ignore[attr-defined]
    node_update_parser.add_argument("-y", "--yes", action="store_true", help="Auto-confirm updates (skip prompts)")
    node_update_parser.add_argument("--no-test", action="store_true", help="Don't test resolution")
    node_update_parser.set_defaults(func=env_cmds.node_update)

    # Workflow management subcommands
    workflow_parser = subparsers.add_parser("workflow", help="Manage workflows")
    workflow_subparsers = workflow_parser.add_subparsers(dest="workflow_command", help="Workflow commands")
    workflow_parser.set_defaults(func=_make_help_func(workflow_parser))

    # workflow list
    workflow_list_parser = workflow_subparsers.add_parser("list", help="List all workflows with sync status")
    workflow_list_parser.set_defaults(func=env_cmds.workflow_list)

    # workflow resolve
    workflow_resolve_parser = workflow_subparsers.add_parser("resolve", help="Resolve workflow dependencies (nodes & models)")
    workflow_resolve_parser.add_argument("name", help="Workflow name to resolve").completer = workflow_completer  # type: ignore[attr-defined]
    workflow_resolve_parser.add_argument("--auto", action="store_true", help="Auto-resolve without interaction")
    workflow_resolve_parser.add_argument("--install", action="store_true", help="Auto-install missing nodes without prompting")
    workflow_resolve_parser.add_argument("--no-install", action="store_true", help="Skip node installation prompt")
    workflow_resolve_parser.set_defaults(func=env_cmds.workflow_resolve)

    # workflow model importance
    workflow_importance_parser = workflow_subparsers.add_parser(
        "model",
        help="Manage workflow models"
    )
    workflow_model_subparsers = workflow_importance_parser.add_subparsers(
        dest="model_command",
        help="Model management commands"
    )
    workflow_importance_parser.set_defaults(func=_make_help_func(workflow_importance_parser))

    importance_parser = workflow_model_subparsers.add_parser(
        "importance",
        help="Set model importance (required/flexible/optional)"
    )
    importance_parser.add_argument(
        "workflow_name",
        nargs="?",
        help="Workflow name (interactive if omitted)"
    ).completer = workflow_completer  # type: ignore[attr-defined]
    importance_parser.add_argument(
        "model_identifier",
        nargs="?",
        help="Model filename or hash (interactive if omitted)"
    )
    importance_parser.add_argument(
        "importance",
        nargs="?",
        choices=["required", "flexible", "optional"],
        help="Importance level"
    )
    importance_parser.set_defaults(func=env_cmds.workflow_model_importance)

    # Constraint management subcommands
    constraint_parser = subparsers.add_parser("constraint", help="Manage UV constraint dependencies")
    constraint_subparsers = constraint_parser.add_subparsers(dest="constraint_command", help="Constraint commands")
    constraint_parser.set_defaults(func=_make_help_func(constraint_parser))

    # constraint add
    constraint_add_parser = constraint_subparsers.add_parser("add", help="Add constraint dependencies")
    constraint_add_parser.add_argument("packages", nargs="+", help="Package specifications (e.g., torch==2.4.1)")
    constraint_add_parser.set_defaults(func=env_cmds.constraint_add)

    # constraint list
    constraint_list_parser = constraint_subparsers.add_parser("list", help="List constraint dependencies")
    constraint_list_parser.set_defaults(func=env_cmds.constraint_list)

    # constraint remove
    constraint_remove_parser = constraint_subparsers.add_parser("remove", help="Remove constraint dependencies")
    constraint_remove_parser.add_argument("packages", nargs="+", help="Package names to remove")
    constraint_remove_parser.set_defaults(func=env_cmds.constraint_remove)

    # Python dependency management subcommands
    py_parser = subparsers.add_parser("py", help="Manage Python dependencies")
    py_subparsers = py_parser.add_subparsers(dest="py_command", help="Python dependency commands")
    py_parser.set_defaults(func=_make_help_func(py_parser))

    # py add
    py_add_parser = py_subparsers.add_parser("add", help="Add Python dependencies")
    py_add_parser.add_argument("packages", nargs="*", help="Package specifications (e.g., requests>=2.0.0)")
    py_add_parser.add_argument("-r", "--requirements", type=Path, help="Add packages from requirements.txt file")
    py_add_parser.add_argument("--upgrade", action="store_true", help="Upgrade existing packages")
    # Tier 2: Power-user flags
    py_add_parser.add_argument("--group", help="Add to dependency group (e.g., optional-cuda)")
    py_add_parser.add_argument("--dev", action="store_true", help="Add to dev dependencies")
    py_add_parser.add_argument(
        "--optional",
        metavar="EXTRA",
        help="Add to optional dependency group (project.optional-dependencies)"
    )
    py_add_parser.add_argument("--editable", action="store_true", help="Install as editable (for local development)")
    py_add_parser.add_argument("--bounds", choices=["lower", "major", "minor", "exact"], help="Version specifier style")
    py_add_parser.add_argument(
        "--no-build-isolation",
        action="store_true",
        help="Build without isolation (for CUDA packages needing PyTorch at build time)"
    )
    py_add_parser.set_defaults(func=env_cmds.py_add)

    # py remove
    py_remove_parser = py_subparsers.add_parser("remove", help="Remove Python dependencies")
    py_remove_parser.add_argument("packages", nargs="+", help="Package names to remove")
    py_remove_parser.add_argument("--group", help="Remove packages from dependency group instead of main dependencies")
    py_remove_parser.set_defaults(func=env_cmds.py_remove)

    # py remove-group
    py_remove_group_parser = py_subparsers.add_parser("remove-group", help="Remove entire dependency group")
    py_remove_group_parser.add_argument("group", help="Dependency group name to remove")
    py_remove_group_parser.set_defaults(func=env_cmds.py_remove_group)

    # py list
    py_list_parser = py_subparsers.add_parser("list", help="List project dependencies")
    py_list_parser.add_argument("--all", action="store_true", help="Show all dependencies including dependency groups")
    py_list_parser.set_defaults(func=env_cmds.py_list)

    # py uv - Direct UV passthrough for advanced users
    py_uv_parser = py_subparsers.add_parser(
        "uv",
        help="Direct UV passthrough (advanced)",
        add_help=False  # Don't interfere with UV's --help
    )
    py_uv_parser.add_argument(
        "uv_args",
        nargs=argparse.REMAINDER,  # Capture everything after 'uv'
        help="UV command and arguments (e.g., 'add --group optional-cuda sageattention')"
    )
    py_uv_parser.set_defaults(func=env_cmds.py_uv)

    # Manager subcommands (per-environment comfygit-manager)
    manager_parser = subparsers.add_parser("manager", help="Manage comfygit-manager installation")
    manager_subparsers = manager_parser.add_subparsers(dest="manager_command", help="Manager commands")
    manager_parser.set_defaults(func=_make_help_func(manager_parser))

    # manager status
    manager_status_parser = manager_subparsers.add_parser("status", help="Show manager version and update availability")
    manager_status_parser.set_defaults(func=env_cmds.manager_status)

    # manager update
    manager_update_parser = manager_subparsers.add_parser("update", help="Update or migrate comfygit-manager")
    manager_update_parser.add_argument("--version", help="Target version (default: latest)")
    manager_update_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")
    manager_update_parser.set_defaults(func=env_cmds.manager_update)

    # Metadata subcommands (environment metadata management)
    metadata_parser = subparsers.add_parser("metadata", help="Manage environment metadata")
    metadata_subparsers = metadata_parser.add_subparsers(dest="metadata_command", help="Metadata commands")
    metadata_parser.set_defaults(func=_make_help_func(metadata_parser))

    # metadata refresh
    metadata_refresh_parser = metadata_subparsers.add_parser(
        "refresh",
        help="Refresh extracted metadata from ComfyUI installation"
    )
    metadata_refresh_parser.set_defaults(func=env_cmds.metadata_refresh)


if __name__ == "__main__":
    main()
