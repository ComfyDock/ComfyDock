"""Contract-serving runtime for ComfyGit environments."""

from __future__ import annotations

import asyncio
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web
from comfygit_core.core.environment import Environment
from comfygit_core.models.workflow_contract import NamedWorkflowContract
from comfygit_core.services.workflow_execution import build_manifest_contract_prompt

from .serve_executor import (
    ComfyGitServeTimeoutError,
    ComfyUIClient,
    ComfyUIRequestError,
    LocalComfyExecutor,
    RunExecutionRequest,
    RunExecutor,
    artifact_dimensions,
    output_kind,
)
from .serve_state import (
    EphemeralServeStateStore,
    ServeGalleryItem,
    ServeRunRecord,
    ServeRunOutputSlot,
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
        self.executor: RunExecutor = LocalComfyExecutor(self.client)
        self.uploads: dict[str, UploadRecord] = {}
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
            app = create_app(state)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, config.host, config.port)
            await site.start()
            print(f"Serving ComfyGit environment '{env.name}' on http://{config.host}:{config.port}")
            print(f"ComfyUI API target: {config.comfy_url}")
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
    app.router.add_post("/contracts/{workflow}/{contract}/run", run_contract_handler)
    app.router.add_get("/outputs/view", output_view_handler)
    app.router.add_get("/{tail:.*}", studio_index_handler)
    app.on_startup.append(_recover_active_runs_on_startup)
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


def _studio_static_dir() -> Path:
    return Path(str(resources.files("comfygit_cli").joinpath("contract_studio_static")))


async def studio_index_handler(request: web.Request) -> web.StreamResponse:
    static_dir = request.app[STUDIO_STATIC_DIR_KEY]
    index_path = static_dir / "index.html"
    if index_path.exists():
        return web.FileResponse(index_path)
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
    payload: dict[str, Any] = {
        "ok": True,
        "environment": state.env.name,
        "comfy_url": state.config.comfy_url,
        "comfyui": {"available": False},
    }
    try:
        await state.client.check_health()
        payload["comfyui"] = {"available": True}
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        payload["comfyui"] = {"available": False, "error": str(exc)}
    return web.json_response(payload)


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
    if not isinstance(prompt_id, str) or not prompt_id:
        return _json_response_for_session(
            {
                "error": "run_not_cancellable",
                "message": f"Run '{run_id}' does not have a ComfyUI prompt id yet.",
                "run": run,
            },
            session,
            status=409,
        )

    try:
        await state.executor.cancel(prompt_id)
    except ComfyUIRequestError as exc:
        return _json_response_for_session(
            {
                "error": "comfyui_rejected_cancel",
                "message": str(exc),
                "comfy_status": exc.status,
                "comfy_url": exc.url,
                "comfyui": exc.payload,
            },
            session,
            status=400 if exc.status == 400 else 502,
        )
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return _json_response_for_session(
            {
                "error": "comfyui_unavailable",
                "message": str(exc),
                "comfy_url": state.config.comfy_url,
            },
            session,
            status=502,
        )
    message = "Generation cancelled."
    raw_result = {
        "status": "cancelled",
        "run_id": run_id,
        "prompt_id": prompt_id,
        "message": message,
    }
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

    return _json_response_for_session(_cancelled_run_payload(state, session, run_id), session)


def _cancelled_run_payload(state: ServeState, session: ServeSession, run_id: str) -> dict[str, Any]:
    return {
        "status": "cancelled",
        "run_id": run_id,
        "run": state.state_store.get_run(session.scope_key, run_id),
        "output_slots": state.state_store.list_output_slots(session.scope_key, run_id),
        "gallery_items": state.state_store.list_gallery_items_for_run(session.scope_key, run_id),
    }


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
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        state = _state(request)
        payload = {
            "error": "comfyui_unavailable",
            "message": str(exc),
            "comfy_url": state.config.comfy_url,
        }
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
    inputs = await _prepare_contract_inputs(state, workflow_name, contract_name, inputs)
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
        pending_items = _pending_gallery_items_for_slots(
            output_slots,
            inputs=inputs,
            response=response,
        )
        state.state_store.record_output_slots(output_slots)
        state.state_store.record_gallery_items(pending_items)
        response["output_slots"] = [slot.to_public_dict() for slot in output_slots]
        response["gallery_items"] = [item.to_public_dict() for item in pending_items]
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
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        payload = {
            "error": "comfyui_unavailable",
            "message": str(exc),
            "comfy_url": state.config.comfy_url,
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
    """Resolve uploaded media refs before building the ComfyUI prompt."""

    manifest = state.manifest_snapshot()
    workflow = manifest.workflows.get(workflow_name)
    execution_contract = getattr(workflow, "execution_contract", None) if workflow else None
    contract = execution_contract.contracts.get(contract_name) if execution_contract else None
    if contract is None:
        return inputs

    prepared = dict(inputs)
    for contract_input in contract.inputs:
        if str(contract_input.type).lower() not in FILE_UPLOAD_CONTRACT_INPUT_TYPES:
            continue
        if contract_input.name not in prepared:
            continue
        prepared[contract_input.name] = _resolve_upload_ref(
            state,
            prepared[contract_input.name],
            input_name=contract_input.name,
        )
    return prepared


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
    if isinstance(value, str):
        if value.startswith("data:"):
            raise ValueError(
                f"Input '{input_name}' uses an inline data URL. Upload the file first and submit a file_ref."
            )
        return value

    if not isinstance(value, Mapping):
        return value

    if value.get("kind") == "file_ref":
        upload_id = value.get("ref") or value.get("upload_id")
        if not isinstance(upload_id, str) or not upload_id:
            raise ValueError(f"Input '{input_name}' file_ref is missing a ref.")
        record = state.uploads.get(upload_id)
        if record is None:
            raise ValueError(f"Input '{input_name}' references an unknown upload.")
        if record.status != "ready":
            raise ValueError(f"Input '{input_name}' references an upload that is not ready.")
        return record.comfyui_filename

    if any(key in value for key in ("data_url", "base64", "data")):
        raise ValueError(
            f"Input '{input_name}' uses inline file bytes. Upload the file first and submit a file_ref."
        )

    return value


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
