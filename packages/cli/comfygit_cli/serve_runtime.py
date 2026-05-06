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
from urllib.parse import urlencode

import aiohttp
from aiohttp import web
from comfygit_core.core.environment import Environment
from comfygit_core.models.workflow_contract import NamedWorkflowContract
from comfygit_core.services.workflow_execution import (
    build_manifest_contract_prompt,
    extract_contract_outputs,
)

DEFAULT_MAX_REQUEST_BYTES = 256 * 1024 * 1024
UPLOAD_TOKEN_BYTES = 32
DEFAULT_UPLOAD_CONTENT_TYPE = "application/octet-stream"
DEFAULT_UPLOAD_EXTENSION = ".bin"

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


class ComfyGitServeTimeoutError(Exception):
    """Raised when a submitted ComfyUI prompt does not finish in time."""


class ComfyUIRequestError(Exception):
    """Raised when ComfyUI returns a structured non-2xx API response."""

    def __init__(self, status: int, url: str, payload: Any) -> None:
        self.status = status
        self.url = url
        self.payload = payload
        super().__init__(_comfyui_error_message(payload) or f"ComfyUI returned HTTP {status}")


@dataclass(frozen=True)
class ServeConfig:
    """Configuration for the local ComfyGit serve adapter."""

    host: str
    port: int
    comfy_url: str
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES


class ComfyUIClient:
    """Small async HTTP client for the ComfyUI API used by `cg serve`."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session

    async def check_health(self) -> dict[str, Any]:
        return await self._request_json("GET", "/system_stats", timeout=2)

    async def submit_prompt(self, prompt: dict[str, dict[str, Any]]) -> str:
        payload = await self._request_json(
            "POST",
            "/prompt",
            json_data={"prompt": prompt},
        )
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI did not return a prompt_id: {payload}")
        return str(prompt_id)

    async def get_history(self, prompt_id: str) -> dict[str, Any] | None:
        payload = await self._request_json("GET", f"/history/{prompt_id}")
        if isinstance(payload, dict) and prompt_id in payload:
            history = payload[prompt_id]
            return history if isinstance(history, dict) else None
        return payload if isinstance(payload, dict) and payload else None

    async def fetch_output(
        self,
        params: Mapping[str, str],
    ) -> tuple[bytes, str, str | None]:
        url = f"{self.base_url}/view"
        request_timeout = aiohttp.ClientTimeout(total=self.timeout)
        if self._session is not None:
            return await self._fetch_output_with_session(
                self._session,
                url,
                params=params,
                timeout=request_timeout,
            )
        async with aiohttp.ClientSession() as session:
            return await self._fetch_output_with_session(
                session,
                url,
                params=params,
                timeout=request_timeout,
            )

    async def wait_for_history(
        self,
        prompt_id: str,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            history = await self.get_history(prompt_id)
            if history:
                return history
            await asyncio.sleep(poll_interval_seconds)
        raise ComfyGitServeTimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}")

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        data: aiohttp.FormData | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        request_timeout = aiohttp.ClientTimeout(total=timeout or self.timeout)
        if self._session is not None:
            return await self._request_json_with_session(
                self._session,
                method,
                url,
                json_data=json_data,
                data=data,
                timeout=request_timeout,
            )
        async with aiohttp.ClientSession() as session:
            return await self._request_json_with_session(
                session,
                method,
                url,
                json_data=json_data,
                data=data,
                timeout=request_timeout,
            )

    async def _request_json_with_session(
        self,
        session: aiohttp.ClientSession,
        method: str,
        url: str,
        *,
        json_data: dict[str, Any] | None,
        data: aiohttp.FormData | None,
        timeout: aiohttp.ClientTimeout,
    ) -> dict[str, Any]:
        async with session.request(
            method,
            url,
            json=json_data,
            data=data,
            timeout=timeout,
        ) as response:
            payload = await _response_payload(response)
            if response.status >= 400:
                raise ComfyUIRequestError(response.status, url, payload)
        return payload if isinstance(payload, dict) else {}

    async def _fetch_output_with_session(
        self,
        session: aiohttp.ClientSession,
        url: str,
        *,
        params: Mapping[str, str],
        timeout: aiohttp.ClientTimeout,
    ) -> tuple[bytes, str, str | None]:
        async with session.get(url, params=params, timeout=timeout) as response:
            response.raise_for_status()
            body = await response.read()
            content_type = response.headers.get("content-type") or "application/octet-stream"
            disposition = response.headers.get("content-disposition")
        return body, content_type, disposition


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
    ) -> None:
        self.env = env
        self.config = config
        self.client = ComfyUIClient(config.comfy_url, session=session)
        self.uploads: dict[str, UploadRecord] = {}

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
        app = create_app(state)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, config.host, config.port)
        await site.start()
        print(f"Serving ComfyGit environment '{env.name}' on http://{config.host}:{config.port}")
        print(f"ComfyUI API target: {config.comfy_url}")
        print("Press Ctrl+C to stop.")
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()


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
    app.router.add_post("/contracts/{workflow}/{contract}/run", run_contract_handler)
    app.router.add_get("/outputs/view", output_view_handler)
    app.router.add_get("/{tail:.*}", studio_index_handler)
    return app


def _max_request_bytes(state: ServeState) -> int:
    value = getattr(getattr(state, "config", None), "max_request_bytes", DEFAULT_MAX_REQUEST_BYTES)
    return value if isinstance(value, int) and value > 0 else DEFAULT_MAX_REQUEST_BYTES


def _state(request: web.Request) -> ServeState:
    return request.app[SERVE_STATE_KEY]


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


async def run_contract_handler(request: web.Request) -> web.Response:
    try:
        payload = await _run_contract(
            _state(request),
            request.match_info["workflow"],
            request.match_info["contract"],
            await _read_json_body(request),
        )
        status = 400 if payload.get("status") == "invalid_request" else 200
        return web.json_response(payload, status=status)
    except web.HTTPRequestEntityTooLarge:
        state = _state(request)
        max_mib = _max_request_bytes(state) // (1024 * 1024)
        return web.json_response(
            {
                "error": "request_too_large",
                "message": (
                    f"Request body is too large. This cg serve instance accepts "
                    f"contract requests up to {max_mib} MiB."
                ),
            },
            status=413,
        )
    except ComfyGitServeTimeoutError as exc:
        return web.json_response({"error": "timeout", "message": str(exc)}, status=504)
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
        state = _state(request)
        return web.json_response(
            {
                "error": "comfyui_unavailable",
                "message": str(exc),
                "comfy_url": state.config.comfy_url,
            },
            status=502,
        )
    except ValueError as exc:
        return web.json_response({"error": "bad_request", "message": str(exc)}, status=400)
    except Exception as exc:
        return web.json_response({"error": "internal_error", "message": str(exc)}, status=500)


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
        body, content_type, disposition = await _state(request).client.fetch_output(params)
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
    headers = {"Content-Type": content_type}
    if disposition:
        headers["Content-Disposition"] = disposition
    return web.Response(body=body, headers=headers)


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


async def _response_payload(response: aiohttp.ClientResponse) -> Any:
    content_type = response.headers.get("content-type", "")
    if "json" in content_type.lower():
        return await response.json(content_type=None)
    text = await response.text()
    return {"message": text} if text else {}


def _comfyui_error_message(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return str(payload) if payload else ""
    error = payload.get("error")
    if isinstance(error, Mapping):
        message = str(error.get("message") or error.get("type") or "")
    else:
        message = str(payload.get("message") or error or "")
    detail = _first_comfyui_node_error_detail(payload)
    if message and detail:
        return f"{message}: {detail}"
    return detail or message


def _first_comfyui_node_error_detail(payload: Mapping[str, Any]) -> str:
    node_errors = payload.get("node_errors")
    if not isinstance(node_errors, Mapping):
        return ""
    for node_error in node_errors.values():
        if not isinstance(node_error, Mapping):
            continue
        errors = node_error.get("errors")
        if not isinstance(errors, list):
            continue
        for error in errors:
            if not isinstance(error, Mapping):
                continue
            detail = error.get("details") or error.get("message")
            if detail:
                return str(detail)
    return ""


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
    wait = bool(body.get("wait", True))
    timeout_seconds = float(body.get("timeout_seconds", 300))
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
        return {
            "status": "invalid_request",
            "issues": [asdict(issue) for issue in build_result.issues],
        }

    _stamp_output_cache_busters(build_result.prompt, build_result.outputs, uuid.uuid4().hex[:10])
    prompt_id = await state.client.submit_prompt(build_result.prompt)
    response: dict[str, Any] = {
        "status": "submitted",
        "prompt_id": prompt_id,
        "issues": [asdict(issue) for issue in build_result.issues],
    }
    if not wait:
        return response

    history = await state.client.wait_for_history(
        prompt_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    outputs = extract_contract_outputs(build_result.outputs, history)
    response.update(
        {
            "status": "completed",
            "outputs": [_contract_output_payload(output) for output in outputs],
        }
    )
    return response


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
        if str(contract_input.type).lower() != "image":
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


def _stamp_output_cache_busters(
    prompt: dict[str, dict[str, Any]],
    outputs: tuple[Any, ...],
    token: str,
) -> None:
    """Force artifact-producing output nodes to re-run for each contract request.

    ComfyUI can mark a whole prompt as cached when input values repeat. When
    `SaveImage` is cached, history may contain no `outputs` entry even though
    execution reports success. Stamping the filename prefix preserves upstream
    cache reuse while making the output node produce fresh artifact metadata.
    """

    safe_token = "".join(char for char in token if char.isalnum() or char in {"-", "_"}) or "run"
    for output in outputs:
        if str(getattr(output, "type", "")).lower() != "image":
            continue
        node_id = str(getattr(output, "node_id", ""))
        node = prompt.get(node_id)
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type", "")) != "SaveImage":
            continue
        inputs = node.setdefault("inputs", {})
        if not isinstance(inputs, dict) or "filename_prefix" not in inputs:
            continue
        prefix = str(inputs.get("filename_prefix") or "ComfyUI")
        inputs["filename_prefix"] = f"{prefix}_{safe_token}"


def _contract_output_payload(output: Any) -> dict[str, Any]:
    payload = asdict(output)
    artifacts = []
    for artifact in output.artifacts:
        item = asdict(artifact)
        filename = item.get("filename")
        if filename:
            item["url"] = _artifact_view_url(item)
        artifacts.append(item)
    payload["artifacts"] = artifacts
    return payload


def _artifact_view_url(artifact: Mapping[str, Any]) -> str:
    query = urlencode(
        {
            "filename": str(artifact.get("filename") or ""),
            "subfolder": str(artifact.get("subfolder") or ""),
            "type": str(artifact.get("type") or "output"),
        }
    )
    return f"/outputs/view?{query}"
