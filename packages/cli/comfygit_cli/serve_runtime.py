"""Contract-serving runtime for ComfyGit environments."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import subprocess
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp
from aiohttp import web
from comfygit_core.core.environment import Environment
from comfygit_core.models.workflow_contract import NamedWorkflowContract
from comfygit_core.services.workflow_execution import build_manifest_contract_prompt

from .serve_executor import (
    PROXY_AUTH_HEADER,
    ComfyGitServeTimeoutError,
    ComfyUIClient,
    ComfyUIExecutionError,
    ComfyUIRequestError,
    LocalComfyExecutor,
    ProxyComfyExecutor,
    RunExecutionRequest,
    RunExecutor,
    StagedUpload,
    _safe_artifact_filename,
    _write_local_artifact,
    artifact_dimensions,
    output_kind,
    workflow_contract_output_from_payload,
)
from .serve_state import (
    EphemeralServeStateStore,
    ServeGalleryItem,
    ServeRunOutputSlot,
    ServeRunRecord,
    ServeSession,
    ServeStateStore,
    SQLiteServeStateStore,
    utc_now,
)

DEFAULT_MAX_REQUEST_BYTES = 256 * 1024 * 1024
DEFAULT_RUN_TIMEOUT_SECONDS = 12 * 60 * 60
UPLOAD_TOKEN_BYTES = 32
DEFAULT_UPLOAD_CONTENT_TYPE = "application/octet-stream"
DEFAULT_UPLOAD_EXTENSION = ".bin"
SESSION_COOKIE_NAME = "comfygit_studio_session"
SESSION_HEADER_NAME = "X-ComfyGit-Studio-Session"
SHARED_GALLERY_SCOPE = "shared"
FILE_UPLOAD_CONTRACT_INPUT_TYPES = {"image", "audio", "video", "file"}
ACTIVE_RUN_STATUSES = {"submitted", "running"}
TERMINAL_RUN_STATUSES = {"completed", "error", "failed", "cancelled"}
OUTPUT_REQUEST_HEADERS = ("Range", "If-Range")
ENVIRONMENT_REF_DIGEST_FILES = ("pyproject.toml",)
ENVIRONMENT_REF_DIGEST_DIRS = ("workflow_api",)
GIT_COMMAND_TIMEOUT_SECONDS = 2

UPLOAD_FILE_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("image/jpeg", (".jpg", ".jpeg")),
    ("image/png", (".png",)),
    ("image/webp", (".webp",)),
    ("image/gif", (".gif",)),
    ("image/bmp", (".bmp",)),
    ("video/mp4", (".mp4",)),
    ("video/webm", (".webm",)),
    ("video/quicktime", (".mov",)),
    ("audio/wav", (".wav",)),
    ("audio/mpeg", (".mp3",)),
)
UPLOAD_MIME_TYPE_BY_EXTENSION = {
    extension: mime_type for mime_type, extensions in UPLOAD_FILE_TYPES for extension in extensions
}
UPLOAD_EXTENSION_BY_MIME_TYPE = {
    mime_type: extensions[0] for mime_type, extensions in UPLOAD_FILE_TYPES
}
UPLOAD_MIME_TYPE_ALIASES = {
    "image/jpg": "image/jpeg",
    "audio/mp3": "audio/mpeg",
    "audio/x-wav": "audio/wav",
}


@dataclass(frozen=True)
class ServeConfig:
    """Configuration for the local ComfyGit serve adapter."""

    host: str
    port: int
    comfy_url: str
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    run_timeout_seconds: float = DEFAULT_RUN_TIMEOUT_SECONDS
    state: str = "ephemeral"
    gallery: str = "private"
    state_db: Path | None = None
    role: str = "studio"
    executor: str = "local"
    proxy_url: str | None = None
    proxy_token: str | None = None
    callback_url: str | None = None
    callback_token: str | None = None
    artifact_dir: Path | None = None


@dataclass
class UploadRecord:
    upload_id: str
    token: str
    filename: str
    content_type: str
    size: int | None
    path: Path
    comfyui_filename: str
    status: str = "pending"

    def public_ref(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": "file_ref",
            "ref": self.upload_id,
            "filename": self.filename,
            "mime_type": self.content_type,
        }
        if self.size is not None:
            payload["size"] = self.size
        return payload


@dataclass(frozen=True)
class PreparedContractInputs:
    inputs: dict[str, Any]
    staged_uploads: tuple[StagedUpload, ...] = ()


@dataclass
class ProxyRuntimeRun:
    prompt_id: str
    status: str
    outputs: tuple[Any, ...]
    raw_result: dict[str, Any]
    error: str | None = None
    callback: ProxyCallbackTarget | None = None


@dataclass(frozen=True)
class ProxyArtifactRef:
    params: dict[str, str]


@dataclass(frozen=True)
class ProxyCallbackTarget:
    run_id: str
    url: str
    token: str | None = None


@dataclass(frozen=True)
class WorkerCallbackUpload:
    field_name: str
    filename: str
    content_type: str
    body: bytes


class ServeState:
    """Shared state for request handlers."""

    def __init__(
        self,
        env: Environment,
        config: ServeConfig,
        session: aiohttp.ClientSession,
        state_store: ServeStateStore | None = None,
    ) -> None:
        self.env = env
        self.config = config
        self.client = ComfyUIClient(config.comfy_url, session=session)
        self.artifact_dir = _serve_artifact_dir(env, config)
        if config.role == "studio" and config.executor == "proxy":
            if not config.proxy_url:
                raise ValueError("--proxy-url is required when --executor proxy is used.")
            self.executor: RunExecutor = ProxyComfyExecutor(
                config.proxy_url,
                session=session,
                token=config.proxy_token,
                artifact_dir=self.artifact_dir,
            )
        else:
            self.executor = LocalComfyExecutor(self.client, artifact_dir=self.artifact_dir)
        self.uploads: dict[str, UploadRecord] = {}
        self.proxy_runs: dict[str, ProxyRuntimeRun] = {}
        self.proxy_artifacts: dict[str, ProxyArtifactRef] = {}
        self.state_store = state_store or _create_state_store(env, config)
        self.background_tasks: set[asyncio.Task[Any]] = set()
        self.active_run_tasks: dict[str, asyncio.Task[Any]] = {}

    def manifest_snapshot(self):
        return self.env.get_manifest_snapshot()


SERVE_STATE_KEY = web.AppKey("serve_state", ServeState)
STUDIO_STATIC_DIR_KEY = web.AppKey("studio_static_dir", Path)


def serve_environment(env: Environment, config: ServeConfig) -> None:
    """Run the local contract-serving HTTP server until interrupted."""

    asyncio.run(_serve_environment_async(env, config))


async def _serve_environment_async(env: Environment, config: ServeConfig) -> None:
    async with aiohttp.ClientSession() as session:
        state = ServeState(env, config, session)
        try:
            app = create_proxy_app(state) if config.role == "proxy" else create_app(state)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, config.host, config.port)
            await site.start()
            print(f"Serving ComfyGit environment '{env.name}' on http://{config.host}:{config.port}")
            print(f"Serve role: {config.role}")
            if config.role == "proxy":
                print(f"Proxy ComfyUI API target: {config.comfy_url}")
            else:
                print(f"Executor: {config.executor}")
                print(f"ComfyUI API target: {config.comfy_url}")
                if config.executor == "proxy":
                    print(f"Proxy runtime target: {config.proxy_url}")
                    if config.callback_url:
                        print(f"Worker callback base URL: {config.callback_url}")
                print(f"Serve state: {config.state} ({'persistent' if state.state_store.persistent else 'ephemeral'})")
            print("Press Ctrl+C to stop.")
            try:
                await asyncio.Event().wait()
            finally:
                await runner.cleanup()
        finally:
            state.state_store.close()


def create_app(state: ServeState) -> web.Application:
    """Create the aiohttp application for a ComfyGit serve runtime."""

    app = web.Application(client_max_size=_max_request_bytes(state))
    app[SERVE_STATE_KEY] = state
    static_dir = _studio_static_dir()
    app[STUDIO_STATIC_DIR_KEY] = static_dir
    app.router.add_get("/", studio_index_handler)
    if (static_dir / "assets").exists():
        app.router.add_static("/assets/", static_dir / "assets", append_version=True)
    app.router.add_get("/favicon.ico", favicon_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/contracts", contracts_handler)
    app.router.add_get("/contracts/{workflow}/{contract}", single_contract_handler)
    app.router.add_post("/uploads/prepare", upload_prepare_handler)
    app.router.add_put("/uploads/{upload_id}", upload_put_handler)
    app.router.add_get("/uploads/{upload_id}/status", upload_status_handler)
    app.router.add_get("/gallery", gallery_handler)
    app.router.add_delete("/gallery/{item_id}", gallery_delete_handler)
    app.router.add_get("/runs", runs_handler)
    app.router.add_get("/runs/{run_id}", single_run_handler)
    app.router.add_post("/runs/{run_id}/cancel", cancel_run_handler)
    app.router.add_post("/worker-callback/runs/{run_id}", worker_callback_handler)
    app.router.add_post("/contracts/{workflow}/{contract}/run", run_contract_handler)
    app.router.add_get("/outputs/view", output_view_handler)
    app.router.add_get("/{tail:.*}", studio_index_handler)
    app.on_startup.append(_recover_active_runs_on_startup)
    app.on_cleanup.append(_cleanup_background_tasks)
    return app


def create_proxy_app(state: ServeState) -> web.Application:
    """Create the compute-only proxy runtime app for remote execution."""

    app = web.Application(client_max_size=_max_request_bytes(state))
    app[SERVE_STATE_KEY] = state
    app.router.add_get("/proxy/health", proxy_health_handler)
    app.router.add_post("/proxy/runs", proxy_run_create_handler)
    app.router.add_get("/proxy/runs/{prompt_id}", proxy_run_status_handler)
    app.router.add_post("/proxy/runs/{prompt_id}/cancel", proxy_run_cancel_handler)
    app.router.add_get("/proxy/artifacts/{artifact_id}", proxy_artifact_handler)
    app.on_cleanup.append(_cleanup_background_tasks)
    return app


async def _recover_active_runs_on_startup(app: web.Application) -> None:
    await _ensure_active_run_recovery(app[SERVE_STATE_KEY])


async def _cleanup_background_tasks(app: web.Application) -> None:
    state = app[SERVE_STATE_KEY]
    background_tasks = getattr(state, "background_tasks", None)
    if not isinstance(background_tasks, set):
        return
    tasks = list(background_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    background_tasks.clear()
    active_run_tasks = getattr(state, "active_run_tasks", None)
    if isinstance(active_run_tasks, dict):
        active_run_tasks.clear()


async def _ensure_active_run_recovery(state: ServeState) -> None:
    if not _state_supports_active_run_recovery(state):
        return
    if _state_uses_proxy_callbacks(state):
        return
    for run in state.state_store.list_active_runs(ACTIVE_RUN_STATUSES):
        if not run.prompt_id:
            _record_recovery_failure(state, run, "Active run has no ComfyUI prompt id to recover.")
            continue
        task = state.active_run_tasks.get(run.run_id)
        if task is not None and not task.done():
            continue
        outputs = _contract_outputs_for_run(state, run.workflow, run.contract)
        if outputs is None:
            _record_recovery_failure(
                state,
                run,
                f"Cannot recover active run because contract '{run.workflow} / {run.contract}' no longer exists.",
            )
            continue
        session = ServeSession(session_id=run.session_id, scope_key=run.scope_key)
        output_slots = _output_slots_for_run(
            run_id=run.run_id,
            session=session,
            workflow_name=run.workflow,
            contract_name=run.contract,
            outputs=outputs,
            prompt_id=run.prompt_id,
            inputs=run.inputs,
        )
        task = asyncio.create_task(
            _complete_submitted_run(
                state,
                session,
                run_id=run.run_id,
                workflow_name=run.workflow,
                contract_name=run.contract,
                inputs=run.inputs,
                prompt_id=run.prompt_id,
                outputs=outputs,
                timeout_seconds=state.config.run_timeout_seconds,
                poll_interval_seconds=1,
                issues=_run_issues(run),
                output_slots=output_slots,
                created_at=run.created_at,
            )
        )
        _track_active_run_task(state, run.run_id, task)


def _state_supports_active_run_recovery(state: Any) -> bool:
    return (
        isinstance(getattr(state, "active_run_tasks", None), dict)
        and isinstance(getattr(state, "background_tasks", None), set)
        and hasattr(state, "config")
        and hasattr(state, "executor")
        and hasattr(state, "state_store")
        and callable(getattr(state, "manifest_snapshot", None))
    )


def _state_uses_proxy_callbacks(state: Any) -> bool:
    config = getattr(state, "config", None)
    return (
        getattr(config, "executor", "local") == "proxy"
        and bool(getattr(config, "callback_url", None))
    )


def _track_active_run_task(state: ServeState, run_id: str, task: asyncio.Task[Any]) -> None:
    state.background_tasks.add(task)
    state.active_run_tasks[run_id] = task

    def discard(completed: asyncio.Task[Any]) -> None:
        state.background_tasks.discard(completed)
        if state.active_run_tasks.get(run_id) is completed:
            state.active_run_tasks.pop(run_id, None)

    task.add_done_callback(discard)


def _contract_outputs_for_run(state: ServeState, workflow_name: str, contract_name: str) -> tuple[Any, ...] | None:
    manifest = state.manifest_snapshot()
    workflow = manifest.workflows.get(workflow_name)
    execution_contract = getattr(workflow, "execution_contract", None) if workflow else None
    contract = execution_contract.contracts.get(contract_name) if execution_contract else None
    if contract is None:
        return None
    return tuple(contract.outputs)


def _run_issues(run: ServeRunRecord) -> list[dict[str, Any]]:
    raw_result = run.raw_result if isinstance(run.raw_result, Mapping) else {}
    issues = raw_result.get("issues")
    return [dict(issue) for issue in issues if isinstance(issue, Mapping)] if isinstance(issues, list) else []


def _record_recovery_failure(state: ServeState, run: ServeRunRecord, message: str) -> None:
    session = ServeSession(session_id=run.session_id, scope_key=run.scope_key)
    payload = {
        "error": "recovery_failed",
        "message": message,
        "run_id": run.run_id,
        "prompt_id": run.prompt_id,
    }
    _record_failed_run(
        state,
        session,
        run.workflow,
        run.contract,
        {"inputs": run.inputs},
        payload,
        run_id=run.run_id,
        prompt_id=run.prompt_id,
        gallery_item_id=f"gallery_{run.run_id}",
        created_at=run.created_at,
    )


def _max_request_bytes(state: ServeState) -> int:
    value = getattr(getattr(state, "config", None), "max_request_bytes", DEFAULT_MAX_REQUEST_BYTES)
    return value if isinstance(value, int) and value > 0 else DEFAULT_MAX_REQUEST_BYTES


def _state(request: web.Request) -> ServeState:
    return request.app[SERVE_STATE_KEY]


def _executor_unavailable_payload(
    state: ServeState,
    exc: BaseException,
    *,
    prompt_id: str | None = None,
) -> dict[str, Any]:
    is_proxy = getattr(state.config, "executor", "local") == "proxy"
    payload: dict[str, Any] = {
        "error": "proxy_unavailable" if is_proxy else "comfyui_unavailable",
        "message": str(exc),
    }
    if is_proxy:
        payload["proxy_url"] = state.config.proxy_url
    else:
        payload["comfy_url"] = state.config.comfy_url
    if prompt_id:
        payload["prompt_id"] = prompt_id
    return payload


def _environment_ref(env: Environment) -> dict[str, Any]:
    cec_path = getattr(env, "cec_path", None)
    cec_path = Path(cec_path) if cec_path is not None else None
    return {
        "environment": getattr(env, "name", None),
        "cec_commit": _git_output(cec_path, "rev-parse", "HEAD") if cec_path else None,
        "cec_dirty": _git_dirty(cec_path) if cec_path else None,
        "contract_digest": _contract_digest(cec_path) if cec_path else None,
    }


def _environment_ref_match(local_ref: Mapping[str, Any], remote_ref: Any) -> bool | None:
    if not isinstance(remote_ref, Mapping):
        return None
    local_digest = local_ref.get("contract_digest")
    remote_digest = remote_ref.get("contract_digest")
    if not isinstance(local_digest, str) or not isinstance(remote_digest, str):
        return None
    return secrets.compare_digest(local_digest, remote_digest)


def _contract_digest(cec_path: Path) -> str | None:
    paths = tuple(_contract_digest_paths(cec_path))
    if not paths:
        return None
    digest = hashlib.sha256()
    for relative_path in paths:
        absolute_path = cec_path / relative_path
        try:
            file_bytes = absolute_path.read_bytes()
        except OSError:
            return None
        digest.update(relative_path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_bytes)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _contract_digest_paths(cec_path: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for filename in ENVIRONMENT_REF_DIGEST_FILES:
        path = cec_path / filename
        if path.is_file():
            paths.append(Path(filename))
    for dirname in ENVIRONMENT_REF_DIGEST_DIRS:
        directory = cec_path / dirname
        if directory.is_dir():
            paths.extend(
                path.relative_to(cec_path)
                for path in sorted(directory.rglob("*"))
                if path.is_file()
            )
    return tuple(paths)


def _git_dirty(repo_path: Path) -> bool | None:
    status = _git_output(repo_path, "status", "--porcelain")
    if status is None:
        return None
    return bool(status)


def _git_output(repo_path: Path | None, *args: str) -> str | None:
    if repo_path is None or not repo_path.exists():
        return None
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=repo_path,
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _create_state_store(env: Environment, config: ServeConfig) -> ServeStateStore:
    if config.state == "local":
        return SQLiteServeStateStore(config.state_db or _default_state_db_path(env))
    return EphemeralServeStateStore()


def _default_state_db_path(env: Environment) -> Path:
    workspace_paths = getattr(env, "workspace_paths", None)
    metadata_dir = getattr(workspace_paths, "metadata", None)
    if metadata_dir is not None:
        return Path(metadata_dir) / "serve" / "serve.sqlite"
    workspace = getattr(env, "workspace", None)
    workspace_path = getattr(workspace, "path", None)
    if workspace_path is not None:
        return Path(workspace_path) / ".metadata" / "serve" / "serve.sqlite"
    env_path = Path(getattr(env, "path", "."))
    return env_path / ".metadata" / "serve" / "serve.sqlite"


def _serve_artifact_dir(env: Environment, config: ServeConfig) -> Path:
    if config.artifact_dir is not None:
        return config.artifact_dir
    workspace_paths = getattr(env, "workspace_paths", None)
    metadata_dir = getattr(workspace_paths, "metadata", None)
    if metadata_dir is not None:
        return Path(metadata_dir) / "serve" / "artifacts"
    workspace = getattr(env, "workspace", None)
    workspace_path = getattr(workspace, "path", None)
    if workspace_path is not None:
        return Path(workspace_path) / ".metadata" / "serve" / "artifacts"
    env_path = Path(getattr(env, "path", "."))
    return env_path / ".metadata" / "serve" / "artifacts"


def _studio_static_dir() -> Path:
    return Path(str(resources.files("comfygit_cli").joinpath("studio_static")))


async def studio_index_handler(request: web.Request) -> web.StreamResponse:
    static_dir = request.app[STUDIO_STATIC_DIR_KEY]
    index_path = static_dir / "index.html"
    if index_path.exists():
        html = index_path.read_text(encoding="utf-8")
        env_name = getattr(_state(request).env, "name", "Environment")
        config = {
            "apiBasePath": "",
            "authMode": "none",
            "endpointName": env_name if isinstance(env_name, str) else "Environment",
        }
        script = f"<script>window.__COMFYGIT_STUDIO_CONFIG__ = {json.dumps(config)};</script>"
        if "<head>" in html:
            html = html.replace("<head>", f"<head>{script}", 1)
        elif "</head>" in html:
            html = html.replace("</head>", f"{script}</head>", 1)
        else:
            html = f"{script}{html}"
        return web.Response(text=html, content_type="text/html")
    return web.Response(
        text=(
            "<!doctype html><html><head><title>ComfyGit Studio</title></head>"
            "<body><h1>ComfyGit Studio assets are not built.</h1>"
            "<p>Run the contract studio build before packaging or serving the UI.</p>"
            "</body></html>"
        ),
        content_type="text/html",
    )


async def favicon_handler(_request: web.Request) -> web.Response:
    return web.Response(status=204)


async def health_handler(request: web.Request) -> web.Response:
    state = _state(request)
    local_environment_ref = _environment_ref(state.env)
    payload: dict[str, Any] = {
        "ok": True,
        "environment": state.env.name,
        "environment_ref": local_environment_ref,
        "comfy_url": state.config.comfy_url,
        "executor": getattr(state.config, "executor", "local"),
        "comfyui": {"available": False},
    }
    if getattr(state.config, "executor", "local") == "proxy" and isinstance(state.executor, ProxyComfyExecutor):
        payload["proxy"] = {
            "configured": True,
            "available": None,
            "health_check": "deferred",
        }
        payload["proxy_environment_ref_match"] = None
        payload["comfyui"] = {
            "available": True,
            "mode": "proxy",
            "status": "deferred",
        }
        check_proxy = request.query.get("check_proxy", "").lower() in {"1", "true", "yes", "on"}
        if not check_proxy:
            return web.json_response(payload)
        try:
            proxy_health = await state.executor.check_health()
            proxy_payload = {
                "configured": True,
                "available": bool(proxy_health.get("ok", True)),
                "health_check": "checked",
            }
            proxy_payload.update(proxy_health)
            payload["proxy"] = proxy_payload
            payload["proxy_environment_ref_match"] = _environment_ref_match(
                local_environment_ref,
                proxy_health.get("environment_ref"),
            )
            payload["comfyui"] = proxy_health.get("comfyui", {"available": True})
        except (ComfyUIRequestError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            payload["proxy"] = {
                "configured": True,
                "available": False,
                "health_check": "checked",
                "error": str(exc),
            }
            payload["proxy_environment_ref_match"] = None
            payload["comfyui"] = {"available": False, "error": str(exc)}
        return web.json_response(payload)
    try:
        await state.client.check_health()
        payload["comfyui"] = {"available": True}
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        payload["comfyui"] = {"available": False, "error": str(exc)}
    return web.json_response(payload)


async def proxy_health_handler(request: web.Request) -> web.Response:
    auth_response = _proxy_auth_response(request)
    if auth_response is not None:
        return auth_response
    state = _state(request)
    payload: dict[str, Any] = {
        "ok": True,
        "role": "proxy",
        "environment": state.env.name,
        "environment_ref": _environment_ref(state.env),
        "comfy_url": state.config.comfy_url,
        "comfyui": {"available": False},
    }
    try:
        await state.client.check_health()
        payload["comfyui"] = {"available": True}
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        payload["comfyui"] = {"available": False, "error": str(exc)}
    return web.json_response(payload)


async def proxy_run_create_handler(request: web.Request) -> web.Response:
    auth_response = _proxy_auth_response(request)
    if auth_response is not None:
        return auth_response
    state = _state(request)
    try:
        payload = await _read_proxy_run_request(request, state)
        prompt = payload.get("prompt")
        if not isinstance(prompt, dict):
            raise ValueError("Proxy run payload must include a prompt object.")
        outputs_payload = payload.get("outputs", [])
        if not isinstance(outputs_payload, list):
            raise ValueError("Proxy run payload outputs must be a list.")
        outputs = tuple(
            workflow_contract_output_from_payload(output)
            for output in outputs_payload
            if isinstance(output, Mapping)
        )
        timeout_seconds = float(payload.get("timeout_seconds", state.config.run_timeout_seconds))
        poll_interval_seconds = float(payload.get("poll_interval_seconds", 1))
        cache_token = str(payload.get("cache_token") or uuid.uuid4().hex[:10])
        callback = _proxy_callback_target(payload.get("callback"))

        async def record_submitted(prompt_id: str) -> None:
            state.proxy_runs[prompt_id] = ProxyRuntimeRun(
                prompt_id=prompt_id,
                status="submitted",
                outputs=outputs,
                raw_result={"status": "submitted", "prompt_id": prompt_id},
                callback=callback,
            )

        execution = await state.executor.execute(
            RunExecutionRequest(
                prompt=prompt,
                outputs=outputs,
                wait=False,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                cache_token=cache_token,
                on_submitted=record_submitted,
            )
        )
        task = asyncio.create_task(
            _complete_proxy_runtime_run(
                state,
                execution.prompt_id,
                outputs,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                callback=callback,
            )
        )
        _track_proxy_task(state, task)
        return web.json_response({"status": execution.status, "prompt_id": execution.prompt_id})
    except ValueError as exc:
        return web.json_response({"error": "bad_request", "message": str(exc)}, status=400)
    except ComfyUIRequestError as exc:
        return web.json_response(
            {
                "error": "comfyui_rejected_request",
                "message": str(exc),
                "comfy_status": exc.status,
                "comfy_url": exc.url,
                "comfyui": exc.payload,
            },
            status=400 if exc.status == 400 else 502,
        )
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return web.json_response(
            {
                "error": "comfyui_unavailable",
                "message": str(exc),
                "comfy_url": state.config.comfy_url,
            },
            status=502,
        )


async def proxy_run_status_handler(request: web.Request) -> web.Response:
    auth_response = _proxy_auth_response(request)
    if auth_response is not None:
        return auth_response
    record = _state(request).proxy_runs.get(request.match_info["prompt_id"])
    if record is None:
        return web.json_response({"error": "not_found", "message": "Unknown proxy run."}, status=404)
    return web.json_response(_proxy_run_payload(record))


async def proxy_run_cancel_handler(request: web.Request) -> web.Response:
    auth_response = _proxy_auth_response(request)
    if auth_response is not None:
        return auth_response
    state = _state(request)
    prompt_id = request.match_info["prompt_id"]
    record = state.proxy_runs.get(prompt_id)
    if record is None:
        return web.json_response({"error": "not_found", "message": "Unknown proxy run."}, status=404)
    try:
        await state.executor.cancel(prompt_id)
    except ComfyUIRequestError as exc:
        return web.json_response({"error": "comfyui_rejected_cancel", "message": str(exc)}, status=400)
    record.status = "cancelled"
    record.raw_result = {"status": "cancelled", "prompt_id": prompt_id}
    return web.json_response(_proxy_run_payload(record))


async def proxy_artifact_handler(request: web.Request) -> web.StreamResponse:
    auth_response = _proxy_auth_response(request)
    if auth_response is not None:
        return auth_response
    state = _state(request)
    artifact = state.proxy_artifacts.get(request.match_info["artifact_id"])
    if artifact is None:
        return web.json_response({"error": "not_found", "message": "Unknown proxy artifact."}, status=404)
    try:
        output_response = await state.client.fetch_output(
            artifact.params,
            request_headers=_output_request_headers(request),
        )
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return web.json_response(
            {
                "error": "comfyui_unavailable",
                "message": str(exc),
                "comfy_url": state.config.comfy_url,
            },
            status=502,
        )
    headers = {"Content-Type": output_response.content_type}
    if output_response.disposition:
        headers["Content-Disposition"] = output_response.disposition
    headers.update(output_response.headers)
    return web.Response(body=output_response.body, status=output_response.status, headers=headers)


async def contracts_handler(request: web.Request) -> web.Response:
    return web.json_response(_contracts_payload(_state(request)))


async def single_contract_handler(request: web.Request) -> web.Response:
    try:
        payload = _single_contract_payload(
            _state(request),
            request.match_info["workflow"],
            request.match_info["contract"],
        )
        return web.json_response(payload)
    except ValueError as exc:
        return web.json_response({"error": "bad_request", "message": str(exc)}, status=400)


async def upload_prepare_handler(request: web.Request) -> web.Response:
    try:
        body = await _read_json_body(request)
        if not isinstance(body, Mapping):
            raise ValueError("Upload prepare body must be a JSON object.")
        record = _prepare_upload_slot(_state(request), body)
        return web.json_response(
            {
                "kind": "upload_slot",
                "upload_id": record.upload_id,
                "ref": record.upload_id,
                "upload_url": f"/uploads/{record.upload_id}?token={record.token}",
                "method": "PUT",
                "headers": {"content-type": record.content_type},
                "destination": "input",
                "max_size": _max_request_bytes(_state(request)),
                "file_ref": record.public_ref(),
            }
        )
    except ValueError as exc:
        return web.json_response({"error": "bad_request", "message": str(exc)}, status=400)


async def upload_put_handler(request: web.Request) -> web.Response:
    state = _state(request)
    upload_id = request.match_info["upload_id"]
    record = state.uploads.get(upload_id)
    if record is None:
        return web.json_response({"error": "not_found", "message": "Unknown upload id."}, status=404)
    if not secrets.compare_digest(request.query.get("token", ""), record.token):
        return web.json_response({"error": "forbidden", "message": "Upload token is invalid."}, status=403)

    content_length = request.content_length
    max_bytes = _max_request_bytes(state)
    if content_length is not None and content_length > max_bytes:
        return _upload_too_large_response(max_bytes)

    record.path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = record.path.with_name(f".{record.path.name}.tmp")
    bytes_written = 0
    try:
        with temp_path.open("wb") as handle:
            try:
                async for chunk in request.content.iter_chunked(1024 * 1024):
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        handle.close()
                        temp_path.unlink(missing_ok=True)
                        return _upload_too_large_response(max_bytes)
                    handle.write(chunk)
            except web.HTTPRequestEntityTooLarge:
                handle.close()
                temp_path.unlink(missing_ok=True)
                return _upload_too_large_response(max_bytes)
        temp_path.replace(record.path)
    finally:
        temp_path.unlink(missing_ok=True)

    record.size = bytes_written
    record.status = "ready"
    return web.json_response({"status": "ready", "file_ref": record.public_ref()})


async def upload_status_handler(request: web.Request) -> web.Response:
    record = _state(request).uploads.get(request.match_info["upload_id"])
    if record is None:
        return web.json_response({"error": "not_found", "message": "Unknown upload id."}, status=404)
    return web.json_response({"status": record.status, "file_ref": record.public_ref()})


async def gallery_handler(request: web.Request) -> web.Response:
    await _ensure_active_run_recovery(_state(request))
    session = _serve_session(request)
    payload = {
        "state": _state(request).config.state,
        "gallery": _state(request).config.gallery,
        "session_id": session.session_id,
        "items": _state(request).state_store.list_gallery_items(session.scope_key),
    }
    return _json_response_for_session(payload, session)


async def gallery_delete_handler(request: web.Request) -> web.Response:
    session = _serve_session(request)
    deleted = _state(request).state_store.delete_gallery_item(
        session.scope_key,
        request.match_info["item_id"],
    )
    status = 200 if deleted else 404
    return _json_response_for_session({"deleted": deleted}, session, status=status)


async def runs_handler(request: web.Request) -> web.Response:
    await _ensure_active_run_recovery(_state(request))
    session = _serve_session(request)
    statuses = None
    if request.query.get("active") == "true":
        statuses = ACTIVE_RUN_STATUSES
    payload = {
        "state": _state(request).config.state,
        "session_id": session.session_id,
        "runs": _state(request).state_store.list_runs(session.scope_key, statuses=statuses),
    }
    return _json_response_for_session(payload, session)


async def single_run_handler(request: web.Request) -> web.Response:
    await _ensure_active_run_recovery(_state(request))
    session = _serve_session(request)
    state = _state(request)
    run_id = request.match_info["run_id"]
    run = state.state_store.get_run(session.scope_key, run_id)
    if run is None:
        return _json_response_for_session(
            {"error": "not_found", "message": f"Run '{run_id}' was not found."},
            session,
            status=404,
        )
    payload = {
        "state": state.config.state,
        "session_id": session.session_id,
        "run": run,
        "output_slots": state.state_store.list_output_slots(session.scope_key, run_id),
        "gallery_items": state.state_store.list_gallery_items_for_run(session.scope_key, run_id),
    }
    return _json_response_for_session(payload, session)


async def cancel_run_handler(request: web.Request) -> web.Response:
    session = _serve_session(request)
    state = _state(request)
    run_id = request.match_info["run_id"]
    run = state.state_store.get_run(session.scope_key, run_id)
    if run is None:
        return _json_response_for_session(
            {"error": "not_found", "message": f"Run '{run_id}' was not found."},
            session,
            status=404,
        )

    run_status = str(run.get("status") or "")
    if run_status == "cancelled":
        return _json_response_for_session(_cancelled_run_payload(state, session, run_id), session)
    if run_status in TERMINAL_RUN_STATUSES:
        return _json_response_for_session(
            {
                "error": "run_not_cancellable",
                "message": f"Run '{run_id}' is already {run_status}.",
                "run": run,
            },
            session,
            status=409,
        )

    prompt_id = run.get("prompt_id")
    cancel_warning: dict[str, Any] | None = None
    if isinstance(prompt_id, str) and prompt_id:
        try:
            await asyncio.wait_for(state.executor.cancel(prompt_id), timeout=10)
        except ComfyUIRequestError as exc:
            cancel_warning = {
                "error": "comfyui_rejected_cancel",
                "message": str(exc),
                "comfy_status": exc.status,
                "comfy_url": exc.url,
                "comfyui": exc.payload,
            }
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            cancel_warning = {
                "error": "comfyui_unavailable",
                "message": str(exc),
                "comfy_url": state.config.comfy_url,
            }
    else:
        cancel_warning = {
            "error": "prompt_id_missing",
            "message": f"Run '{run_id}' did not have a remote prompt id when local cancellation was requested.",
        }
    message = "Generation cancelled."
    raw_result = {
        "status": "cancelled",
        "run_id": run_id,
        "prompt_id": prompt_id,
        "message": message,
    }
    if cancel_warning is not None:
        raw_result["remote_cancel"] = cancel_warning
    if not state.state_store.cancel_run(session.scope_key, run_id, raw_result=raw_result, error=message):
        return _json_response_for_session(
            {
                "error": "run_not_cancellable",
                "message": f"Run '{run_id}' is no longer active.",
                "run": state.state_store.get_run(session.scope_key, run_id),
            },
            session,
            status=409,
        )

    task = state.active_run_tasks.pop(run_id, None)
    if task is not None and not task.done():
        task.cancel()

    payload = _cancelled_run_payload(state, session, run_id)
    if cancel_warning is not None:
        payload["remote_cancel"] = cancel_warning
    return _json_response_for_session(payload, session)


async def worker_callback_handler(request: web.Request) -> web.Response:
    auth_response = _worker_callback_auth_response(request)
    if auth_response is not None:
        return auth_response
    state = _state(request)
    route_run_id = request.match_info["run_id"]
    try:
        payload, uploads = await _read_worker_callback_request(request)
    except ValueError as exc:
        return web.json_response({"error": "bad_request", "message": str(exc)}, status=400)

    payload_run_id = payload.get("run_id")
    if payload_run_id is not None and payload_run_id != route_run_id:
        return web.json_response(
            {"error": "bad_request", "message": "Callback run_id does not match route run_id."},
            status=400,
        )
    run = state.state_store.get_run_record(route_run_id)
    if run is None:
        return web.json_response({"error": "not_found", "message": "Unknown coordinator run."}, status=404)

    status = str(payload.get("status") or "").lower()
    if run.status in TERMINAL_RUN_STATUSES and status in TERMINAL_RUN_STATUSES:
        session = ServeSession(session_id=run.session_id, scope_key=run.scope_key)
        return web.json_response({"status": run.status, "duplicate": True, **_callback_run_snapshot(state, session, run.run_id)})
    if status == "running":
        slots = _output_slots_for_callback_run(state, run)
        _record_worker_running_callback(state, run, payload, slots)
        session = ServeSession(session_id=run.session_id, scope_key=run.scope_key)
        return web.json_response({"status": "running", **_callback_run_snapshot(state, session, run.run_id)})
    if status == "completed":
        outputs = payload.get("outputs")
        if not isinstance(outputs, list):
            return web.json_response(
                {"error": "bad_request", "message": "Completed callback payload must include outputs."},
                status=400,
            )
        slots = _output_slots_for_callback_run(state, run)
        output_payloads = _localize_worker_callback_outputs(
            state,
            str(payload.get("prompt_id") or run.prompt_id or run.run_id),
            [dict(output) for output in outputs if isinstance(output, Mapping)],
            uploads,
        )
        response = {
            "status": "completed",
            "run_id": run.run_id,
            "prompt_id": str(payload.get("prompt_id") or run.prompt_id or ""),
            "issues": payload.get("issues") if isinstance(payload.get("issues"), list) else [],
            "outputs": output_payloads,
        }
        session = ServeSession(session_id=run.session_id, scope_key=run.scope_key)
        _record_completed_run_response(
            state,
            session,
            workflow_name=run.workflow,
            contract_name=run.contract,
            inputs=run.inputs,
            response=response,
            output_slots=slots,
            created_at=run.created_at,
        )
        return web.json_response({"status": "completed", **_callback_run_snapshot(state, session, run.run_id)})

    if status in {"error", "failed", "timeout", "cancelled"}:
        slots = _output_slots_for_callback_run(state, run)
        error_payload = dict(payload)
        error_payload.setdefault("status", "error" if status != "cancelled" else "cancelled")
        error_payload.setdefault("run_id", run.run_id)
        error_payload.setdefault("prompt_id", run.prompt_id)
        if status == "cancelled":
            state.state_store.cancel_run(
                run.scope_key,
                run.run_id,
                raw_result=error_payload,
                error=str(error_payload.get("message") or "Generation cancelled."),
            )
        else:
            _record_failed_run(
                state,
                ServeSession(session_id=run.session_id, scope_key=run.scope_key),
                run.workflow,
                run.contract,
                {"inputs": run.inputs},
                error_payload,
                run_id=run.run_id,
                prompt_id=str(error_payload.get("prompt_id") or run.prompt_id or "") or None,
                output_slots=slots,
                created_at=run.created_at,
            )
        session = ServeSession(session_id=run.session_id, scope_key=run.scope_key)
        return web.json_response({"status": error_payload["status"], **_callback_run_snapshot(state, session, run.run_id)})

    return web.json_response(
        {"error": "bad_request", "message": "Callback status must be running, completed, error, failed, timeout, or cancelled."},
        status=400,
    )


def _cancelled_run_payload(state: ServeState, session: ServeSession, run_id: str) -> dict[str, Any]:
    return {
        "status": "cancelled",
        "run_id": run_id,
        "run": state.state_store.get_run(session.scope_key, run_id),
        "output_slots": state.state_store.list_output_slots(session.scope_key, run_id),
        "gallery_items": state.state_store.list_gallery_items_for_run(session.scope_key, run_id),
    }


def _worker_callback_url(state: ServeState, run_id: str, *, wait: bool) -> str | None:
    if wait or state.config.executor != "proxy":
        return None
    base_url = getattr(state.config, "callback_url", None)
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/worker-callback/runs/{run_id}"


def _callback_auth_token(state: ServeState) -> str | None:
    token = getattr(state.config, "callback_token", None) or getattr(state.config, "proxy_token", None)
    return str(token) if token else None


def _worker_callback_auth_response(request: web.Request) -> web.Response | None:
    token = _callback_auth_token(_state(request))
    if not token:
        return None
    expected = f"Bearer {token}"
    received = request.headers.get(PROXY_AUTH_HEADER, "")
    if secrets.compare_digest(received, expected):
        return None
    return web.json_response({"error": "forbidden", "message": "Worker callback token is invalid."}, status=403)


async def _read_worker_callback_request(
    request: web.Request,
) -> tuple[dict[str, Any], dict[str, WorkerCallbackUpload]]:
    if not request.content_type.lower().startswith("multipart/"):
        return await _read_json_body(request), {}

    reader = await request.multipart()
    payload: dict[str, Any] | None = None
    uploads: dict[str, WorkerCallbackUpload] = {}
    while raw_part := await reader.next():
        if not isinstance(raw_part, aiohttp.BodyPartReader):
            raise ValueError("Nested multipart callback uploads are not supported.")
        part = raw_part
        if part.name == "payload":
            try:
                payload_data = json.loads(await part.text())
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid callback payload JSON: {exc}") from exc
            if not isinstance(payload_data, dict):
                raise ValueError("Callback payload must be a JSON object.")
            payload = payload_data
            continue
        field_name = str(part.name or "")
        if not field_name:
            raise ValueError("Callback upload part is missing a field name.")
        uploads[field_name] = WorkerCallbackUpload(
            field_name=field_name,
            filename=_safe_artifact_filename(part.filename, fallback=f"{field_name}.bin"),
            content_type=part.headers.get("Content-Type") or DEFAULT_UPLOAD_CONTENT_TYPE,
            body=await part.read(),
        )

    if payload is None:
        raise ValueError("Worker callback request is missing a payload field.")
    return payload, uploads


def _callback_run_snapshot(state: ServeState, session: ServeSession, run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "run": state.state_store.get_run(session.scope_key, run_id),
        "output_slots": state.state_store.list_output_slots(session.scope_key, run_id),
        "gallery_items": state.state_store.list_gallery_items_for_run(session.scope_key, run_id),
    }


def _output_slots_for_callback_run(state: ServeState, run: ServeRunRecord) -> list[ServeRunOutputSlot]:
    slots = [_output_slot_from_public_dict(run, slot) for slot in state.state_store.list_output_slots(run.scope_key, run.run_id)]
    if slots:
        return slots
    outputs = _contract_outputs_for_run(state, run.workflow, run.contract) or ()
    return _output_slots_for_run(
        run_id=run.run_id,
        session=ServeSession(session_id=run.session_id, scope_key=run.scope_key),
        workflow_name=run.workflow,
        contract_name=run.contract,
        outputs=outputs,
        prompt_id=run.prompt_id,
        inputs=run.inputs,
    )


def _output_slot_from_public_dict(run: ServeRunRecord, payload: Mapping[str, Any]) -> ServeRunOutputSlot:
    raw_result = payload.get("rawResult")
    return ServeRunOutputSlot(
        slot_id=str(payload.get("slot_id") or payload.get("slotId") or f"slot_{run.run_id}_0_result"),
        run_id=run.run_id,
        session_id=run.session_id,
        scope_key=run.scope_key,
        workflow=run.workflow,
        contract=run.contract,
        output_name=str(payload.get("outputName") or "result"),
        output_type=_slot_output_type(str(payload.get("type") or "json")),
        status=str(payload.get("status") or "pending"),
        prompt_id=str(payload.get("promptId") or run.prompt_id or "") or None,
        width=_optional_positive_int(payload.get("width")),
        height=_optional_positive_int(payload.get("height")),
        error=str(payload.get("error")) if payload.get("error") is not None else None,
        raw_result={str(key): value for key, value in raw_result.items()} if isinstance(raw_result, Mapping) else None,
        created_at=str(payload.get("createdAt") or run.created_at),
        updated_at=str(payload.get("updatedAt") or run.updated_at),
    )


def _record_worker_running_callback(
    state: ServeState,
    run: ServeRunRecord,
    payload: Mapping[str, Any],
    slots: list[ServeRunOutputSlot],
) -> None:
    prompt_id = str(payload.get("prompt_id") or run.prompt_id or "") or None
    raw_result = {"status": "running", "run_id": run.run_id, **dict(payload)}
    state.state_store.record_run(
        ServeRunRecord(
            run_id=run.run_id,
            session_id=run.session_id,
            scope_key=run.scope_key,
            workflow=run.workflow,
            contract=run.contract,
            status="running",
            inputs=run.inputs,
            prompt_id=prompt_id,
            raw_result=raw_result,
            created_at=run.created_at,
        )
    )
    state.state_store.record_output_slots(
        [_copy_output_slot(slot, status="running", prompt_id=prompt_id, raw_result=raw_result) for slot in slots]
    )


def _localize_worker_callback_outputs(
    state: ServeState,
    prompt_id: str,
    outputs: list[dict[str, Any]],
    uploads: Mapping[str, WorkerCallbackUpload],
) -> list[dict[str, Any]]:
    output_payloads = [dict(output) for output in outputs]
    for output_index, output in enumerate(output_payloads):
        artifacts = output.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact_index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                continue
            field_name = str(artifact.get("upload_field") or f"artifact_{output_index}_{artifact_index}")
            upload = uploads.get(field_name)
            if upload is None:
                continue
            filename = _safe_artifact_filename(
                artifact.get("filename") or upload.filename,
                fallback=upload.filename,
            )
            ref = _write_local_artifact(state.artifact_dir, prompt_id, filename, upload.body)
            artifact["serve_artifact"] = ref
            artifact["url"] = f"/outputs/view?serve_artifact={quote(ref, safe='/')}"
            artifact["content_type"] = upload.content_type
            artifact.pop("upload_field", None)
    return output_payloads


async def run_contract_handler(request: web.Request) -> web.Response:
    body: dict[str, Any] = {}
    session = _serve_session(request)
    try:
        body = await _read_json_body(request)
        payload = await _run_contract(
            _state(request),
            session,
            request.match_info["workflow"],
            request.match_info["contract"],
            body,
        )
        status = 400 if payload.get("status") == "invalid_request" else 200
        return _json_response_for_session(payload, session, status=status)
    except web.HTTPRequestEntityTooLarge:
        state = _state(request)
        max_mib = _max_request_bytes(state) // (1024 * 1024)
        return _json_response_for_session(
            {
                "error": "request_too_large",
                "message": (
                    f"Request body is too large. This cg serve instance accepts "
                    f"contract requests up to {max_mib} MiB."
                ),
            },
            session,
            status=413,
        )
    except ComfyGitServeTimeoutError as exc:
        payload = {"error": "timeout", "message": str(exc)}
        payload.update(_record_failed_run(_state(request), session, request.match_info["workflow"], request.match_info["contract"], body, payload))
        return _json_response_for_session(payload, session, status=504)
    except ComfyUIRequestError as exc:
        payload = {
            "error": "comfyui_rejected_request",
            "message": str(exc),
            "comfy_status": exc.status,
            "comfy_url": exc.url,
            "comfyui": exc.payload,
        }
        payload.update(_record_failed_run(_state(request), session, request.match_info["workflow"], request.match_info["contract"], body, payload))
        return _json_response_for_session(payload, session, status=400 if exc.status == 400 else 502)
    except ComfyUIExecutionError as exc:
        payload = {
            "error": "comfyui_execution_failed",
            "message": str(exc),
            "prompt_id": exc.prompt_id,
            "comfyui": exc.payload,
        }
        payload.update(_record_failed_run(_state(request), session, request.match_info["workflow"], request.match_info["contract"], body, payload))
        return _json_response_for_session(payload, session, status=500)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        state = _state(request)
        payload = _executor_unavailable_payload(state, exc)
        payload.update(_record_failed_run(state, session, request.match_info["workflow"], request.match_info["contract"], body, payload))
        return _json_response_for_session(payload, session, status=502)
    except ValueError as exc:
        payload = {"error": "bad_request", "message": str(exc)}
        payload.update(_record_failed_run(_state(request), session, request.match_info["workflow"], request.match_info["contract"], body, payload))
        return _json_response_for_session(payload, session, status=400)
    except Exception as exc:
        payload = {"error": "internal_error", "message": str(exc)}
        payload.update(_record_failed_run(_state(request), session, request.match_info["workflow"], request.match_info["contract"], body, payload))
        return _json_response_for_session(payload, session, status=500)


async def output_view_handler(request: web.Request) -> web.StreamResponse:
    serve_artifact = request.query.get("serve_artifact")
    if serve_artifact:
        return _serve_local_artifact_response(_state(request), serve_artifact)

    filename = request.query.get("filename")
    if not filename:
        return web.json_response(
            {"error": "bad_request", "message": "'filename' query parameter is required."},
            status=400,
        )
    params = {
        "filename": filename,
        "subfolder": request.query.get("subfolder", ""),
        "type": request.query.get("type", "output"),
    }
    try:
        output_response = await _state(request).client.fetch_output(
            params,
            request_headers=_output_request_headers(request),
        )
    except aiohttp.ClientResponseError as exc:
        if exc.status == 404:
            return web.json_response(
                {
                    "error": "output_not_found",
                    "message": "ComfyUI no longer has this output artifact.",
                    "filename": filename,
                    "type": params["type"],
                },
                status=404,
            )
        state = _state(request)
        return web.json_response(
            {
                "error": "comfyui_unavailable",
                "message": str(exc),
                "comfy_url": state.config.comfy_url,
            },
            status=502,
        )
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        state = _state(request)
        return web.json_response(
            {
                "error": "comfyui_unavailable",
                "message": str(exc),
                "comfy_url": state.config.comfy_url,
            },
            status=502,
        )
    headers = {"Content-Type": output_response.content_type}
    if output_response.disposition:
        headers["Content-Disposition"] = output_response.disposition
    headers.update(output_response.headers)
    return web.Response(body=output_response.body, status=output_response.status, headers=headers)


def _output_request_headers(request: web.Request) -> dict[str, str]:
    return {
        header_name: request.headers[header_name]
        for header_name in OUTPUT_REQUEST_HEADERS
        if header_name in request.headers
    }


def _serve_local_artifact_response(state: ServeState, artifact_ref: str) -> web.StreamResponse:
    path = _local_artifact_path(state, artifact_ref)
    if path is None or not path.is_file():
        return web.json_response({"error": "not_found", "message": "Unknown serve artifact."}, status=404)
    return web.FileResponse(path)


def _local_artifact_path(state: ServeState, artifact_ref: str) -> Path | None:
    ref_path = Path(artifact_ref)
    if ref_path.is_absolute() or ".." in ref_path.parts:
        return None
    if len(ref_path.parts) != 2:
        return None
    if any(_safe_token(part) != part for part in ref_path.parts):
        filename = ref_path.parts[-1]
        if _safe_upload_filename(filename) != filename:
            return None
    resolved = (state.artifact_dir / ref_path).resolve()
    artifact_root = state.artifact_dir.resolve()
    if artifact_root not in resolved.parents:
        return None
    return resolved


async def _read_json_body(request: web.Request) -> dict[str, Any]:
    if request.can_read_body is False:
        return {}
    try:
        data = await request.json()
    except ValueError as exc:
        raise ValueError(f"Invalid JSON body: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object.")
    return data


async def _read_proxy_run_request(request: web.Request, state: ServeState) -> dict[str, Any]:
    if not request.content_type.lower().startswith("multipart/"):
        return await _read_json_body(request)

    reader = await request.multipart()
    payload: dict[str, Any] | None = None
    staged_fields: set[str] = set()
    while raw_part := await reader.next():
        if not isinstance(raw_part, aiohttp.BodyPartReader):
            raise ValueError("Nested multipart proxy uploads are not supported.")
        part = raw_part
        if part.name == "payload":
            try:
                payload_data = json.loads(await part.text())
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid proxy payload JSON: {exc}") from exc
            if not isinstance(payload_data, dict):
                raise ValueError("Proxy payload must be a JSON object.")
            payload = payload_data
            continue
        if payload is None:
            raise ValueError("Proxy multipart payload must be sent before file parts.")
        upload = _proxy_upload_by_field(payload, str(part.name or ""))
        if upload is None:
            raise ValueError(f"Unexpected proxy upload field '{part.name}'.")
        await _stage_proxy_upload_part(state, part, upload)
        staged_fields.add(str(part.name))

    if payload is None:
        raise ValueError("Proxy run request is missing a payload field.")
    expected_fields = {
        str(upload.get("field_name") or "")
        for upload in payload.get("uploads", [])
        if isinstance(upload, Mapping)
    }
    missing_fields = {field for field in expected_fields if field and field not in staged_fields}
    if missing_fields:
        raise ValueError(f"Proxy run request is missing upload file part(s): {', '.join(sorted(missing_fields))}.")
    return payload


def _proxy_upload_by_field(payload: Mapping[str, Any], field_name: str) -> Mapping[str, Any] | None:
    uploads = payload.get("uploads")
    if not isinstance(uploads, list):
        return None
    for upload in uploads:
        if isinstance(upload, Mapping) and upload.get("field_name") == field_name:
            return upload
    return None


async def _stage_proxy_upload_part(
    state: ServeState,
    part: Any,
    upload: Mapping[str, Any],
) -> None:
    filename = _safe_upload_filename(upload.get("comfyui_filename") or part.filename)
    expected_size = _optional_positive_int(upload.get("size"))
    max_bytes = _max_request_bytes(state)
    if expected_size is not None and expected_size > max_bytes:
        raise ValueError(f"Proxy upload '{filename}' is too large. Limit: {max_bytes} bytes.")

    input_dir = _comfyui_input_dir(state.env)
    input_dir.mkdir(parents=True, exist_ok=True)
    target_path = input_dir / filename
    temp_path = target_path.with_name(f".{target_path.name}.tmp")
    bytes_written = 0
    try:
        with temp_path.open("wb") as handle:
            while chunk := await part.read_chunk(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    handle.close()
                    temp_path.unlink(missing_ok=True)
                    raise ValueError(f"Proxy upload '{filename}' is too large. Limit: {max_bytes} bytes.")
                handle.write(chunk)
        temp_path.replace(target_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _track_proxy_task(state: ServeState, task: asyncio.Task[Any]) -> None:
    state.background_tasks.add(task)
    task.add_done_callback(state.background_tasks.discard)


def _proxy_callback_target(value: Any) -> ProxyCallbackTarget | None:
    if not isinstance(value, Mapping):
        return None
    run_id = value.get("run_id")
    url = value.get("url")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("Proxy callback payload is missing a run_id.")
    if not isinstance(url, str) or not url:
        raise ValueError("Proxy callback payload is missing a url.")
    token = value.get("token")
    return ProxyCallbackTarget(
        run_id=run_id,
        url=url,
        token=str(token) if token else None,
    )


async def _complete_proxy_runtime_run(
    state: ServeState,
    prompt_id: str,
    outputs: tuple[Any, ...],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
    callback: ProxyCallbackTarget | None = None,
) -> None:
    record = state.proxy_runs.get(prompt_id)
    if record is None:
        return
    record.status = "running"
    record.raw_result = {"status": "running", "prompt_id": prompt_id}
    await _post_worker_status_callback(callback, {"status": "running", "run_id": callback.run_id, "prompt_id": prompt_id} if callback else {})
    try:
        execution = await state.executor.complete_submitted(
            prompt_id,
            outputs,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    except ComfyGitServeTimeoutError as exc:
        payload = {"error": "timeout", "message": str(exc), "prompt_id": prompt_id}
        _record_proxy_run_error(record, payload)
        await _post_worker_status_callback(callback, {"status": "error", "run_id": callback.run_id, **payload} if callback else {})
        return
    except ComfyUIRequestError as exc:
        payload = {
            "error": "comfyui_rejected_request",
            "message": str(exc),
            "comfy_status": exc.status,
            "comfy_url": exc.url,
            "comfyui": exc.payload,
            "prompt_id": prompt_id,
        }
        _record_proxy_run_error(record, payload)
        await _post_worker_status_callback(callback, {"status": "error", "run_id": callback.run_id, **payload} if callback else {})
        return
    except ComfyUIExecutionError as exc:
        payload = {
            "error": "comfyui_execution_failed",
            "message": str(exc),
            "prompt_id": exc.prompt_id,
            "comfyui": exc.payload,
        }
        _record_proxy_run_error(record, payload)
        await _post_worker_status_callback(callback, {"status": "error", "run_id": callback.run_id, **payload} if callback else {})
        return
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        payload = _executor_unavailable_payload(state, exc, prompt_id=prompt_id)
        _record_proxy_run_error(record, payload)
        await _post_worker_status_callback(callback, {"status": "error", "run_id": callback.run_id, **payload} if callback else {})
        return
    except Exception as exc:
        payload = {"error": "internal_error", "message": str(exc), "prompt_id": prompt_id}
        _record_proxy_run_error(record, payload)
        await _post_worker_status_callback(callback, {"status": "error", "run_id": callback.run_id, **payload} if callback else {})
        return

    output_payloads = _register_proxy_artifacts(state, execution.outputs)
    record.status = "completed"
    record.raw_result = {
        "status": "completed",
        "prompt_id": execution.prompt_id,
        "outputs": output_payloads,
    }
    if callback is not None:
        try:
            callback_outputs, uploads = await _worker_callback_outputs_and_uploads(state, execution.outputs)
            await _post_worker_completion_callback(
                callback,
                {
                    "status": "completed",
                    "run_id": callback.run_id,
                    "prompt_id": execution.prompt_id,
                    "outputs": callback_outputs,
                },
                uploads,
            )
        except Exception as exc:
            _record_proxy_run_error(
                record,
                {
                    "error": "callback_failed",
                    "message": str(exc),
                    "prompt_id": execution.prompt_id,
                },
            )


async def _post_worker_status_callback(callback: ProxyCallbackTarget | None, payload: Mapping[str, Any]) -> None:
    if callback is None:
        return
    await _post_worker_callback_request(callback, json_payload=dict(payload))


async def _post_worker_completion_callback(
    callback: ProxyCallbackTarget,
    payload: Mapping[str, Any],
    uploads: list[WorkerCallbackUpload],
) -> None:
    headers = _worker_callback_headers(callback)
    if not uploads:
        await _post_worker_callback_request(callback, json_payload=dict(payload))
        return

    def build_form() -> aiohttp.FormData:
        form = aiohttp.FormData()
        form.add_field("payload", json.dumps(dict(payload)), content_type="application/json")
        for upload in uploads:
            form.add_field(
                upload.field_name,
                upload.body,
                filename=upload.filename,
                content_type=upload.content_type,
            )
        return form

    await _post_worker_callback_request(callback, data_factory=build_form, headers=headers, timeout_seconds=120)


async def _post_worker_callback_request(
    callback: ProxyCallbackTarget,
    *,
    json_payload: dict[str, Any] | None = None,
    data_factory: Callable[[], aiohttp.FormData] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float = 30,
) -> None:
    request_headers = dict(headers or _worker_callback_headers(callback))
    for attempt in range(20):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                callback.url,
                json=json_payload,
                data=data_factory() if data_factory is not None else None,
                headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            ) as response:
                if response.status not in {404, 409} or attempt == 19:
                    response.raise_for_status()
                    return
        await asyncio.sleep(0.25)


def _worker_callback_headers(callback: ProxyCallbackTarget) -> dict[str, str]:
    if not callback.token:
        return {}
    return {PROXY_AUTH_HEADER: f"Bearer {callback.token}"}


async def _worker_callback_outputs_and_uploads(
    state: ServeState,
    outputs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[WorkerCallbackUpload]]:
    output_payloads = [dict(output) for output in outputs]
    uploads: list[WorkerCallbackUpload] = []
    for output_index, output in enumerate(output_payloads):
        artifacts = output.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        output_type = str(output.get("type") or "output")
        for artifact_index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                continue
            filename = str(artifact.get("filename") or "")
            if not filename:
                continue
            response = await state.client.fetch_output(
                {
                    "filename": filename,
                    "subfolder": str(artifact.get("subfolder") or ""),
                    "type": str(artifact.get("type") or "output"),
                },
                request_headers={},
            )
            field_name = f"artifact_{output_index}_{artifact_index}"
            safe_filename = _safe_artifact_filename(
                filename,
                fallback=f"{field_name}{_extension_for_content_type(response.content_type)}",
            )
            artifact["upload_field"] = field_name
            artifact["content_type"] = response.content_type
            artifact["kind"] = output_kind(output_type, safe_filename)
            uploads.append(
                WorkerCallbackUpload(
                    field_name=field_name,
                    filename=safe_filename,
                    content_type=response.content_type,
                    body=response.body,
                )
            )
    return output_payloads, uploads


def _record_proxy_run_error(record: ProxyRuntimeRun, payload: dict[str, Any]) -> None:
    record.status = "error"
    record.error = str(payload.get("message") or payload.get("error") or "Proxy run failed.")
    record.raw_result = {"status": "error", **payload}


def _register_proxy_artifacts(state: ServeState, outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output_payloads = [dict(output) for output in outputs]
    for output in output_payloads:
        output_type = str(output.get("type") or "output")
        artifacts = output.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            filename = str(artifact.get("filename") or "")
            if not filename:
                continue
            artifact_id = f"artifact_{uuid.uuid4().hex}"
            state.proxy_artifacts[artifact_id] = ProxyArtifactRef(
                params={
                    "filename": filename,
                    "subfolder": str(artifact.get("subfolder") or ""),
                    "type": str(artifact.get("type") or "output"),
                }
            )
            artifact["proxy_artifact_id"] = artifact_id
            artifact["url"] = f"/proxy/artifacts/{artifact_id}"
            artifact["kind"] = output_kind(output_type, filename)
    return output_payloads


def _proxy_run_payload(record: ProxyRuntimeRun) -> dict[str, Any]:
    return {"status": record.status, "prompt_id": record.prompt_id, **record.raw_result}


def _proxy_auth_response(request: web.Request) -> web.Response | None:
    token = getattr(_state(request).config, "proxy_token", None)
    if not token:
        return None
    expected = f"Bearer {token}"
    received = request.headers.get(PROXY_AUTH_HEADER, "")
    if secrets.compare_digest(received, expected):
        return None
    return web.json_response({"error": "forbidden", "message": "Proxy token is invalid."}, status=403)


def _serve_session(request: web.Request) -> ServeSession:
    state = _state(request)
    header_value = request.headers.get(SESSION_HEADER_NAME)
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    session_id = _session_id_from_value(cookie_value) or _session_id_from_value(header_value) or f"anon_{uuid.uuid4().hex}"
    scope_key = SHARED_GALLERY_SCOPE if state.config.gallery == "shared" else session_id
    return state.state_store.ensure_session(session_id, scope_key=scope_key)


def _json_response_for_session(
    payload: Mapping[str, Any],
    session: ServeSession,
    *,
    status: int = 200,
) -> web.Response:
    response = web.json_response(payload, status=status)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session.session_id,
        httponly=True,
        samesite="Lax",
        max_age=60 * 60 * 24 * 365,
    )
    return response


def _safe_token(value: str) -> str:
    return "".join(char for char in value if char.isalnum() or char in {"-", "_"})


def _session_id_from_value(value: str | None) -> str | None:
    if value and _safe_token(value) == value:
        return value
    return None


def _contracts_payload(state: ServeState) -> dict[str, Any]:
    manifest = state.manifest_snapshot()
    contracts: list[dict[str, Any]] = []
    for workflow_name, workflow in manifest.workflows.items():
        execution_contract = workflow.execution_contract
        if execution_contract is None:
            continue
        for contract_name, contract in execution_contract.contracts.items():
            contracts.append(_contract_payload(workflow_name, contract_name, contract))
    return {
        "environment": state.env.name,
        "contracts": contracts,
    }


def _single_contract_payload(
    state: ServeState,
    workflow_name: str,
    contract_name: str,
) -> dict[str, Any]:
    manifest = state.manifest_snapshot()
    workflow = manifest.workflows.get(workflow_name)
    if workflow is None or workflow.execution_contract is None:
        raise ValueError(f"Workflow '{workflow_name}' does not declare contracts.")
    contract = workflow.execution_contract.contracts.get(contract_name)
    if contract is None:
        raise ValueError(f"Workflow '{workflow_name}' does not declare contract '{contract_name}'.")
    return _contract_payload(workflow_name, contract_name, contract)


def _contract_payload(
    workflow_name: str,
    contract_name: str,
    contract: NamedWorkflowContract,
) -> dict[str, Any]:
    return {
        "workflow": workflow_name,
        "contract": contract_name,
        "display_name": contract.display_name,
        "description": contract.description,
        "inputs": [item.to_dict() for item in contract.inputs],
        "outputs": [item.to_dict() for item in contract.outputs],
    }


async def _run_contract(
    state: ServeState,
    session: ServeSession,
    workflow_name: str,
    contract_name: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    if "inputs" in body:
        inputs = body["inputs"]
    else:
        control_keys = {"wait", "timeout_seconds", "poll_interval_seconds"}
        inputs = {key: value for key, value in body.items() if key not in control_keys}
    if not isinstance(inputs, dict):
        raise ValueError("'inputs' must be a JSON object.")
    wait = bool(body.get("wait", False))
    timeout_seconds = float(body.get("timeout_seconds", state.config.run_timeout_seconds))
    poll_interval_seconds = float(body.get("poll_interval_seconds", 1))

    manifest = state.manifest_snapshot()
    prepared_contract = await _prepare_contract_run_inputs(state, workflow_name, contract_name, inputs)
    inputs = prepared_contract.inputs
    build_result = build_manifest_contract_prompt(
        manifest,
        state.env.cec_path,
        workflow_name,
        inputs,
        contract_name=contract_name,
    )
    if build_result.has_errors:
        payload: dict[str, Any] = {
            "status": "invalid_request",
            "issues": [asdict(issue) for issue in build_result.issues],
            "message": "Contract inputs could not be applied to the workflow prompt.",
        }
        error_record = _record_failed_run(state, session, workflow_name, contract_name, {"inputs": inputs}, payload)
        payload.update(error_record)
        return payload

    run_id = f"run_{uuid.uuid4().hex}"
    callback_url = _worker_callback_url(state, run_id, wait=wait)
    callback_token = _callback_auth_token(state) if callback_url else None

    async def record_submitted(prompt_id: str) -> None:
        response = {
            "status": "submitted",
            "run_id": run_id,
            "prompt_id": prompt_id,
            "issues": [asdict(issue) for issue in build_result.issues],
        }
        state.state_store.record_run(
            ServeRunRecord(
                run_id=run_id,
                session_id=session.session_id,
                scope_key=session.scope_key,
                workflow=workflow_name,
                contract=contract_name,
                status="submitted",
                prompt_id=prompt_id,
                inputs=_display_inputs(inputs),
                raw_result=dict(response),
            )
        )

    execution = await state.executor.execute(
        RunExecutionRequest(
            prompt=build_result.prompt,
            outputs=build_result.outputs,
            wait=wait,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            cache_token=uuid.uuid4().hex[:10],
            on_submitted=record_submitted,
            staged_uploads=prepared_contract.staged_uploads,
            callback_run_id=run_id if callback_url else None,
            callback_url=callback_url,
            callback_token=callback_token,
        )
    )

    response: dict[str, Any] = {
        "status": execution.status,
        "run_id": run_id,
        "prompt_id": execution.prompt_id,
        "issues": [asdict(issue) for issue in build_result.issues],
    }
    output_slots = _output_slots_for_run(
        run_id=run_id,
        session=session,
        workflow_name=workflow_name,
        contract_name=contract_name,
        outputs=build_result.outputs,
        prompt_id=execution.prompt_id,
        inputs=inputs,
    )
    if execution.status != "completed":
        if callback_url:
            existing_run = state.state_store.get_run_record(run_id)
            if existing_run is not None and existing_run.status != "submitted":
                snapshot = _callback_run_snapshot(state, session, run_id)
                snapshot["status"] = existing_run.status
                return snapshot
        pending_items = _pending_gallery_items_for_slots(
            output_slots,
            inputs=inputs,
            response=response,
        )
        state.state_store.record_output_slots(output_slots)
        state.state_store.record_gallery_items(pending_items)
        response["output_slots"] = [slot.to_public_dict() for slot in output_slots]
        response["gallery_items"] = [item.to_public_dict() for item in pending_items]
        if callback_url:
            return response
        task = asyncio.create_task(
            _complete_submitted_run(
                state,
                session,
                run_id=run_id,
                workflow_name=workflow_name,
                contract_name=contract_name,
                inputs=inputs,
                prompt_id=execution.prompt_id,
                outputs=build_result.outputs,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                issues=[asdict(issue) for issue in build_result.issues],
                output_slots=output_slots,
                created_at=output_slots[0].created_at if output_slots else utc_now(),
            )
        )
        _track_active_run_task(state, run_id, task)
        return response

    response["outputs"] = execution.outputs
    state.state_store.record_run(
        ServeRunRecord(
            run_id=run_id,
            session_id=session.session_id,
            scope_key=session.scope_key,
            workflow=workflow_name,
            contract=contract_name,
            status="completed",
            prompt_id=execution.prompt_id,
            inputs=_display_inputs(inputs),
            raw_result=dict(response),
        )
    )
    resolved_slots = _resolved_output_slots_for_response(output_slots, response)
    state.state_store.record_output_slots(resolved_slots)
    gallery_items = _gallery_items_for_outputs(
        run_id=run_id,
        session=session,
        workflow_name=workflow_name,
        contract_name=contract_name,
        inputs=inputs,
        response=response,
        output_slots=resolved_slots,
    )
    gallery_items.extend(
        _empty_gallery_items_for_slots(
            resolved_slots,
            existing_items=gallery_items,
            inputs=inputs,
            response=response,
        )
    )
    state.state_store.record_gallery_items(gallery_items)
    response["output_slots"] = [slot.to_public_dict() for slot in resolved_slots]
    response["gallery_items"] = [item.to_public_dict() for item in gallery_items]
    return response


async def _complete_submitted_run(
    state: ServeState,
    session: ServeSession,
    *,
    run_id: str,
    workflow_name: str,
    contract_name: str,
    inputs: dict[str, Any],
    prompt_id: str,
    outputs: tuple[Any, ...],
    timeout_seconds: float,
    poll_interval_seconds: float,
    issues: list[dict[str, Any]],
    output_slots: list[ServeRunOutputSlot],
    created_at: str,
) -> None:
    running_slots = [
        _copy_output_slot(slot, status="running", prompt_id=prompt_id, raw_result={"status": "running", "run_id": run_id, "prompt_id": prompt_id})
        for slot in output_slots
    ]
    state.state_store.record_output_slots(running_slots)
    state.state_store.record_run(
        ServeRunRecord(
            run_id=run_id,
            session_id=session.session_id,
            scope_key=session.scope_key,
            workflow=workflow_name,
            contract=contract_name,
            status="running",
            prompt_id=prompt_id,
            inputs=_display_inputs(inputs),
            raw_result={"status": "running", "run_id": run_id, "prompt_id": prompt_id, "issues": issues},
            created_at=created_at,
        )
    )
    try:
        execution = await state.executor.complete_submitted(
            prompt_id,
            outputs,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    except ComfyGitServeTimeoutError as exc:
        payload = {"error": "timeout", "message": str(exc), "prompt_id": prompt_id}
        _record_failed_run(
            state,
            session,
            workflow_name,
            contract_name,
            {"inputs": inputs},
            payload,
            run_id=run_id,
            prompt_id=prompt_id,
            output_slots=output_slots,
            created_at=created_at,
        )
        return
    except ComfyUIRequestError as exc:
        payload = {
            "error": "comfyui_rejected_request",
            "message": str(exc),
            "comfy_status": exc.status,
            "comfy_url": exc.url,
            "comfyui": exc.payload,
            "prompt_id": prompt_id,
        }
        _record_failed_run(
            state,
            session,
            workflow_name,
            contract_name,
            {"inputs": inputs},
            payload,
            run_id=run_id,
            prompt_id=prompt_id,
            output_slots=output_slots,
            created_at=created_at,
        )
        return
    except ComfyUIExecutionError as exc:
        payload = {
            "error": "comfyui_execution_failed",
            "message": str(exc),
            "prompt_id": exc.prompt_id,
            "comfyui": exc.payload,
        }
        _record_failed_run(
            state,
            session,
            workflow_name,
            contract_name,
            {"inputs": inputs},
            payload,
            run_id=run_id,
            prompt_id=prompt_id,
            output_slots=output_slots,
            created_at=created_at,
        )
        return
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        payload = _executor_unavailable_payload(state, exc, prompt_id=prompt_id)
        _record_failed_run(
            state,
            session,
            workflow_name,
            contract_name,
            {"inputs": inputs},
            payload,
            run_id=run_id,
            prompt_id=prompt_id,
            output_slots=output_slots,
            created_at=created_at,
        )
        return
    except Exception as exc:
        payload = {"error": "internal_error", "message": str(exc), "prompt_id": prompt_id}
        _record_failed_run(
            state,
            session,
            workflow_name,
            contract_name,
            {"inputs": inputs},
            payload,
            run_id=run_id,
            prompt_id=prompt_id,
            output_slots=output_slots,
            created_at=created_at,
        )
        return

    response: dict[str, Any] = {
        "status": "completed",
        "run_id": run_id,
        "prompt_id": execution.prompt_id,
        "issues": issues,
        "outputs": execution.outputs,
    }
    state.state_store.record_run(
        ServeRunRecord(
            run_id=run_id,
            session_id=session.session_id,
            scope_key=session.scope_key,
            workflow=workflow_name,
            contract=contract_name,
            status="completed",
            prompt_id=execution.prompt_id,
            inputs=_display_inputs(inputs),
            raw_result=dict(response),
            created_at=created_at,
        )
    )
    resolved_slots = _resolved_output_slots_for_response(output_slots, response)
    state.state_store.record_output_slots(resolved_slots)
    gallery_items = _gallery_items_for_outputs(
        run_id=run_id,
        session=session,
        workflow_name=workflow_name,
        contract_name=contract_name,
        inputs=inputs,
        response=response,
        output_slots=resolved_slots,
        created_at=created_at,
    )
    gallery_items.extend(
        _empty_gallery_items_for_slots(
            resolved_slots,
            existing_items=gallery_items,
            inputs=inputs,
            response=response,
        )
    )
    if not gallery_items:
        gallery_items = [
            _json_gallery_item_for_completed_run(
                run_id=run_id,
                session=session,
                workflow_name=workflow_name,
                contract_name=contract_name,
                inputs=inputs,
                response=response,
                item_id=_gallery_item_id_for_slot(resolved_slots[0]) if resolved_slots else f"gallery_{run_id}",
                slot_id=resolved_slots[0].slot_id if resolved_slots else None,
                created_at=created_at,
            )
        ]
    state.state_store.record_gallery_items(gallery_items)


def _record_completed_run_response(
    state: ServeState,
    session: ServeSession,
    *,
    workflow_name: str,
    contract_name: str,
    inputs: dict[str, Any],
    response: dict[str, Any],
    output_slots: list[ServeRunOutputSlot],
    created_at: str,
) -> None:
    prompt_id = str(response.get("prompt_id") or "") or None
    state.state_store.record_run(
        ServeRunRecord(
            run_id=str(response.get("run_id") or ""),
            session_id=session.session_id,
            scope_key=session.scope_key,
            workflow=workflow_name,
            contract=contract_name,
            status="completed",
            prompt_id=prompt_id,
            inputs=_display_inputs(inputs),
            raw_result=dict(response),
            created_at=created_at,
        )
    )
    resolved_slots = _resolved_output_slots_for_response(output_slots, response)
    state.state_store.record_output_slots(resolved_slots)
    gallery_items = _gallery_items_for_outputs(
        run_id=str(response.get("run_id") or ""),
        session=session,
        workflow_name=workflow_name,
        contract_name=contract_name,
        inputs=inputs,
        response=response,
        output_slots=resolved_slots,
        created_at=created_at,
    )
    gallery_items.extend(
        _empty_gallery_items_for_slots(
            resolved_slots,
            existing_items=gallery_items,
            inputs=inputs,
            response=response,
        )
    )
    if not gallery_items:
        gallery_items = [
            _json_gallery_item_for_completed_run(
                run_id=str(response.get("run_id") or ""),
                session=session,
                workflow_name=workflow_name,
                contract_name=contract_name,
                inputs=inputs,
                response=response,
                item_id=_gallery_item_id_for_slot(resolved_slots[0]) if resolved_slots else f"gallery_{response.get('run_id')}",
                slot_id=resolved_slots[0].slot_id if resolved_slots else None,
                created_at=created_at,
            )
        ]
    state.state_store.record_gallery_items(gallery_items)


def _output_slots_for_run(
    *,
    run_id: str,
    session: ServeSession,
    workflow_name: str,
    contract_name: str,
    outputs: tuple[Any, ...],
    prompt_id: str | None,
    inputs: dict[str, Any],
) -> list[ServeRunOutputSlot]:
    created_at = utc_now()
    slots: list[ServeRunOutputSlot] = []
    declared_outputs = outputs or (None,)
    for index, output in enumerate(declared_outputs):
        output_name = str(getattr(output, "name", "result") or "result")
        output_type = _slot_output_type(str(getattr(output, "type", "json") or "json"))
        width, height = _fallback_dimensions_for_type(output_type)
        slots.append(
            ServeRunOutputSlot(
                slot_id=_slot_id(run_id, index, output_name),
                run_id=run_id,
                session_id=session.session_id,
                scope_key=session.scope_key,
                workflow=workflow_name,
                contract=contract_name,
                output_name=output_name,
                output_type=output_type,
                status="pending",
                prompt_id=prompt_id,
                width=width,
                height=height,
                raw_result={"status": "pending", "run_id": run_id, "prompt_id": prompt_id, "inputs": _display_inputs(inputs)},
                created_at=created_at,
                updated_at=created_at,
            )
        )
    return slots


def _pending_gallery_items_for_slots(
    slots: list[ServeRunOutputSlot],
    *,
    inputs: dict[str, Any],
    response: dict[str, Any],
) -> list[ServeGalleryItem]:
    display_inputs = _display_inputs(inputs)
    return [
        ServeGalleryItem(
            item_id=_gallery_item_id_for_slot(slot),
            run_id=slot.run_id,
            session_id=slot.session_id,
            scope_key=slot.scope_key,
            workflow=slot.workflow,
            contract=slot.contract,
            status="pending",
            output_type=slot.output_type,
            slot_id=slot.slot_id,
            output_name=slot.output_name,
            prompt_id=slot.prompt_id,
            width=slot.width,
            height=slot.height,
            inputs=display_inputs,
            raw_result=dict(response),
            created_at=slot.created_at,
            updated_at=slot.created_at,
        )
        for slot in slots
    ]


def _resolved_output_slots_for_response(
    slots: list[ServeRunOutputSlot],
    response: dict[str, Any],
) -> list[ServeRunOutputSlot]:
    response_outputs = [output for output in response.get("outputs") or [] if isinstance(output, Mapping)]
    resolved: list[ServeRunOutputSlot] = []
    for index, slot in enumerate(slots):
        output = response_outputs[index] if index < len(response_outputs) else None
        artifacts = output.get("artifacts") if isinstance(output, Mapping) else None
        artifact_list = artifacts if isinstance(artifacts, list) else []
        output_type = _slot_output_type(str(output.get("type") or slot.output_type)) if isinstance(output, Mapping) else slot.output_type
        width, height = slot.width, slot.height
        if artifact_list:
            first_artifact = artifact_list[0]
            if isinstance(first_artifact, Mapping):
                item_type = output_kind(output_type, str(first_artifact.get("filename") or ""))
                width, height = _gallery_dimensions_for_artifact(item_type, first_artifact)
                output_type = item_type
        resolved.append(
            _copy_output_slot(
                slot,
                status="done" if artifact_list else "empty",
                output_type=output_type,
                prompt_id=str(response.get("prompt_id") or "") or slot.prompt_id,
                width=width,
                height=height,
                raw_result=dict(response),
            )
        )
    return resolved


def _copy_output_slot(
    slot: ServeRunOutputSlot,
    *,
    status: str,
    output_type: str | None = None,
    prompt_id: str | None = None,
    width: int | None = None,
    height: int | None = None,
    error: str | None = None,
    raw_result: dict[str, Any] | None = None,
) -> ServeRunOutputSlot:
    return ServeRunOutputSlot(
        slot_id=slot.slot_id,
        run_id=slot.run_id,
        session_id=slot.session_id,
        scope_key=slot.scope_key,
        workflow=slot.workflow,
        contract=slot.contract,
        output_name=slot.output_name,
        output_type=output_type or slot.output_type,
        status=status,
        prompt_id=prompt_id or slot.prompt_id,
        width=width if width is not None else slot.width,
        height=height if height is not None else slot.height,
        error=error,
        raw_result=raw_result,
        created_at=slot.created_at,
    )


def _slot_id(run_id: str, index: int, output_name: str) -> str:
    safe_name = _safe_token(output_name) or "output"
    return f"slot_{run_id}_{index}_{safe_name}"


def _gallery_item_id_for_slot(slot: ServeRunOutputSlot) -> str:
    if slot.slot_id.startswith(f"slot_{slot.run_id}_0_"):
        return f"gallery_{slot.run_id}"
    return f"gallery_{slot.slot_id}"


def _slot_output_type(output_type: str) -> str:
    normalized = output_type.lower()
    return normalized if normalized in {"image", "video", "audio", "json"} else "json"


def _fallback_dimensions_for_type(output_type: str) -> tuple[int, int]:
    return (4, 1) if output_type == "audio" else (1, 1)


def _gallery_dimensions_for_artifact(item_type: str, artifact: Mapping[str, Any]) -> tuple[int, int]:
    if item_type == "audio":
        return (4, 1)
    if item_type in {"image", "video"}:
        return artifact_dimensions(artifact)
    return (1, 1)


def _json_gallery_item_for_completed_run(
    *,
    run_id: str,
    session: ServeSession,
    workflow_name: str,
    contract_name: str,
    inputs: dict[str, Any],
    response: dict[str, Any],
    item_id: str,
    slot_id: str | None,
    created_at: str,
) -> ServeGalleryItem:
    return ServeGalleryItem(
        item_id=item_id,
        run_id=run_id,
        session_id=session.session_id,
        scope_key=session.scope_key,
        workflow=workflow_name,
        contract=contract_name,
        status="done",
        output_type="json",
        slot_id=slot_id,
        output_name="result",
        prompt_id=str(response.get("prompt_id") or "") or None,
        width=1,
        height=1,
        inputs=_display_inputs(inputs),
        raw_result=dict(response),
        created_at=created_at,
        updated_at=created_at,
    )


def _record_failed_run(
    state: ServeState,
    session: ServeSession,
    workflow_name: str,
    contract_name: str,
    body: dict[str, Any],
    payload: dict[str, Any],
    *,
    run_id: str | None = None,
    prompt_id: str | None = None,
    gallery_item_id: str | None = None,
    output_slots: list[ServeRunOutputSlot] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or f"run_{uuid.uuid4().hex}"
    created_at = created_at or utc_now()
    inputs = _extract_run_inputs(body)
    message = str(payload.get("message") or payload.get("error") or "Generation failed")
    raw_result = dict(payload)
    state.state_store.record_run(
        ServeRunRecord(
            run_id=run_id,
            session_id=session.session_id,
            scope_key=session.scope_key,
            workflow=workflow_name,
            contract=contract_name,
            status="error",
            inputs=_display_inputs(inputs),
            prompt_id=prompt_id,
            raw_result=raw_result,
            error=message,
            created_at=created_at,
        )
    )
    slots = output_slots or []
    errored_slots: list[ServeRunOutputSlot] = []
    if slots:
        errored_slots = [
            _copy_output_slot(slot, status="error", prompt_id=prompt_id, error=message, raw_result=raw_result)
            for slot in slots
        ]
        state.state_store.record_output_slots(errored_slots)
        gallery_items = _error_gallery_items_for_slots(
            errored_slots,
            inputs=inputs,
            raw_result=raw_result,
            message=message,
        )
    else:
        gallery_items = [
            ServeGalleryItem(
                item_id=gallery_item_id or f"gallery_{uuid.uuid4().hex}",
                run_id=run_id,
                session_id=session.session_id,
                scope_key=session.scope_key,
                workflow=workflow_name,
                contract=contract_name,
                status="error",
                output_type="image",
                inputs=_display_inputs(inputs),
                prompt_id=prompt_id,
                width=1,
                height=1,
                raw_result=raw_result,
                error=message,
                created_at=created_at,
                updated_at=created_at,
            )
        ]
    state.state_store.record_gallery_items(gallery_items)
    return {
        "run_id": run_id,
        "output_slots": [slot.to_public_dict() for slot in errored_slots],
        "gallery_items": [item.to_public_dict() for item in gallery_items],
    }


def _error_gallery_items_for_slots(
    slots: list[ServeRunOutputSlot],
    *,
    inputs: dict[str, Any],
    raw_result: dict[str, Any],
    message: str,
) -> list[ServeGalleryItem]:
    display_inputs = _display_inputs(inputs)
    return [
        ServeGalleryItem(
            item_id=_gallery_item_id_for_slot(slot),
            run_id=slot.run_id,
            session_id=slot.session_id,
            scope_key=slot.scope_key,
            workflow=slot.workflow,
            contract=slot.contract,
            status="error",
            output_type=slot.output_type if slot.output_type in {"image", "video", "audio", "json"} else "image",
            slot_id=slot.slot_id,
            output_name=slot.output_name,
            inputs=display_inputs,
            prompt_id=slot.prompt_id,
            width=slot.width,
            height=slot.height,
            raw_result=raw_result,
            error=message,
            created_at=slot.created_at,
            updated_at=slot.created_at,
        )
        for slot in slots
    ]


def _empty_gallery_items_for_slots(
    slots: list[ServeRunOutputSlot],
    *,
    existing_items: list[ServeGalleryItem],
    inputs: dict[str, Any],
    response: dict[str, Any],
) -> list[ServeGalleryItem]:
    existing_slot_ids = {item.slot_id for item in existing_items if item.slot_id}
    display_inputs = _display_inputs(inputs)
    return [
        ServeGalleryItem(
            item_id=_gallery_item_id_for_slot(slot),
            run_id=slot.run_id,
            session_id=slot.session_id,
            scope_key=slot.scope_key,
            workflow=slot.workflow,
            contract=slot.contract,
            status="done",
            output_type="json",
            slot_id=slot.slot_id,
            output_name=slot.output_name,
            inputs=display_inputs,
            prompt_id=slot.prompt_id,
            width=1,
            height=1,
            raw_result=dict(response),
            created_at=slot.created_at,
            updated_at=slot.created_at,
        )
        for slot in slots
        if slot.status == "empty" and slot.slot_id not in existing_slot_ids
    ]


def _gallery_items_for_outputs(
    *,
    run_id: str,
    session: ServeSession,
    workflow_name: str,
    contract_name: str,
    inputs: dict[str, Any],
    response: dict[str, Any],
    output_slots: list[ServeRunOutputSlot] | None = None,
    created_at: str | None = None,
) -> list[ServeGalleryItem]:
    items: list[ServeGalleryItem] = []
    display_inputs = _display_inputs(inputs)
    prompt_id = str(response.get("prompt_id") or "")
    created_at = created_at or utc_now()
    raw_result = dict(response)
    slots = output_slots or []
    for output_index, output in enumerate(response.get("outputs") or []):
        if not isinstance(output, Mapping):
            continue
        slot = slots[output_index] if output_index < len(slots) else None
        output_name = str(output.get("name") or "output")
        output_type = str(output.get("type") or "json").lower()
        artifacts = output.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact_index, artifact in enumerate(artifacts):
            if not isinstance(artifact, Mapping):
                continue
            artifact_payload = dict(artifact)
            filename = artifact_payload.get("filename")
            item_type = output_kind(output_type, str(filename or ""))
            width, height = _gallery_dimensions_for_artifact(item_type, artifact_payload)
            item_id = _gallery_item_id_for_slot(slot) if slot and artifact_index == 0 else f"gallery_{uuid.uuid4().hex}"
            items.append(
                ServeGalleryItem(
                    item_id=item_id,
                    run_id=run_id,
                    session_id=session.session_id,
                    scope_key=session.scope_key,
                    workflow=workflow_name,
                    contract=contract_name,
                    status="done",
                    output_type=item_type,
                    slot_id=slot.slot_id if slot else None,
                    output_name=output_name,
                    prompt_id=prompt_id or None,
                    filename=str(filename) if filename else None,
                    url=str(artifact_payload.get("url")) if artifact_payload.get("url") else None,
                    width=width if item_type in {"image", "video", "audio"} else 1,
                    height=height if item_type in {"image", "video", "audio"} else 1,
                    inputs=display_inputs,
                    artifact=artifact_payload,
                    raw_result=raw_result,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
    return items


def _extract_run_inputs(body: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(body.get("inputs"), dict):
        return dict(body["inputs"])
    control_keys = {"wait", "timeout_seconds", "poll_interval_seconds"}
    return {key: value for key, value in body.items() if key not in control_keys}


def _display_inputs(inputs: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _display_value(value) for key, value in inputs.items()}


def _display_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if value.get("kind") == "file_ref":
            return {
                key: value.get(key)
                for key in ("kind", "ref", "filename", "mime_type", "size")
                if key in value
            }
        return {str(key): _display_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_display_value(child) for child in value]
    if isinstance(value, str) and value.startswith("data:"):
        return f"{value[:48]}... [inline data omitted]"
    return value


async def _prepare_contract_inputs(
    state: ServeState,
    workflow_name: str,
    contract_name: str,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    return (await _prepare_contract_run_inputs(state, workflow_name, contract_name, inputs)).inputs


async def _prepare_contract_run_inputs(
    state: ServeState,
    workflow_name: str,
    contract_name: str,
    inputs: dict[str, Any],
) -> PreparedContractInputs:
    """Resolve uploaded media refs before building the ComfyUI prompt."""

    manifest = state.manifest_snapshot()
    workflow = manifest.workflows.get(workflow_name)
    execution_contract = getattr(workflow, "execution_contract", None) if workflow else None
    contract = execution_contract.contracts.get(contract_name) if execution_contract else None
    if contract is None:
        return PreparedContractInputs(dict(inputs))

    prepared = dict(inputs)
    staged_uploads: list[StagedUpload] = []
    for contract_input in contract.inputs:
        if str(contract_input.type).lower() not in FILE_UPLOAD_CONTRACT_INPUT_TYPES:
            continue
        if contract_input.name not in prepared:
            continue
        resolved, record = _resolve_upload_binding(
            state,
            prepared[contract_input.name],
            input_name=contract_input.name,
        )
        prepared[contract_input.name] = resolved
        if record is not None:
            staged_upload = _staged_upload_from_record(contract_input.name, record)
            if staged_upload is not None:
                staged_uploads.append(staged_upload)
    return PreparedContractInputs(prepared, tuple(staged_uploads))


def _staged_upload_from_record(input_name: str, record: Any) -> StagedUpload | None:
    path = getattr(record, "path", None)
    filename = getattr(record, "filename", None)
    content_type = getattr(record, "content_type", None)
    comfyui_filename = getattr(record, "comfyui_filename", None)
    if path is None or filename is None or content_type is None or comfyui_filename is None:
        return None
    return StagedUpload(
        input_name=input_name,
        path=Path(path),
        filename=str(filename),
        content_type=str(content_type),
        size=getattr(record, "size", None),
        comfyui_filename=str(comfyui_filename),
    )


def _prepare_upload_slot(state: ServeState, body: Mapping[str, Any]) -> UploadRecord:
    requested_content_type = _canonical_content_type(body.get("mime_type") or body.get("content_type"))
    filename = _safe_upload_filename(body.get("filename"), requested_content_type)
    content_type = requested_content_type or _content_type_for_filename(filename)
    size = _optional_positive_int(body.get("size"))
    max_bytes = _max_request_bytes(state)
    if size is not None and size > max_bytes:
        raise ValueError(f"Upload is too large. This cg serve instance accepts files up to {max_bytes} bytes.")

    upload_id = f"upload_{uuid.uuid4().hex}"
    stored_filename = f"{upload_id}_{filename}"
    input_dir = _comfyui_input_dir(state.env)
    record = UploadRecord(
        upload_id=upload_id,
        token=secrets.token_urlsafe(UPLOAD_TOKEN_BYTES),
        filename=filename,
        content_type=content_type,
        size=size,
        path=input_dir / stored_filename,
        comfyui_filename=stored_filename,
    )
    state.uploads[upload_id] = record
    return record


def _resolve_upload_ref(state: ServeState, value: Any, *, input_name: str) -> Any:
    return _resolve_upload_binding(state, value, input_name=input_name)[0]


def _resolve_upload_binding(state: ServeState, value: Any, *, input_name: str) -> tuple[Any, UploadRecord | None]:
    if isinstance(value, str):
        if value.startswith("data:"):
            raise ValueError(
                f"Input '{input_name}' uses an inline data URL. Upload the file first and submit a file_ref."
            )
        return value, None

    if not isinstance(value, Mapping):
        return value, None

    if value.get("kind") == "file_ref":
        upload_id = value.get("ref") or value.get("upload_id")
        if not isinstance(upload_id, str) or not upload_id:
            raise ValueError(f"Input '{input_name}' file_ref is missing a ref.")
        record = state.uploads.get(upload_id)
        if record is None:
            raise ValueError(f"Input '{input_name}' references an unknown upload.")
        if record.status != "ready":
            raise ValueError(f"Input '{input_name}' references an upload that is not ready.")
        return record.comfyui_filename, record

    if any(key in value for key in ("data_url", "base64", "data")):
        raise ValueError(
            f"Input '{input_name}' uses inline file bytes. Upload the file first and submit a file_ref."
        )

    return value, None


def _safe_upload_filename(value: Any, content_type: Any = None) -> str:
    raw = str(value or "").strip().replace("\\", "/").split("/")[-1]
    safe = "".join(char for char in raw if char.isalnum() or char in {"-", "_", "."}).strip(" .")
    if safe and "." in safe and any(char.isalnum() for char in safe):
        return safe
    return _generated_upload_filename(str(content_type or ""), stem=safe or None)


def _generated_upload_filename(content_type: str, stem: str | None = None) -> str:
    extension = _extension_for_content_type(content_type)
    return f"{stem or f'comfygit-upload-{uuid.uuid4().hex}'}{extension}"


def _content_type_for_filename(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    return UPLOAD_MIME_TYPE_BY_EXTENSION.get(extension, DEFAULT_UPLOAD_CONTENT_TYPE)


def _extension_for_content_type(content_type: str) -> str:
    return UPLOAD_EXTENSION_BY_MIME_TYPE.get(
        _canonical_content_type(content_type),
        DEFAULT_UPLOAD_EXTENSION,
    )


def _canonical_content_type(value: Any) -> str:
    content_type = str(value or "").split(";", 1)[0].strip().lower()
    return UPLOAD_MIME_TYPE_ALIASES.get(content_type, content_type)


def _optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _comfyui_input_dir(env: Environment) -> Path:
    comfyui_path = Path(getattr(env, "comfyui_path", Path(getattr(env, "path", ".")) / "ComfyUI"))
    return comfyui_path / "input"


def _upload_too_large_response(max_bytes: int) -> web.Response:
    max_mib = max_bytes // (1024 * 1024)
    return web.json_response(
        {
            "error": "request_too_large",
            "message": f"Upload is too large. This cg serve instance accepts uploads up to {max_mib} MiB.",
        },
        status=413,
    )
