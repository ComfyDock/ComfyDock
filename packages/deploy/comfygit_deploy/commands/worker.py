"""Worker CLI command handlers.

Commands for setting up and managing the worker server on GPU machines.
"""

import argparse
import asyncio
import contextlib
import json
import secrets
from pathlib import Path

from ..config import DeployConfig

WORKER_CONFIG_PATH = Path.home() / ".config" / "comfygit" / "deploy" / "worker.json"


def generate_api_key() -> str:
    """Generate a new worker API key."""
    return f"cg_wk_{secrets.token_hex(16)}"


def load_worker_config() -> dict | None:
    """Load worker config from disk."""
    if not WORKER_CONFIG_PATH.exists():
        return None
    try:
        return json.loads(WORKER_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def get_validated_workspace() -> Path | None:
    """Get workspace path from env or config.

    Checks COMFYGIT_HOME env first, then falls back to worker config.

    Returns:
        Workspace Path if configured and exists, None otherwise.
    """
    import os

    # Check environment variable first (takes precedence)
    env_home = os.environ.get("COMFYGIT_HOME")
    if env_home:
        workspace = Path(env_home)
        if workspace.exists():
            return workspace

    # Fall back to worker config
    config = load_worker_config()
    if config and config.get("workspace_path"):
        workspace = Path(config["workspace_path"])
        if workspace.exists():
            return workspace

    return None


def save_worker_config(config: dict) -> None:
    """Save worker config to disk."""
    WORKER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    WORKER_CONFIG_PATH.write_text(json.dumps(config, indent=2))


def _resolve_cloud_settings(args: argparse.Namespace) -> tuple[str | None, str | None]:
    config = DeployConfig()

    cloud_url = args.cloud or config.cloud_url
    cloud_token = args.token or config.cloud_token

    updated = False
    if args.cloud:
        config.cloud_url = args.cloud
        updated = True
    if args.token:
        config.cloud_token = args.token
        updated = True
    if updated:
        config.save()

    return cloud_url, cloud_token


def is_worker_running() -> bool:
    """Check if worker server is running."""
    # Simple check - look for PID file or try to connect
    pid_file = WORKER_CONFIG_PATH.parent / "worker.pid"
    if not pid_file.exists():
        return False

    try:
        import os

        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # Check if process exists
        return True
    except (OSError, ValueError):
        return False


def handle_setup(args: argparse.Namespace) -> int:
    """Handle 'worker setup' command."""
    workspace = args.workspace or str(Path.home() / "comfygit")
    api_key = args.api_key or generate_api_key()

    config = {
        "version": "1",
        "api_key": api_key,
        "workspace_path": workspace,
        "default_mode": "docker",
        "server_port": 9090,
        "instance_port_range": {"start": 8200, "end": 8210},
    }

    save_worker_config(config)

    print("Worker setup complete!")
    print(f"  Workspace: {workspace}")
    print(f"  API Key: {api_key}")
    print(f"  Config: {WORKER_CONFIG_PATH}")
    print()
    print("To start the worker server:")
    print("  cg-deploy worker up")

    return 0


def handle_up(args: argparse.Namespace) -> int:
    """Handle 'worker up' command."""
    import os

    config = load_worker_config()
    if not config:
        print("Worker not configured. Run 'cg-deploy worker setup' first.")
        return 1

    # Use COMFYGIT_HOME if set, otherwise fall back to config
    workspace = get_validated_workspace()
    if not workspace:
        print("No valid workspace found.")
        print("Set COMFYGIT_HOME or run 'cg-deploy worker setup --workspace /path'")
        return 1

    # Parse port range
    port_range = args.port_range.split(":")
    port_start = int(port_range[0])
    port_end = int(port_range[1]) if len(port_range) > 1 else port_start + 10

    # Dev mode: explicit paths override saved config
    dev_core = getattr(args, "dev_core", None)
    dev_manager = getattr(args, "dev_manager", None)

    # --dev flag loads saved config for any missing paths
    if getattr(args, "dev", False):
        from .dev import load_dev_config
        dev_config = load_dev_config()
        dev_core = dev_core or dev_config.get("core_path")
        dev_manager = dev_manager or dev_config.get("manager_path")

    if dev_core:
        dev_core = str(Path(dev_core).resolve())
        os.environ["COMFYGIT_DEV_CORE_PATH"] = dev_core
        print(f"Dev mode: core -> {dev_core}")

    if dev_manager:
        dev_manager = str(Path(dev_manager).resolve())
        # Symlink manager to system_nodes
        system_nodes = workspace / ".metadata" / "system_nodes"
        system_nodes.mkdir(parents=True, exist_ok=True)
        manager_link = system_nodes / "comfygit-manager"

        if manager_link.is_symlink():
            manager_link.unlink()
        elif manager_link.is_dir():
            import shutil
            shutil.rmtree(manager_link)

        manager_link.symlink_to(dev_manager)
        print(f"Dev mode: manager -> {dev_manager}")

    cloud_url, cloud_token = _resolve_cloud_settings(args)
    if bool(cloud_url) != bool(cloud_token):
        print("Cloud tunnel requires both --cloud and --token, or both values saved in config.")
        return 1

    print(f"Starting worker server on {args.host}:{args.port}...")
    print(f"  Mode: {args.mode}")
    print(f"  Instance ports: {port_start}-{port_end}")
    print(f"  Broadcast: {args.broadcast}")
    if cloud_url:
        print(f"  Cloud tunnel: {cloud_url}")
    print()
    print("Press Ctrl+C to stop.")

    from aiohttp import web

    from ..tunnel.client import TunnelClient
    from ..worker.server import create_worker_app

    app = create_worker_app(
        api_key=config["api_key"],
        workspace_path=workspace,
        default_mode=args.mode,
        port_range_start=port_start,
        port_range_end=port_end,
    )

    if cloud_url and cloud_token:
        try:
            tunnel_client = TunnelClient(
                cloud_url=cloud_url,
                token=cloud_token,
                worker_server=app["worker"],
            )
        except ValueError as exc:
            print(f"Invalid cloud URL: {exc}")
            return 1

        app["tunnel_client"] = tunnel_client

        async def _start_tunnel(app: web.Application) -> None:
            app["tunnel_task"] = asyncio.create_task(tunnel_client.run())

        async def _stop_tunnel(app: web.Application) -> None:
            await tunnel_client.close()
            tunnel_task = app.get("tunnel_task")
            if tunnel_task:
                tunnel_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tunnel_task

        app.on_startup.append(_start_tunnel)
        app.on_cleanup.append(_stop_tunnel)

    # Save PID file
    pid_file = WORKER_CONFIG_PATH.parent / "worker.pid"
    import os

    pid_file.write_text(str(os.getpid()))

    # Start mDNS broadcast if requested
    broadcaster = None
    if args.broadcast:
        from ..worker.mdns import MDNSBroadcaster

        broadcaster = MDNSBroadcaster(port=args.port, mode=args.mode)
        broadcaster.start()

    try:
        web.run_app(app, host=args.host, port=args.port, print=lambda _: None)
    finally:
        if broadcaster:
            broadcaster.stop()
        pid_file.unlink(missing_ok=True)

    return 0


def handle_down(args: argparse.Namespace) -> int:
    """Handle 'worker down' command."""
    pid_file = WORKER_CONFIG_PATH.parent / "worker.pid"

    if not pid_file.exists():
        print("Worker server is not running.")
        return 0

    try:
        import os
        import signal

        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        pid_file.unlink(missing_ok=True)
        print("Worker server stopped.")
    except (OSError, ValueError) as e:
        print(f"Failed to stop worker: {e}")
        pid_file.unlink(missing_ok=True)
        return 1

    return 0


def handle_status(args: argparse.Namespace) -> int:
    """Handle 'worker status' command."""
    config = load_worker_config()

    if not config:
        print("Worker not configured. Run 'cg-deploy worker setup' first.")
        return 0

    running = is_worker_running()
    status = "RUNNING" if running else "NOT RUNNING"

    print(f"Worker Status: {status}")
    print(f"  Workspace: {config.get('workspace_path', 'N/A')}")
    print(f"  Default Mode: {config.get('default_mode', 'docker')}")
    print(f"  Server Port: {config.get('server_port', 9090)}")

    port_range = config.get("instance_port_range", {})
    print(
        f"  Instance Ports: {port_range.get('start', 8200)}-{port_range.get('end', 8210)}"
    )

    return 0


def handle_regenerate_key(args: argparse.Namespace) -> int:
    """Handle 'worker regenerate-key' command."""
    config = load_worker_config()
    if not config:
        print("Worker not configured. Run 'cg-deploy worker setup' first.")
        return 1

    old_key = config.get("api_key", "")[:20] + "..."
    new_key = generate_api_key()

    config["api_key"] = new_key
    save_worker_config(config)

    print("API key regenerated!")
    print(f"  Old: {old_key}")
    print(f"  New: {new_key}")
    print()
    print("Note: Update any clients using the old key.")

    if is_worker_running():
        print("Warning: Restart the worker server for the new key to take effect.")

    return 0
