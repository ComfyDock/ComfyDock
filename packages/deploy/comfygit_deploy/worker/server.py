"""Worker HTTP server for managing ComfyUI instances.

Provides REST API for creating, starting, stopping, and terminating instances.
"""

import asyncio
import base64
import glob
import os
import secrets
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

from .. import __version__
from .native_manager import NativeManager
from .state import InstanceState, PortAllocator, WorkerState

MODEL_EXTENSIONS = {
    ".safetensors",
    ".ckpt",
    ".pt",
    ".pth",
    ".bin",
    ".gguf",
}
SKIPPED_MODEL_DIRS = {".venv", "__pycache__", ".git", ".cache"}


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
        self.models_path_cache: Path | None = None
        self.model_download_tasks: set[asyncio.Task[Any]] = set()
        self.git_pull_tasks: dict[str, asyncio.Task[Any]] = {}


def _resolve_models_path(worker: WorkerServer, *, create: bool = False) -> Path:
    """Resolve the shared models directory and cache the result."""
    if worker.models_path_cache is not None:
        if create and not worker.models_path_cache.exists():
            worker.models_path_cache.mkdir(parents=True, exist_ok=True)
        return worker.models_path_cache

    candidates: list[Path] = []
    seen: set[Path] = set()

    # Check running instances first
    for instance in worker.state.instances.values():
        candidate = worker.workspace_path / instance.environment_name / "ComfyUI" / "models"
        if candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)

    # Check environments/ subdirectory (standard comfygit layout)
    envs_dir = worker.workspace_path / "environments"
    if envs_dir.is_dir():
        for child in envs_dir.iterdir():
            if child.is_dir():
                candidate = child / "ComfyUI" / "models"
                if candidate not in seen:
                    candidates.append(candidate)
                    seen.add(candidate)

    # Check direct workspace children as fallback
    if worker.workspace_path.exists():
        for child in worker.workspace_path.iterdir():
            candidate = child / "ComfyUI" / "models"
            if candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)

    for candidate in candidates:
        if candidate.is_symlink():
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            worker.models_path_cache = resolved
            return resolved

    workspace_models = worker.workspace_path / "models"
    if workspace_models.exists():
        worker.models_path_cache = workspace_models.resolve()
        return worker.models_path_cache

    shared_models = Path("/data/models")
    if shared_models.exists():
        worker.models_path_cache = shared_models.resolve()
        return worker.models_path_cache

    if create:
        workspace_models.mkdir(parents=True, exist_ok=True)
        worker.models_path_cache = workspace_models.resolve()
        return worker.models_path_cache

    worker.models_path_cache = workspace_models
    return worker.models_path_cache


def _instance_cec_path(worker: WorkerServer, instance: InstanceState) -> Path:
    """Return the tracked ComfyGit repo path for an instance."""
    return worker.workspace_path / "environments" / instance.environment_name / ".cec"


def _instance_has_git_repo(worker: WorkerServer, instance: InstanceState) -> bool:
    """Check whether the instance environment has an initialized git repo."""
    cec_path = _instance_cec_path(worker, instance)
    return cec_path.is_dir() and (cec_path / ".git").exists()


def _append_instance_log(worker: WorkerServer, instance_id: str, line: str) -> None:
    """Append a line to the instance log buffer."""
    worker.native_manager._append_log_line(instance_id, line)


async def _run_git_command(
    repo_path: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    """Run a git command inside the instance .cec repo."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(repo_path),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
        proc.returncode,
    )


async def _get_git_status_payload(
    worker: WorkerServer,
    instance: InstanceState,
) -> dict[str, Any]:
    """Collect git state for an instance environment."""
    cec_path = _instance_cec_path(worker, instance)

    branch_out, _, _ = await _run_git_command(cec_path, "branch", "--show-current")
    commit_out, _, _ = await _run_git_command(
        cec_path,
        "log",
        "-1",
        "--format=%H%n%s%n%aI%n%an",
    )
    status_out, _, _ = await _run_git_command(cec_path, "status", "--porcelain")
    remote_out, _, _ = await _run_git_command(cec_path, "remote", "-v")

    commit_lines = commit_out.splitlines() if commit_out else []
    remotes: dict[str, str] = {}
    for line in remote_out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] not in remotes:
            remotes[parts[0]] = parts[1]

    ahead = 0
    behind = 0
    upstream_out = ""
    if remotes:
        upstream_out, _, upstream_rc = await _run_git_command(
            cec_path,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
        )
        if upstream_rc == 0 and upstream_out:
            await _run_git_command(cec_path, "fetch", "--quiet")
            ab_out, _, ab_rc = await _run_git_command(
                cec_path,
                "rev-list",
                "--left-right",
                "--count",
                f"HEAD...{upstream_out}",
            )
            if ab_rc == 0 and ab_out:
                counts = ab_out.split()
                if len(counts) == 2:
                    ahead = int(counts[0])
                    behind = int(counts[1])

    pull_task = worker.git_pull_tasks.get(instance.id)
    return {
        "branch": branch_out or "main",
        "commit": {
            "hash": commit_lines[0] if len(commit_lines) > 0 else None,
            "short_hash": commit_lines[0][:7] if len(commit_lines) > 0 else None,
            "message": commit_lines[1] if len(commit_lines) > 1 else None,
            "date": commit_lines[2] if len(commit_lines) > 2 else None,
            "author": commit_lines[3] if len(commit_lines) > 3 else None,
        },
        "dirty": bool(status_out),
        "changed_files": [line.strip() for line in status_out.splitlines() if line.strip()],
        "remote": {
            "name": next(iter(remotes), None),
            "url": next(iter(remotes.values()), None),
        },
        "ahead": ahead,
        "behind": behind,
        "has_remote": bool(remotes),
        "has_upstream": bool(upstream_out),
        "pulling": bool(pull_task and not pull_task.done()),
    }


async def _get_git_log_payload(
    worker: WorkerServer,
    instance: InstanceState,
    *,
    limit: int,
) -> dict[str, Any]:
    """Collect recent commit history for an instance environment."""
    cec_path = _instance_cec_path(worker, instance)
    log_out, _, _ = await _run_git_command(
        cec_path,
        "log",
        f"-{limit}",
        "--format=%H%n%s%n%aI%n%an%n---",
    )

    commits: list[dict[str, Any]] = []
    if log_out:
        for entry in log_out.split("---\n"):
            lines = entry.strip().splitlines()
            if len(lines) >= 4:
                commits.append({
                    "hash": lines[0],
                    "short_hash": lines[0][:7],
                    "message": lines[1],
                    "date": lines[2],
                    "author": lines[3],
                })

    return {"commits": commits}


async def _run_instance_git_pull(
    worker: WorkerServer,
    instance: InstanceState,
    *,
    force: bool,
) -> None:
    """Run cg pull in the background and stream output into the instance log buffer."""
    cec_path = _instance_cec_path(worker, instance)
    cmd = ["cg", "pull", "--yes"]
    if force:
        cmd.append("--force")

    env = os.environ.copy()
    env["COMFYGIT_HOME"] = str(worker.workspace_path)

    worker.native_manager._ensure_log_buffer(instance.id)
    _append_instance_log(worker, instance.id, f"[cg pull] Starting {' '.join(cmd)}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cec_path),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        stdout_stream = proc.stdout
        if stdout_stream is not None:
            while True:
                line = await stdout_stream.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                _append_instance_log(worker, instance.id, f"[cg pull] {decoded}")

        await proc.wait()
        if proc.returncode == 0:
            _append_instance_log(worker, instance.id, "[cg pull] Pull completed successfully.")
        else:
            _append_instance_log(
                worker,
                instance.id,
                f"[cg pull] Pull failed with exit code {proc.returncode}.",
            )
    except Exception as exc:
        _append_instance_log(worker, instance.id, f"[cg pull] Pull crashed: {exc}")
    finally:
        worker.git_pull_tasks.pop(instance.id, None)


def _start_git_pull(
    worker: WorkerServer,
    instance: InstanceState,
    *,
    force: bool,
) -> dict[str, Any]:
    """Schedule cg pull for an instance if one is not already running."""
    existing_task = worker.git_pull_tasks.get(instance.id)
    if existing_task and not existing_task.done():
        raise RuntimeError("A pull is already in progress for this instance.")

    task = asyncio.create_task(_run_instance_git_pull(worker, instance, force=force))
    worker.git_pull_tasks[instance.id] = task
    return {
        "status": "pulling",
        "force": force,
        "message": "Pull started. Check git-status for completion.",
    }


def _resolve_model_relative_path(path_value: str) -> Path:
    """Validate a user-provided model path relative to the models directory."""
    normalized = str(path_value or "").strip().replace("\\", "/")
    if not normalized:
        raise ValueError("path is required")

    path = Path(normalized)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError("Invalid model path")

    safe_parts = [part for part in path.parts if part not in {"", "."}]
    if not safe_parts:
        raise ValueError("Invalid model path")

    return Path(*safe_parts)


def _resolve_model_file_path(
    models_path: Path,
    relative_path: str,
    *,
    require_exists: bool = False,
) -> Path:
    """Resolve a relative model path and ensure it stays within models_path."""
    safe_relative = _resolve_model_relative_path(relative_path)
    base_path = models_path.resolve()
    target = (base_path / safe_relative).resolve(strict=require_exists)
    if not target.is_relative_to(base_path):
        raise ValueError("Invalid model path")
    return target


async def _download_model_to_path(url: str, destination: Path) -> None:
    """Download a model to disk using a temporary file and atomic rename."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f"{destination.name}.part")
    if temp_path.exists():
        temp_path.unlink()

    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=300)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status >= 400:
                    raise RuntimeError(f"Download failed with HTTP {response.status}")

                with temp_path.open("wb") as handle:
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        if chunk:
                            handle.write(chunk)

        temp_path.replace(destination)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def _track_background_task(worker: WorkerServer, task: asyncio.Task[Any]) -> None:
    worker.model_download_tasks.add(task)
    task.add_done_callback(worker.model_download_tasks.discard)


def _launch_model_download(
    worker: WorkerServer,
    *,
    url: str,
    destination: Path,
) -> None:
    async def _runner() -> None:
        try:
            await _download_model_to_path(url, destination)
        except Exception as exc:
            print(f"Model download failed for {destination}: {exc}")

    task = asyncio.create_task(_runner())
    _track_background_task(worker, task)


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


async def handle_list_models(request: web.Request) -> web.Response:
    """GET /api/v1/models - List models from the shared models directory."""
    worker: WorkerServer = request.app["worker"]
    models_path = _resolve_models_path(worker)

    models: list[dict[str, Any]] = []
    total_size_bytes = 0

    if models_path.exists():
        for root, dirs, files in os.walk(models_path):
            dirs[:] = [name for name in dirs if name not in SKIPPED_MODEL_DIRS]
            root_path = Path(root)

            for filename in files:
                file_path = root_path / filename
                if file_path.suffix.lower() not in MODEL_EXTENSIONS:
                    continue

                try:
                    stat = file_path.stat()
                except OSError:
                    continue

                relative_path = file_path.relative_to(models_path).as_posix()
                folder = Path(relative_path).parent.as_posix()
                if folder == ".":
                    folder = ""

                models.append({
                    "name": file_path.name,
                    "path": relative_path,
                    "folder": folder,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(
                        stat.st_mtime,
                        timezone.utc,
                    ).isoformat(),
                })
                total_size_bytes += stat.st_size

    models.sort(key=lambda item: str(item["path"]).lower())
    return web.json_response({
        "models_path": str(models_path),
        "total_size_bytes": total_size_bytes,
        "models": models,
    })


async def handle_download_model(request: web.Request) -> web.Response:
    """POST /api/v1/models/download - Start a background model download."""
    worker: WorkerServer = request.app["worker"]

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    url = str(data.get("url") or "").strip()
    relative_path = str(data.get("path") or "").strip()
    if not url:
        return web.json_response({"error": "url is required"}, status=400)
    if not relative_path:
        return web.json_response({"error": "path is required"}, status=400)

    try:
        models_path = _resolve_models_path(worker, create=True)
        destination = _resolve_model_file_path(models_path, relative_path)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    _launch_model_download(worker, url=url, destination=destination)
    return web.json_response({
        "status": "downloading",
        "path": relative_path.replace("\\", "/"),
    })


async def handle_delete_model(request: web.Request) -> web.Response:
    """DELETE /api/v1/models/{path:.*} - Delete a model file."""
    worker: WorkerServer = request.app["worker"]
    relative_path = request.match_info.get("path", "")

    try:
        models_path = _resolve_models_path(worker)
        file_path = _resolve_model_file_path(
            models_path,
            relative_path,
            require_exists=True,
        )
    except FileNotFoundError:
        return web.json_response({"error": "Model not found"}, status=404)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    if not file_path.is_file():
        return web.json_response({"error": "Model not found"}, status=404)

    try:
        file_path.unlink()
    except OSError as exc:
        return web.json_response({"error": f"Failed to delete model: {exc}"}, status=500)

    return web.json_response({
        "deleted": True,
        "path": relative_path.replace("\\", "/"),
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


async def handle_git_status(request: web.Request) -> web.Response:
    """GET /api/v1/instances/{id}/git-status - Return instance git state."""
    worker: WorkerServer = request.app["worker"]
    instance_id = request.match_info["id"]

    instance = worker.state.instances.get(instance_id)
    if not instance:
        return web.json_response({"error": "Instance not found"}, status=404)

    if not _instance_has_git_repo(worker, instance):
        return web.json_response({"error": "No git repository found"}, status=404)

    payload = await _get_git_status_payload(worker, instance)
    return web.json_response(payload)


async def handle_git_log(request: web.Request) -> web.Response:
    """GET /api/v1/instances/{id}/git-log - Return recent commit history."""
    worker: WorkerServer = request.app["worker"]
    instance_id = request.match_info["id"]

    instance = worker.state.instances.get(instance_id)
    if not instance:
        return web.json_response({"error": "Instance not found"}, status=404)

    if not _instance_has_git_repo(worker, instance):
        return web.json_response({"error": "No git repository found"}, status=404)

    try:
        limit = int(request.query.get("limit", "20"))
    except ValueError:
        return web.json_response({"error": "limit must be an integer"}, status=400)

    limit = min(max(limit, 1), 100)
    payload = await _get_git_log_payload(worker, instance, limit=limit)
    return web.json_response(payload)


async def handle_git_pull(request: web.Request) -> web.Response:
    """POST /api/v1/instances/{id}/git-pull - Run cg pull in the instance repo."""
    worker: WorkerServer = request.app["worker"]
    instance_id = request.match_info["id"]

    instance = worker.state.instances.get(instance_id)
    if not instance:
        return web.json_response({"error": "Instance not found"}, status=404)

    if not _instance_has_git_repo(worker, instance):
        return web.json_response({"error": "No git repository found"}, status=404)

    if request.can_read_body:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)
    else:
        body = {}

    raw_force = body.get("force", False) if isinstance(body, dict) else False
    if isinstance(raw_force, bool):
        force = raw_force
    elif isinstance(raw_force, str):
        force = raw_force.strip().lower() in {"1", "true", "yes", "on"}
    else:
        force = bool(raw_force)

    try:
        payload = _start_git_pull(worker, instance, force=force)
    except RuntimeError as exc:
        return web.json_response({"error": str(exc)}, status=409)

    return web.json_response(payload)


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


def _get_running_instance(worker: WorkerServer, instance_id: str) -> InstanceState:
    instance = worker.state.instances.get(instance_id)
    if not instance:
        raise LookupError("Instance not found")
    if instance.status != "running":
        raise RuntimeError("Instance is not running")
    return instance


def _comfyui_error_detail(status: int, payload: dict[str, Any] | None = None) -> str:
    if isinstance(payload, dict):
        detail = payload.get("error") or payload.get("detail")
        if detail:
            return str(detail)
    return f"ComfyUI returned HTTP {status}."


async def _proxy_comfyui_json_payload(
    worker: WorkerServer,
    instance_id: str,
    method: str,
    path: str,
    *,
    json_body: Any | None = None,
    params: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    instance = _get_running_instance(worker, instance_id)
    comfyui_url = f"http://localhost:{instance.assigned_port}"
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(
            method,
            f"{comfyui_url}{path}",
            json=json_body,
            params=params,
        ) as resp:
            payload = await resp.json(content_type=None)
            if not isinstance(payload, dict):
                raise RuntimeError("ComfyUI returned an unexpected JSON payload.")
            return resp.status, payload


async def _proxy_comfyui_view_payload(
    worker: WorkerServer,
    instance_id: str,
    *,
    params: dict[str, str],
) -> tuple[int, dict[str, Any]]:
    instance = _get_running_instance(worker, instance_id)
    comfyui_url = f"http://localhost:{instance.assigned_port}"
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{comfyui_url}/view", params=params) as resp:
            body = await resp.read()
            if resp.status >= 400:
                detail = body.decode("utf-8", errors="replace").strip()
                return resp.status, {
                    "error": detail or f"ComfyUI returned HTTP {resp.status}."
                }
            return resp.status, {
                "data": base64.b64encode(body).decode(),
                "content_type": resp.content_type,
            }


async def handle_comfyui_object_info(request: web.Request) -> web.Response:
    """GET /api/v1/instances/{id}/comfyui/object_info - Proxy object_info."""
    worker: WorkerServer = request.app["worker"]
    instance_id = request.match_info["id"]

    try:
        status, payload = await _proxy_comfyui_json_payload(
            worker,
            instance_id,
            "GET",
            "/object_info",
        )
        return web.json_response(payload, status=status)
    except LookupError:
        return web.json_response({"error": "Instance not found"}, status=404)
    except RuntimeError as exc:
        if str(exc) == "Instance is not running":
            return web.json_response({"error": "Instance is not running"}, status=409)
        return web.json_response({"error": str(exc)}, status=502)
    except asyncio.TimeoutError:
        return web.json_response({"error": "ComfyUI request timed out"}, status=504)
    except Exception as exc:
        return web.json_response({"error": f"ComfyUI proxy error: {exc}"}, status=502)


async def handle_comfyui_prompt(request: web.Request) -> web.Response:
    """POST /api/v1/instances/{id}/comfyui/prompt - Proxy prompt submission."""
    worker: WorkerServer = request.app["worker"]
    instance_id = request.match_info["id"]

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    try:
        status, payload = await _proxy_comfyui_json_payload(
            worker,
            instance_id,
            "POST",
            "/prompt",
            json_body=data,
        )
        return web.json_response(payload, status=status)
    except LookupError:
        return web.json_response({"error": "Instance not found"}, status=404)
    except RuntimeError as exc:
        if str(exc) == "Instance is not running":
            return web.json_response({"error": "Instance is not running"}, status=409)
        return web.json_response({"error": str(exc)}, status=502)
    except asyncio.TimeoutError:
        return web.json_response({"error": "ComfyUI request timed out"}, status=504)
    except Exception as exc:
        return web.json_response({"error": f"ComfyUI proxy error: {exc}"}, status=502)


async def handle_comfyui_history(request: web.Request) -> web.Response:
    """GET /api/v1/instances/{id}/comfyui/history/{prompt_id} - Proxy prompt history."""
    worker: WorkerServer = request.app["worker"]
    instance_id = request.match_info["id"]
    prompt_id = request.match_info["prompt_id"]

    try:
        status, payload = await _proxy_comfyui_json_payload(
            worker,
            instance_id,
            "GET",
            f"/history/{prompt_id}",
        )
        return web.json_response(payload, status=status)
    except LookupError:
        return web.json_response({"error": "Instance not found"}, status=404)
    except RuntimeError as exc:
        if str(exc) == "Instance is not running":
            return web.json_response({"error": "Instance is not running"}, status=409)
        return web.json_response({"error": str(exc)}, status=502)
    except asyncio.TimeoutError:
        return web.json_response({"error": "ComfyUI request timed out"}, status=504)
    except Exception as exc:
        return web.json_response({"error": f"ComfyUI proxy error: {exc}"}, status=502)


async def handle_comfyui_view(request: web.Request) -> web.Response:
    """GET /api/v1/instances/{id}/comfyui/view - Proxy output retrieval."""
    worker: WorkerServer = request.app["worker"]
    instance_id = request.match_info["id"]
    params = {
        "filename": request.query.get("filename", ""),
        "subfolder": request.query.get("subfolder", ""),
        "type": request.query.get("type", ""),
    }

    try:
        status, payload = await _proxy_comfyui_view_payload(
            worker,
            instance_id,
            params=params,
        )
        return web.json_response(payload, status=status)
    except LookupError:
        return web.json_response({"error": "Instance not found"}, status=404)
    except RuntimeError as exc:
        if str(exc) == "Instance is not running":
            return web.json_response({"error": "Instance is not running"}, status=409)
        return web.json_response({"error": str(exc)}, status=502)
    except asyncio.TimeoutError:
        return web.json_response({"error": "ComfyUI request timed out"}, status=504)
    except Exception as exc:
        return web.json_response({"error": f"ComfyUI proxy error: {exc}"}, status=502)


def _find_pid_on_port(port: int) -> int | None:
    """Find the PID of a process listening on the given port via /proc/net/tcp."""
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
    app.router.add_get("/api/v1/instances/{id}/git-status", handle_git_status)
    app.router.add_get("/api/v1/instances/{id}/git-log", handle_git_log)
    app.router.add_post("/api/v1/instances/{id}/git-pull", handle_git_pull)
    app.router.add_post("/api/v1/instances/{id}/stop", handle_stop_instance)
    app.router.add_post("/api/v1/instances/{id}/start", handle_start_instance)
    app.router.add_delete("/api/v1/instances/{id}", handle_terminate_instance)
    # Combined handler for both HTTP GET and WebSocket upgrade
    app.router.add_get("/api/v1/instances/{id}/logs", handle_logs)
    app.router.add_get(
        "/api/v1/instances/{id}/comfyui/object_info",
        handle_comfyui_object_info,
    )
    app.router.add_post(
        "/api/v1/instances/{id}/comfyui/prompt",
        handle_comfyui_prompt,
    )
    app.router.add_get(
        "/api/v1/instances/{id}/comfyui/history/{prompt_id}",
        handle_comfyui_history,
    )
    app.router.add_get(
        "/api/v1/instances/{id}/comfyui/view",
        handle_comfyui_view,
    )
    app.router.add_get("/api/v1/models", handle_list_models)
    app.router.add_post("/api/v1/models/download", handle_download_model)
    app.router.add_delete("/api/v1/models/{path:.*}", handle_delete_model)

    return app
