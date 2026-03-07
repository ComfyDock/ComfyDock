"""Worker HTTP server for managing ComfyUI instances.

Provides REST API for creating, starting, stopping, and terminating instances.
"""

import asyncio
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from .. import __version__
from .native_manager import NativeManager
from .state import InstanceState, PortAllocator, WorkerState


def generate_instance_id() -> str:
    """Generate unique instance ID."""
    return f"inst_{secrets.token_hex(4)}"


def generate_instance_name(user_name: str | None) -> str:
    """Generate instance name with timestamp."""
    import re
    base = user_name or "unnamed"
    # Sanitize: lowercase, replace non-alphanumeric with hyphen, collapse multiples
    base = re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-')[:32] or "unnamed"
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = secrets.token_hex(2)
    return f"deploy-{base}-{date}-{suffix}"


class WorkerServer:
    """Worker HTTP server managing ComfyUI instances."""

    def __init__(
        self,
        api_key: str,
        workspace_path: Path,
        default_mode: str = "docker",
        port_range_start: int = 8200,
        port_range_end: int = 8210,
        state_dir: Path | None = None,
    ):
        """Initialize worker server.

        Args:
            api_key: API key for authentication
            workspace_path: ComfyGit workspace path
            default_mode: Default instance mode (docker/native)
            port_range_start: First port for instances
            port_range_end: Last port for instances
            state_dir: Directory for state files
        """
        self.api_key = api_key
        self.workspace_path = workspace_path
        self.default_mode = default_mode
        self.port_range_start = port_range_start
        self.port_range_end = port_range_end

        state_dir = state_dir or Path.home() / ".config" / "comfygit" / "deploy"
        state_dir.mkdir(parents=True, exist_ok=True)

        self.state = WorkerState(
            state_dir / "instances.json", workspace_path=workspace_path
        )
        self.port_allocator = PortAllocator(
            state_dir / "instances.json",
            base_port=port_range_start,
            max_instances=port_range_end - port_range_start,
        )

        # Instance managers by mode
        self.native_manager = NativeManager(workspace_path)
        # self.docker_manager = DockerManager(workspace_path)  # Future


@web.middleware
async def auth_middleware(
    request: web.Request, handler: Any
) -> web.StreamResponse:
    """Validate API key in Authorization header."""
    # Skip auth for certain paths if needed
    auth_header = request.headers.get("Authorization", "")
    expected_key = request.app["worker"].api_key

    if not auth_header.startswith("Bearer "):
        return web.json_response({"error": "Missing authorization"}, status=401)

    provided_key = auth_header[7:]
    if provided_key != expected_key:
        return web.json_response({"error": "Invalid API key"}, status=401)

    response: web.StreamResponse = await handler(request)
    return response


async def handle_health(request: web.Request) -> web.Response:
    """GET /api/v1/health - Health check endpoint."""
    return web.json_response({"status": "ok", "worker_version": __version__})


async def handle_system_info(request: web.Request) -> web.Response:
    """GET /api/v1/system/info - System information."""
    worker: WorkerServer = request.app["worker"]

    # Count instance states
    instances = worker.state.instances
    running = sum(1 for i in instances.values() if i.status == "running")
    stopped = sum(1 for i in instances.values() if i.status == "stopped")

    return web.json_response({
        "worker_version": __version__,
        "workspace_path": str(worker.workspace_path),
        "default_mode": worker.default_mode,
        "instances": {
            "total": len(instances),
            "running": running,
            "stopped": stopped,
        },
        "ports": {
            "range_start": worker.port_range_start,
            "range_end": worker.port_range_end,
            "allocated": list(worker.port_allocator.allocated.values()),
            "available": (worker.port_range_end - worker.port_range_start)
            - len(worker.port_allocator.allocated),
        },
    })


async def handle_list_instances(request: web.Request) -> web.Response:
    """GET /api/v1/instances - List all instances."""
    worker: WorkerServer = request.app["worker"]

    instances = [
        {
            "id": inst.id,
            "name": inst.name,
            "status": inst.status,
            "mode": inst.mode,
            "assigned_port": inst.assigned_port,
            "comfyui_url": f"http://localhost:{inst.assigned_port}"
            if inst.status == "running"
            else None,
            "created_at": inst.created_at,
        }
        for inst in worker.state.instances.values()
    ]

    return web.json_response({
        "instances": instances,
        "port_range": {
            "start": worker.port_range_start,
            "end": worker.port_range_end,
        },
        "ports_available": (worker.port_range_end - worker.port_range_start)
        - len(worker.port_allocator.allocated),
    })


async def handle_create_instance(request: web.Request) -> web.Response:
    """POST /api/v1/instances - Create new instance."""
    worker: WorkerServer = request.app["worker"]

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    import_source = data.get("import_source")
    if not import_source:
        return web.json_response(
            {"error": "import_source is required"}, status=400
        )

    name = data.get("name")
    mode = data.get("mode", worker.default_mode)
    branch = data.get("branch")

    try:
        instance = _create_instance_record(
            worker,
            name=name,
            mode=mode,
            import_source=import_source,
            branch=branch,
        )
    except RuntimeError as e:
        return web.json_response({"error": str(e)}, status=503)

    # Start deployment in background task
    asyncio.create_task(_deploy_instance(worker, instance))

    return web.json_response(_instance_response(instance), status=201)


async def handle_create_bundle_instance(request: web.Request) -> web.Response:
    """POST /api/v1/instances/bundle - Create an instance from an uploaded tarball."""
    worker: WorkerServer = request.app["worker"]

    try:
        reader = await request.multipart()
    except Exception:
        return web.json_response({"error": "Expected multipart form upload"}, status=400)

    fields: dict[str, str] = {}
    bundle_path: Path | None = None
    bundle_label = "environment.tar.gz"

    try:
        while True:
            part = await reader.next()
            if part is None:
                break

            if part.name == "bundle":
                bundle_label = part.filename or bundle_label
                with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp:
                    while True:
                        chunk = await part.read_chunk()
                        if not chunk:
                            break
                        tmp.write(chunk)
                    bundle_path = Path(tmp.name)
                continue

            fields[part.name] = await part.text()
    except Exception:
        if bundle_path:
            try:
                bundle_path.unlink()
            except OSError:
                pass
        return web.json_response({"error": "Failed to read uploaded bundle"}, status=400)

    if not bundle_path:
        return web.json_response({"error": "bundle file is required"}, status=400)

    name = fields.get("name")
    mode = fields.get("mode", worker.default_mode)

    try:
        instance = _create_instance_record(
            worker,
            name=name,
            mode=mode,
            import_source=f"bundle:{bundle_label}",
            branch=None,
        )
    except RuntimeError as e:
        try:
            bundle_path.unlink()
        except OSError:
            pass
        return web.json_response({"error": str(e)}, status=503)

    asyncio.create_task(
        _deploy_instance(
            worker,
            instance,
            deploy_source=str(bundle_path),
            cleanup_path=bundle_path,
        )
    )

    return web.json_response(_instance_response(instance), status=201)


def _create_instance_record(
    worker: WorkerServer,
    *,
    name: str | None,
    mode: str,
    import_source: str,
    branch: str | None,
) -> InstanceState:
    """Allocate an instance ID/port and persist the initial state."""
    instance_id = generate_instance_id()
    instance_name = generate_instance_name(name)

    port = worker.port_allocator.allocate(instance_id)

    instance = InstanceState(
        id=instance_id,
        name=instance_name,
        environment_name=instance_name,
        mode=mode,
        assigned_port=port,
        import_source=import_source,
        branch=branch,
        status="deploying",
    )

    worker.state.add_instance(instance)
    worker.state.save()
    return instance


def _instance_response(instance: InstanceState) -> dict[str, Any]:
    return {
        "id": instance.id,
        "name": instance.name,
        "environment_name": instance.environment_name,
        "status": instance.status,
        "mode": instance.mode,
        "assigned_port": instance.assigned_port,
        "created_at": instance.created_at,
    }


async def _deploy_instance(
    worker: WorkerServer,
    instance: InstanceState,
    *,
    deploy_source: str | None = None,
    cleanup_path: Path | None = None,
) -> None:
    """Background task to deploy and start an instance."""
    try:
        import_source = deploy_source or instance.import_source
        if instance.mode == "native":
            # Deploy environment (may skip if already exists)
            result = await worker.native_manager.deploy(
                instance_id=instance.id,
                environment_name=instance.environment_name,
                import_source=import_source,
                branch=instance.branch,
            )

            if not result.success:
                worker.state.update_status(instance.id, "error")
                worker.state.save()
                return

            # Start ComfyUI process
            worker.state.update_status(instance.id, "starting")
            worker.state.save()

            proc_info = worker.native_manager.start(
                instance_id=instance.id,
                environment_name=instance.environment_name,
                port=instance.assigned_port,
            )

            if not proc_info:
                worker.state.update_status(instance.id, "error")
                worker.state.save()
                return

            # Wait for ComfyUI to become ready
            is_ready = await worker.native_manager.wait_for_ready(
                port=instance.assigned_port,
                timeout_seconds=120.0,
                poll_interval=2.0,
            )

            if is_ready:
                worker.state.update_status(instance.id, "running", pid=proc_info.pid)
            else:
                # Process started but HTTP not responding
                worker.state.update_status(instance.id, "error")
        else:
            # Docker mode - not yet implemented
            worker.state.update_status(instance.id, "error")

        worker.state.save()

    except Exception as e:
        print(f"Deployment failed for {instance.id}: {e}")
        worker.state.update_status(instance.id, "error")
        worker.state.save()
    finally:
        if cleanup_path:
            try:
                cleanup_path.unlink()
            except OSError:
                pass


async def handle_get_instance(request: web.Request) -> web.Response:
    """GET /api/v1/instances/{id} - Get instance details."""
    worker: WorkerServer = request.app["worker"]
    instance_id = request.match_info["id"]

    instance = worker.state.instances.get(instance_id)
    if not instance:
        return web.json_response({"error": "Instance not found"}, status=404)

    return web.json_response({
        "id": instance.id,
        "name": instance.name,
        "environment_name": instance.environment_name,
        "status": instance.status,
        "mode": instance.mode,
        "assigned_port": instance.assigned_port,
        "import_source": instance.import_source,
        "branch": instance.branch,
        "container_id": instance.container_id,
        "pid": instance.pid,
        "created_at": instance.created_at,
        "comfyui_url": f"http://localhost:{instance.assigned_port}"
        if instance.status == "running"
        else None,
    })


async def handle_stop_instance(request: web.Request) -> web.Response:
    """POST /api/v1/instances/{id}/stop - Stop instance."""
    worker: WorkerServer = request.app["worker"]
    instance_id = request.match_info["id"]

    instance = worker.state.instances.get(instance_id)
    if not instance:
        return web.json_response({"error": "Instance not found"}, status=404)

    # Stop based on mode
    if instance.mode == "native":
        worker.native_manager.stop(instance_id, pid=instance.pid)
    # Docker mode would go here

    worker.state.update_status(instance_id, "stopped")
    worker.state.save()

    return web.json_response({
        "id": instance.id,
        "status": "stopped",
        "assigned_port": instance.assigned_port,
        "message": f"Instance stopped. Port {instance.assigned_port} remains reserved.",
    })


async def handle_start_instance(request: web.Request) -> web.Response:
    """POST /api/v1/instances/{id}/start - Start stopped instance."""
    worker: WorkerServer = request.app["worker"]
    instance_id = request.match_info["id"]

    instance = worker.state.instances.get(instance_id)
    if not instance:
        return web.json_response({"error": "Instance not found"}, status=404)

    # Start based on mode
    if instance.mode == "native":
        proc_info = worker.native_manager.start(
            instance_id=instance_id,
            environment_name=instance.environment_name,
            port=instance.assigned_port,
        )
        if proc_info:
            worker.state.update_status(instance_id, "running", pid=proc_info.pid)
        else:
            return web.json_response({"error": "Failed to start instance"}, status=500)
    else:
        return web.json_response({"error": "Docker mode not yet supported"}, status=501)

    worker.state.save()

    return web.json_response({
        "id": instance.id,
        "status": "running",
        "assigned_port": instance.assigned_port,
        "comfyui_url": f"http://localhost:{instance.assigned_port}",
        "message": f"Instance started on port {instance.assigned_port}.",
    })


async def handle_terminate_instance(request: web.Request) -> web.Response:
    """DELETE /api/v1/instances/{id} - Terminate instance."""
    worker: WorkerServer = request.app["worker"]
    instance_id = request.match_info["id"]
    keep_env = request.query.get("keep_env", "false").lower() == "true"

    instance = worker.state.instances.get(instance_id)
    if not instance:
        return web.json_response({"error": "Instance not found"}, status=404)

    # Terminate based on mode
    if instance.mode == "native":
        worker.native_manager.terminate(instance_id, pid=instance.pid)
        if not keep_env:
            worker.native_manager.delete_environment(instance.environment_name)
    # Docker mode would go here

    # Release port and remove from state
    worker.port_allocator.release(instance_id)
    worker.state.remove_instance(instance_id)
    worker.state.save()

    msg = f"Instance terminated. Port {instance.assigned_port} released."
    if not keep_env:
        msg += f" Environment '{instance.environment_name}' deleted."

    return web.json_response({
        "id": instance_id,
        "status": "terminated",
        "message": msg,
    })


async def handle_logs(request: web.Request) -> web.Response | web.WebSocketResponse:
    """Handle /api/v1/instances/{id}/logs - GET for fetch, WebSocket for streaming."""
    # Check if this is a WebSocket upgrade request
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await _handle_logs_websocket(request)

    # Regular HTTP GET request
    worker: WorkerServer = request.app["worker"]
    instance_id = request.match_info["id"]

    instance = worker.state.instances.get(instance_id)
    if not instance:
        return web.json_response({"error": "Instance not found"}, status=404)

    lines = int(request.query.get("lines", "100"))

    if instance.mode == "native":
        process_logs = worker.native_manager.get_logs(instance_id, lines=lines)
        logs = [{"level": "INFO", "message": line} for line in process_logs.stdout]
    else:
        logs = []

    return web.json_response({"logs": logs})


async def _handle_logs_websocket(request: web.Request) -> web.WebSocketResponse:
    """WebSocket /api/v1/instances/{id}/logs - Stream instance logs."""
    worker: WorkerServer = request.app["worker"]
    instance_id = request.match_info["id"]

    instance = worker.state.instances.get(instance_id)
    if not instance:
        raise web.HTTPNotFound(text="Instance not found")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Stream logs (no initial connection message - tests expect first message to be log type)
    last_index = 0
    try:
        while not ws.closed:
            if instance.mode == "native":
                buf = worker.native_manager._log_buffers.get(instance_id, [])
                # Send new lines since last check
                if len(buf) > last_index:
                    for line in buf[last_index:]:
                        await ws.send_json({
                            "type": "log",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "level": "INFO",
                            "message": line,
                        })
                    last_index = len(buf)

            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        # Server shutdown - close websocket gracefully
        await ws.close()
    except Exception:
        pass
    finally:
        if not ws.closed:
            await ws.close()

    return ws


def _find_pid_on_port(port: int) -> int | None:
    """Find the PID of a process listening on the given port via /proc/net/tcp."""
    import struct
    try:
        hex_port = f"{port:04X}"
        with open("/proc/net/tcp", "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 10:
                    continue
                local_addr = parts[1]
                if local_addr.endswith(f":{hex_port}"):
                    # Found a listener — get the inode
                    inode = parts[9]
                    if inode == "0":
                        continue
                    # Search /proc/*/fd/* for this inode
                    import glob
                    for fd_link in glob.glob("/proc/[0-9]*/fd/*"):
                        try:
                            target = os.readlink(fd_link)
                            if f"socket:[{inode}]" in target:
                                pid = int(fd_link.split("/")[2])
                                return pid
                        except (OSError, ValueError):
                            continue
    except (OSError, PermissionError):
        pass
    return None


def create_worker_app(
    api_key: str,
    workspace_path: Path,
    default_mode: str = "docker",
    port_range_start: int = 8200,
    port_range_end: int = 8210,
    state_dir: Path | None = None,
) -> web.Application:
    """Create aiohttp application for worker server.

    Args:
        api_key: API key for authentication
        workspace_path: ComfyGit workspace path
        default_mode: Default instance mode
        port_range_start: First port for instances
        port_range_end: Last port for instances
        state_dir: Directory for state files

    Returns:
        Configured aiohttp Application
    """
    app = web.Application(middlewares=[auth_middleware])

    # Create worker server instance
    worker = WorkerServer(
        api_key=api_key,
        workspace_path=workspace_path,
        default_mode=default_mode,
        port_range_start=port_range_start,
        port_range_end=port_range_end,
        state_dir=state_dir,
    )
    app["worker"] = worker

    # Recover log readers for instances that survived a worker restart
    for inst_id, inst in worker.state.instances.items():
        if inst.status == "running" and inst.assigned_port:
            import os
            pid_alive = False
            if inst.pid:
                try:
                    os.kill(inst.pid, 0)
                    pid_alive = True
                except (ProcessLookupError, PermissionError):
                    pass

            if pid_alive:
                worker.native_manager.recover_instance_logs(inst_id, inst.pid)
            else:
                # PID is gone — check if something is still listening on the port
                # (user may have restarted ComfyUI manually)
                import socket
                port_in_use = False
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(1)
                        s.connect(("127.0.0.1", inst.assigned_port))
                        port_in_use = True
                except (ConnectionRefusedError, OSError, TimeoutError):
                    pass

                if port_in_use:
                    # ComfyUI is running on the port but with a new PID — find it
                    new_pid = _find_pid_on_port(inst.assigned_port)
                    if new_pid:
                        worker.state.update_status(inst_id, "running", pid=new_pid)
                        worker.state.save()
                        worker.native_manager.recover_instance_logs(inst_id, new_pid)
                        print(f"  Recovered {inst_id}: new PID {new_pid} on port {inst.assigned_port}")
                    else:
                        worker.native_manager._ensure_log_buffer(inst_id)
                        worker.native_manager._append_log_line(
                            inst_id,
                            f"[worker] Instance running on port {inst.assigned_port} but PID unknown"
                        )
                        print(f"  Recovered {inst_id}: port {inst.assigned_port} active, PID unknown")
                else:
                    worker.state.update_status(inst_id, "stopped")
                    worker.state.save()
                    print(f"  Instance {inst_id}: process dead, port closed — marked stopped")

    # Register routes
    app.router.add_get("/api/v1/health", handle_health)
    app.router.add_get("/api/v1/system/info", handle_system_info)
    app.router.add_get("/api/v1/instances", handle_list_instances)
    app.router.add_post("/api/v1/instances", handle_create_instance)
    app.router.add_post("/api/v1/instances/bundle", handle_create_bundle_instance)
    app.router.add_get("/api/v1/instances/{id}", handle_get_instance)
    app.router.add_post("/api/v1/instances/{id}/stop", handle_stop_instance)
    app.router.add_post("/api/v1/instances/{id}/start", handle_start_instance)
    app.router.add_delete("/api/v1/instances/{id}", handle_terminate_instance)
    # Combined handler for both HTTP GET and WebSocket upgrade
    app.router.add_get("/api/v1/instances/{id}/logs", handle_logs)

    return app
