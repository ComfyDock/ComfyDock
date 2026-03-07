"""CLI entry point for comfygit-deploy.

Provides command-line interface for deploying ComfyUI environments
to cloud providers (RunPod) and self-hosted workers.
"""

import argparse
import sys

from . import __version__


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="cg-deploy",
        description="ComfyGit Deploy - Remote deployment and worker management",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # =========================================================================
    # RunPod commands
    # =========================================================================
    runpod_parser = subparsers.add_parser("runpod", help="RunPod operations")
    runpod_subparsers = runpod_parser.add_subparsers(
        dest="runpod_command", help="RunPod subcommands"
    )

    # runpod config
    config_parser = runpod_subparsers.add_parser("config", help="Configure RunPod API key")
    config_parser.add_argument("--api-key", help="Set RunPod API key")
    config_parser.add_argument("--show", action="store_true", help="Show current config")
    config_parser.add_argument("--clear", action="store_true", help="Clear stored API key")

    # runpod gpus
    gpus_parser = runpod_subparsers.add_parser("gpus", help="List available GPUs with pricing")
    gpus_parser.add_argument("--region", help="Filter by region/data center")

    # runpod volumes
    runpod_subparsers.add_parser("volumes", help="List network volumes")

    # runpod regions
    runpod_subparsers.add_parser("regions", help="List data centers")

    # runpod deploy
    deploy_parser = runpod_subparsers.add_parser("deploy", help="Deploy environment to RunPod")
    deploy_parser.add_argument("import_source", help="Git URL or local path to import")
    deploy_parser.add_argument("--gpu", required=True, help="GPU type (e.g., 'RTX 4090')")
    deploy_parser.add_argument("--volume", help="Network volume ID to attach")
    deploy_parser.add_argument("--name", help="Deployment name")
    deploy_parser.add_argument("--branch", "-b", help="Git branch/tag to use")
    deploy_parser.add_argument(
        "--cloud-type",
        choices=["SECURE", "COMMUNITY"],
        default="SECURE",
        help="Cloud type (default: SECURE)",
    )
    deploy_parser.add_argument(
        "--pricing-type",
        choices=["ON_DEMAND", "SPOT"],
        default="ON_DEMAND",
        help="Pricing type (default: ON_DEMAND)",
    )
    deploy_parser.add_argument("--spot-bid", type=float, help="Spot bid price (for SPOT pricing)")

    # =========================================================================
    # Instance commands
    # =========================================================================
    instances_parser = subparsers.add_parser("instances", help="List all instances")
    instances_parser.add_argument(
        "--provider",
        choices=["runpod", "custom"],
        help="Filter by provider",
    )
    instances_parser.add_argument(
        "--status",
        choices=["running", "stopped"],
        help="Filter by status",
    )
    instances_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # start
    start_parser = subparsers.add_parser("start", help="Start a stopped instance")
    start_parser.add_argument("instance_id", help="Instance ID to start")

    # stop
    stop_parser = subparsers.add_parser("stop", help="Stop a running instance")
    stop_parser.add_argument("instance_id", help="Instance ID to stop")

    # terminate
    terminate_parser = subparsers.add_parser("terminate", help="Terminate an instance")
    terminate_parser.add_argument("instance_id", help="Instance ID to terminate")
    terminate_parser.add_argument("--force", action="store_true", help="Force termination")
    terminate_parser.add_argument("--keep-env", action="store_true", help="Keep environment directory")

    # logs
    logs_parser = subparsers.add_parser("logs", help="View instance logs")
    logs_parser.add_argument("instance_id", help="Instance ID")
    logs_parser.add_argument("--follow", "-f", action="store_true", help="Follow log output")
    logs_parser.add_argument("--lines", "-n", type=int, default=100, help="Number of lines")

    # open
    open_parser = subparsers.add_parser("open", help="Open ComfyUI URL in browser")
    open_parser.add_argument("instance_id", help="Instance ID")

    # wait
    wait_parser = subparsers.add_parser("wait", help="Wait for instance to be ready")
    wait_parser.add_argument("instance_id", help="Instance ID")
    wait_parser.add_argument("--timeout", type=int, default=300, help="Timeout in seconds")

    # =========================================================================
    # Custom worker commands (Phase 2)
    # =========================================================================
    custom_parser = subparsers.add_parser("custom", help="Custom worker operations")
    custom_subparsers = custom_parser.add_subparsers(
        dest="custom_command", help="Custom worker subcommands"
    )

    # custom scan
    scan_parser = custom_subparsers.add_parser("scan", help="Scan for workers via mDNS")
    scan_parser.add_argument("--timeout", type=int, default=5, help="Scan timeout")

    # custom add
    add_parser = custom_subparsers.add_parser("add", help="Add a custom worker")
    add_parser.add_argument("name", help="Worker name")
    add_parser.add_argument("--host", help="Worker host/IP")
    add_parser.add_argument("--port", type=int, default=9090, help="Worker port")
    add_parser.add_argument("--api-key", help="Worker API key")
    add_parser.add_argument(
        "--discovered", action="store_true", help="Add from last scan results"
    )

    # custom remove
    remove_parser = custom_subparsers.add_parser("remove", help="Remove a custom worker")
    remove_parser.add_argument("name", help="Worker name")

    # custom list
    custom_subparsers.add_parser("list", help="List registered workers")

    # custom test
    test_parser = custom_subparsers.add_parser("test", help="Test worker connection")
    test_parser.add_argument("name", help="Worker name")

    # custom deploy
    custom_deploy_parser = custom_subparsers.add_parser(
        "deploy", help="Deploy to custom worker"
    )
    custom_deploy_parser.add_argument("worker_name", help="Worker to deploy to")
    custom_deploy_parser.add_argument("import_source", help="Git URL or local path")
    custom_deploy_parser.add_argument("--branch", "-b", help="Git branch/tag")
    custom_deploy_parser.add_argument(
        "--mode",
        choices=["docker", "native"],
        default="docker",
        help="Deployment mode",
    )
    custom_deploy_parser.add_argument("--name", help="Environment name")

    # =========================================================================
    # Worker commands (runs on GPU machine, Phase 2)
    # =========================================================================
    worker_parser = subparsers.add_parser("worker", help="Worker server management")
    worker_subparsers = worker_parser.add_subparsers(
        dest="worker_command", help="Worker subcommands"
    )

    # worker setup
    setup_parser = worker_subparsers.add_parser("setup", help="One-time worker setup")
    setup_parser.add_argument("--api-key", help="Set worker API key")
    setup_parser.add_argument("--workspace", help="Workspace path")

    # worker up
    up_parser = worker_subparsers.add_parser("up", help="Start worker server")
    up_parser.add_argument("--port", type=int, default=9090, help="Server port")
    up_parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    up_parser.add_argument(
        "--mode",
        choices=["docker", "native"],
        default="docker",
        help="Instance mode",
    )
    up_parser.add_argument("--broadcast", action="store_true", help="Enable mDNS broadcast")
    up_parser.add_argument("--port-range", default="8200:8210", help="Instance port range")
    up_parser.add_argument("--cloud", help="ComfyGit Cloud base URL or websocket URL")
    up_parser.add_argument("--token", help="Tunnel auth token for ComfyGit Cloud")
    up_parser.add_argument("--dev", action="store_true", help="Use saved dev config (from 'dev setup')")
    up_parser.add_argument("--dev-core", metavar="PATH", help="Use local comfygit-core (editable)")
    up_parser.add_argument("--dev-manager", metavar="PATH", help="Use local comfygit-manager")

    # worker down
    worker_subparsers.add_parser("down", help="Stop worker server")

    # worker status
    worker_subparsers.add_parser("status", help="Show worker status")

    # worker regenerate-key
    worker_subparsers.add_parser("regenerate-key", help="Regenerate API key")

    # =========================================================================
    # Dev commands (development mode setup)
    # =========================================================================
    dev_parser = subparsers.add_parser("dev", help="Development mode setup")
    dev_subparsers = dev_parser.add_subparsers(dest="dev_command", help="Dev subcommands")

    # dev setup
    dev_setup_parser = dev_subparsers.add_parser(
        "setup", help="Configure local dev paths for core/manager"
    )
    dev_setup_parser.add_argument("--core", metavar="PATH", help="Path to comfygit-core package")
    dev_setup_parser.add_argument("--manager", metavar="PATH", help="Path to comfygit-manager")
    dev_setup_parser.add_argument("--show", action="store_true", help="Show current dev config")
    dev_setup_parser.add_argument("--clear", action="store_true", help="Clear dev config")

    # dev patch
    dev_patch_parser = dev_subparsers.add_parser(
        "patch", help="Patch existing environments with dev config"
    )
    dev_patch_parser.add_argument("--env", help="Specific environment to patch (default: all)")

    # dev add-node
    dev_add_node_parser = dev_subparsers.add_parser(
        "add-node", help="Add a dev node to be symlinked into environments"
    )
    dev_add_node_parser.add_argument("name", help="Node directory name (e.g., ComfyUI-Async-API)")
    dev_add_node_parser.add_argument("path", help="Path to the node source directory")

    # dev remove-node
    dev_remove_node_parser = dev_subparsers.add_parser(
        "remove-node", help="Remove a dev node from config"
    )
    dev_remove_node_parser.add_argument("name", help="Node name to remove")

    # dev list-nodes
    dev_subparsers.add_parser("list-nodes", help="List configured dev nodes")

    return parser


def main(args: list[str] | None = None) -> int:
    """Main entry point for cg-deploy CLI.

    Args:
        args: Command-line arguments (uses sys.argv if None)

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    parser = create_parser()
    parsed = parser.parse_args(args)

    if not parsed.command:
        parser.print_help()
        return 0

    # Import command handlers
    from .commands import instances as instance_commands
    from .commands import runpod as runpod_commands

    # Dispatch to command handlers
    try:
        if parsed.command == "runpod":
            if not parsed.runpod_command:
                parser.parse_args(["runpod", "--help"])
                return 0
            handler_map = {
                "config": runpod_commands.handle_config,
                "gpus": runpod_commands.handle_gpus,
                "volumes": runpod_commands.handle_volumes,
                "regions": runpod_commands.handle_regions,
                "deploy": runpod_commands.handle_deploy,
            }
            handler = handler_map.get(parsed.runpod_command)
            if handler:
                return handler(parsed)
            print(f"Unknown runpod command: {parsed.runpod_command}")
            return 1

        elif parsed.command == "instances":
            return instance_commands.handle_instances(parsed)

        elif parsed.command == "start":
            return instance_commands.handle_start(parsed)

        elif parsed.command == "stop":
            return instance_commands.handle_stop(parsed)

        elif parsed.command == "terminate":
            return instance_commands.handle_terminate(parsed)

        elif parsed.command == "open":
            return instance_commands.handle_open(parsed)

        elif parsed.command == "wait":
            return instance_commands.handle_wait(parsed)

        elif parsed.command == "logs":
            return instance_commands.handle_logs(parsed)

        elif parsed.command == "worker":
            from .commands import worker as worker_commands

            if not parsed.worker_command:
                parser.parse_args(["worker", "--help"])
                return 0
            handler_map = {
                "setup": worker_commands.handle_setup,
                "up": worker_commands.handle_up,
                "down": worker_commands.handle_down,
                "status": worker_commands.handle_status,
                "regenerate-key": worker_commands.handle_regenerate_key,
            }
            handler = handler_map.get(parsed.worker_command)
            if handler:
                return handler(parsed)
            print(f"Unknown worker command: {parsed.worker_command}")
            return 1

        elif parsed.command == "custom":
            from .commands import custom as custom_commands

            if not parsed.custom_command:
                parser.parse_args(["custom", "--help"])
                return 0
            handler_map = {
                "scan": custom_commands.handle_scan,
                "add": custom_commands.handle_add,
                "remove": custom_commands.handle_remove,
                "list": custom_commands.handle_list,
                "test": custom_commands.handle_test,
                "deploy": custom_commands.handle_deploy,
            }
            handler = handler_map.get(parsed.custom_command)
            if handler:
                return handler(parsed)
            print(f"Unknown custom command: {parsed.custom_command}")
            return 1

        elif parsed.command == "dev":
            from .commands import dev as dev_commands

            if not parsed.dev_command:
                parser.parse_args(["dev", "--help"])
                return 0
            handler_map = {
                "setup": dev_commands.handle_setup,
                "patch": dev_commands.handle_patch,
                "add-node": dev_commands.handle_add_node,
                "remove-node": dev_commands.handle_remove_node,
                "list-nodes": dev_commands.handle_list_nodes,
            }
            handler = handler_map.get(parsed.dev_command)
            if handler:
                return handler(parsed)
            print(f"Unknown dev command: {parsed.dev_command}")
            return 1

        else:
            print(f"Unknown command: {parsed.command}")
            return 1

    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
