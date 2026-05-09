"""Execution strategies for the ComfyGit serve runtime."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import struct
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlencode

import aiohttp
from comfygit_core.models.workflow_contract import WorkflowContractOutput
from comfygit_core.services.workflow_execution import extract_contract_outputs

OUTPUT_RESPONSE_HEADERS = (
    "accept-ranges",
    "content-range",
    "etag",
    "last-modified",
)
COMFYUI_CLIENT_ID_PREFIX = "comfygit-serve"
PROXY_AUTH_HEADER = "Authorization"


class ComfyGitServeTimeoutError(Exception):
    """Raised when a submitted ComfyUI prompt does not finish in time."""


class ComfyUIRequestError(Exception):
    """Raised when ComfyUI returns a structured non-2xx API response."""

    def __init__(self, status: int, url: str, payload: Any) -> None:
        self.status = status
        self.url = url
        self.payload = payload
        super().__init__(_comfyui_error_message(payload) or f"ComfyUI returned HTTP {status}")


class ComfyUIExecutionError(Exception):
    """Raised when ComfyUI accepts a prompt but history reports execution failure."""

    def __init__(self, prompt_id: str, history: Mapping[str, Any], message: str) -> None:
        self.prompt_id = prompt_id
        self.history = history
        self.payload = _comfyui_history_error_payload(prompt_id, history, message)
        super().__init__(message)


@dataclass(frozen=True)
class StagedUpload:
    """A front-door uploaded file that must be staged into a runtime proxy."""

    input_name: str
    path: Path
    filename: str
    content_type: str
    size: int | None
    comfyui_filename: str


@dataclass(frozen=True)
class RunExecutionRequest:
    """A contract prompt ready to execute through a serve executor."""

    prompt: dict[str, dict[str, Any]]
    outputs: tuple[Any, ...]
    wait: bool
    timeout_seconds: float
    poll_interval_seconds: float
    cache_token: str
    on_submitted: Callable[[str], Awaitable[None]] | None = None
    staged_uploads: tuple[StagedUpload, ...] = ()
    callback_run_id: str | None = None
    callback_url: str | None = None
    callback_token: str | None = None


@dataclass(frozen=True)
class RunExecutionResult:
    """Executor result normalized back into the serve contract shape."""

    status: str
    prompt_id: str
    outputs: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ServeOutputResponse:
    """Raw ComfyUI output response data proxied through `cg serve`."""

    body: bytes
    content_type: str
    disposition: str | None = None
    status: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)


class RunExecutor(Protocol):
    """Serve-owned execution strategy boundary."""

    async def execute(self, request: RunExecutionRequest) -> RunExecutionResult:
        """Execute a contract prompt and return normalized output payloads."""
        ...

    async def complete_submitted(
        self,
        prompt_id: str,
        outputs: tuple[Any, ...],
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> RunExecutionResult:
        """Wait for a previously submitted prompt and normalize its outputs."""
        ...

    async def cancel(self, prompt_id: str) -> None:
        """Request cancellation for a previously submitted prompt."""
        ...


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
            json_data={"prompt": prompt, "client_id": _new_comfyui_client_id()},
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

    async def delete_queued_prompt(self, prompt_id: str) -> None:
        await self._request_json("POST", "/queue", json_data={"delete": [prompt_id]})

    async def interrupt_prompt(self, prompt_id: str) -> None:
        await self._request_json("POST", "/interrupt", json_data={"prompt_id": prompt_id})

    async def fetch_output(
        self,
        params: Mapping[str, str],
        request_headers: Mapping[str, str] | None = None,
    ) -> ServeOutputResponse:
        url = f"{self.base_url}/view"
        request_timeout = aiohttp.ClientTimeout(total=self.timeout)
        if self._session is not None:
            return await self._fetch_output_with_session(
                self._session,
                url,
                params=params,
                request_headers=request_headers,
                timeout=request_timeout,
            )
        async with aiohttp.ClientSession() as session:
            return await self._fetch_output_with_session(
                session,
                url,
                params=params,
                request_headers=request_headers,
                timeout=request_timeout,
            )

    def output_view_url(self, params: Mapping[str, str]) -> str:
        return f"{self.base_url}/view?{urlencode(params)}"

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
        request_headers: Mapping[str, str] | None,
        timeout: aiohttp.ClientTimeout,
    ) -> ServeOutputResponse:
        async with session.get(url, params=params, headers=request_headers, timeout=timeout) as response:
            response.raise_for_status()
            body = await response.read()
            content_type = response.headers.get("content-type") or "application/octet-stream"
            disposition = response.headers.get("content-disposition")
            headers = {
                name: response.headers[name]
                for name in OUTPUT_RESPONSE_HEADERS
                if name in response.headers
            }
            status = response.status
        return ServeOutputResponse(
            body=body,
            content_type=content_type,
            disposition=disposition,
            status=status,
            headers=headers,
        )


class LocalComfyExecutor:
    """Run contract prompts against the configured local ComfyUI HTTP API."""

    def __init__(self, client: ComfyUIClient, *, artifact_dir: Path | None = None) -> None:
        self._client = client
        self._artifact_dir = artifact_dir

    async def execute(self, request: RunExecutionRequest) -> RunExecutionResult:
        _stamp_output_cache_busters(request.prompt, request.outputs, request.cache_token)
        prompt_id = await self._client.submit_prompt(request.prompt)
        if request.on_submitted is not None:
            await request.on_submitted(prompt_id)
        if not request.wait:
            return RunExecutionResult(status="submitted", prompt_id=prompt_id)

        return await self.complete_submitted(
            prompt_id,
            request.outputs,
            timeout_seconds=request.timeout_seconds,
            poll_interval_seconds=request.poll_interval_seconds,
        )

    async def complete_submitted(
        self,
        prompt_id: str,
        outputs: tuple[Any, ...],
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> RunExecutionResult:
        history = await self._client.wait_for_history(
            prompt_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        error_message = _comfyui_history_error_message(history)
        if error_message:
            raise ComfyUIExecutionError(prompt_id, history, error_message)
        extracted_outputs = extract_contract_outputs(outputs, history)
        output_payloads = [_contract_output_payload(output) for output in extracted_outputs]
        await _attach_artifact_dimensions(self._client, output_payloads)
        if self._artifact_dir is not None:
            await _localize_client_outputs(
                self._client,
                prompt_id,
                output_payloads,
                self._artifact_dir,
                temp_only=True,
            )
        return RunExecutionResult(status="completed", prompt_id=prompt_id, outputs=output_payloads)

    async def cancel(self, prompt_id: str) -> None:
        await self._client.delete_queued_prompt(prompt_id)
        await self._client.interrupt_prompt(prompt_id)


class ProxyComfyExecutor:
    """Run contract prompts through a remote `cg serve --role proxy` runtime."""

    def __init__(
        self,
        base_url: str,
        *,
        session: aiohttp.ClientSession | None = None,
        token: str | None = None,
        artifact_dir: Path,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = session
        self._token = token
        self._artifact_dir = artifact_dir

    async def check_health(self) -> dict[str, Any]:
        return await self._request_json("GET", "/proxy/health", timeout=5)

    async def execute(self, request: RunExecutionRequest) -> RunExecutionResult:
        _stamp_output_cache_busters(request.prompt, request.outputs, request.cache_token)
        payload = {
            "prompt": request.prompt,
            "outputs": [_workflow_contract_output_payload(output) for output in request.outputs],
            "wait": request.wait,
            "timeout_seconds": request.timeout_seconds,
            "poll_interval_seconds": request.poll_interval_seconds,
            "cache_token": request.cache_token,
            "uploads": [_staged_upload_payload(upload, index) for index, upload in enumerate(request.staged_uploads)],
        }
        if request.callback_run_id and request.callback_url:
            callback_payload: dict[str, Any] = {
                "run_id": request.callback_run_id,
                "url": request.callback_url,
            }
            if request.callback_token:
                callback_payload["token"] = request.callback_token
            payload["callback"] = callback_payload
        response = await self._post_run(payload, request.staged_uploads, timeout_seconds=request.timeout_seconds)
        prompt_id = str(response.get("prompt_id") or "")
        if not prompt_id:
            raise RuntimeError(f"Proxy runtime did not return a prompt_id: {response}")
        if request.on_submitted is not None:
            await request.on_submitted(prompt_id)
        if not request.wait:
            return RunExecutionResult(status=str(response.get("status") or "submitted"), prompt_id=prompt_id)
        return await self.complete_submitted(
            prompt_id,
            request.outputs,
            timeout_seconds=request.timeout_seconds,
            poll_interval_seconds=request.poll_interval_seconds,
        )

    async def complete_submitted(
        self,
        prompt_id: str,
        outputs: tuple[Any, ...],
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> RunExecutionResult:
        del outputs
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            payload = await self._request_json("GET", f"/proxy/runs/{prompt_id}", timeout=10)
            status = str(payload.get("status") or "").lower()
            if status == "completed":
                output_payloads = [
                    dict(output)
                    for output in payload.get("outputs", [])
                    if isinstance(output, Mapping)
                ]
                await self._localize_proxy_outputs(prompt_id, output_payloads)
                return RunExecutionResult(status="completed", prompt_id=prompt_id, outputs=output_payloads)
            if status in {"error", "failed"}:
                message = str(payload.get("message") or payload.get("error") or "Proxy execution failed")
                raise ComfyUIExecutionError(prompt_id, payload, message)
            if status == "cancelled":
                return RunExecutionResult(status="cancelled", prompt_id=prompt_id)
            await asyncio.sleep(poll_interval_seconds)
        raise ComfyGitServeTimeoutError(f"Timed out waiting for proxy prompt {prompt_id}")

    async def cancel(self, prompt_id: str) -> None:
        await self._request_json("POST", f"/proxy/runs/{prompt_id}/cancel", timeout=10)

    async def _post_run(
        self,
        payload: Mapping[str, Any],
        staged_uploads: tuple[StagedUpload, ...],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if not staged_uploads:
            return await self._request_json("POST", "/proxy/runs", json_data=dict(payload), timeout=timeout_seconds)

        form = aiohttp.FormData()
        form.add_field("payload", json.dumps(payload), content_type="application/json")
        handles = []
        try:
            for index, upload in enumerate(staged_uploads):
                handle = upload.path.open("rb")
                handles.append(handle)
                form.add_field(
                    f"file_{index}",
                    handle,
                    filename=upload.comfyui_filename,
                    content_type=upload.content_type,
                )
            return await self._request_json("POST", "/proxy/runs", data=form, timeout=timeout_seconds)
        finally:
            for handle in handles:
                handle.close()

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
        request_timeout = aiohttp.ClientTimeout(total=timeout or 10)
        headers = self._headers()
        if self._session is not None:
            return await self._request_json_with_session(
                self._session,
                method,
                url,
                json_data=json_data,
                data=data,
                headers=headers,
                timeout=request_timeout,
            )
        async with aiohttp.ClientSession() as session:
            return await self._request_json_with_session(
                session,
                method,
                url,
                json_data=json_data,
                data=data,
                headers=headers,
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
        headers: Mapping[str, str],
        timeout: aiohttp.ClientTimeout,
    ) -> dict[str, Any]:
        async with session.request(
            method,
            url,
            json=json_data,
            data=data,
            headers=headers,
            timeout=timeout,
        ) as response:
            payload = await _response_payload(response)
            if response.status >= 400:
                raise ComfyUIRequestError(response.status, url, payload)
        return payload if isinstance(payload, dict) else {}

    async def _fetch_artifact(self, artifact_id: str) -> ServeOutputResponse:
        url = f"{self.base_url}/proxy/artifacts/{quote(artifact_id, safe='')}"
        request_timeout = aiohttp.ClientTimeout(total=60)
        headers = self._headers()
        if self._session is not None:
            return await self._fetch_artifact_with_session(self._session, url, headers, request_timeout)
        async with aiohttp.ClientSession() as session:
            return await self._fetch_artifact_with_session(session, url, headers, request_timeout)

    async def _fetch_artifact_with_session(
        self,
        session: aiohttp.ClientSession,
        url: str,
        headers: Mapping[str, str],
        timeout: aiohttp.ClientTimeout,
    ) -> ServeOutputResponse:
        async with session.get(url, headers=headers, timeout=timeout) as response:
            response.raise_for_status()
            return ServeOutputResponse(
                body=await response.read(),
                content_type=response.headers.get("content-type") or "application/octet-stream",
                disposition=response.headers.get("content-disposition"),
                status=response.status,
                headers={
                    name: response.headers[name]
                    for name in OUTPUT_RESPONSE_HEADERS
                    if name in response.headers
                },
            )

    async def _localize_proxy_outputs(self, prompt_id: str, outputs: list[dict[str, Any]]) -> None:
        for output_index, output in enumerate(outputs):
            artifacts = output.get("artifacts")
            if not isinstance(artifacts, list):
                continue
            for artifact_index, artifact in enumerate(artifacts):
                if not isinstance(artifact, dict):
                    continue
                artifact_id = str(artifact.get("proxy_artifact_id") or "")
                if not artifact_id:
                    continue
                response = await self._fetch_artifact(artifact_id)
                filename = _safe_artifact_filename(
                    artifact.get("filename"),
                    fallback=f"artifact_{output_index}_{artifact_index}{_extension_for_content_type(response.content_type)}",
                )
                ref = _write_local_artifact(self._artifact_dir, prompt_id, filename, response.body)
                artifact["serve_artifact"] = ref
                artifact["url"] = f"/outputs/view?serve_artifact={quote(ref, safe='/')}"
                artifact["content_type"] = response.content_type

    def _headers(self) -> dict[str, str]:
        if not self._token:
            return {}
        return {PROXY_AUTH_HEADER: f"Bearer {self._token}"}


def _new_comfyui_client_id() -> str:
    return f"{COMFYUI_CLIENT_ID_PREFIX}-{uuid.uuid4().hex}"


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


def _comfyui_history_error_message(history: Mapping[str, Any]) -> str:
    status = history.get("status")
    if not isinstance(status, Mapping):
        return ""
    status_str = str(status.get("status_str") or "").lower()
    execution_error = _first_execution_error(status)
    if status_str in {"error", "failed"} or execution_error:
        return execution_error or str(status.get("status_str") or "ComfyUI execution failed")
    return ""


def _first_execution_error(status: Mapping[str, Any]) -> str:
    messages = status.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in messages:
        if not isinstance(message, list | tuple) or len(message) < 2:
            continue
        event_type, event_payload = message[0], message[1]
        if event_type != "execution_error" or not isinstance(event_payload, Mapping):
            continue
        error_text = str(event_payload.get("exception_message") or event_payload.get("message") or "").strip()
        if not error_text:
            error_text = str(event_payload.get("exception_type") or "ComfyUI execution failed")
        node_type = event_payload.get("node_type")
        node_id = event_payload.get("node_id")
        if node_type and node_id:
            return f"{node_type} node {node_id} failed: {error_text}"
        if node_type:
            return f"{node_type} failed: {error_text}"
        return error_text
    return ""


def _comfyui_history_error_payload(
    prompt_id: str,
    history: Mapping[str, Any],
    message: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt_id": prompt_id,
        "message": message,
    }
    status = history.get("status")
    if isinstance(status, Mapping):
        payload["status"] = status
    outputs = history.get("outputs")
    if isinstance(outputs, Mapping):
        payload["outputs"] = outputs
    return payload


def output_kind(output_type: str, filename: str) -> str:
    lowered = filename.lower()
    normalized_type = output_type.lower()
    if normalized_type == "video" or lowered.endswith((".mp4", ".webm", ".mov", ".mkv")):
        return "video"
    if normalized_type == "audio" or lowered.endswith((".wav", ".mp3", ".m4a", ".flac", ".ogg")):
        return "audio"
    if normalized_type == "image" or lowered.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        return "image"
    return "json"


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


def _workflow_contract_output_payload(output: Any) -> dict[str, Any]:
    to_dict = getattr(output, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return dict(payload) if isinstance(payload, Mapping) else {}
    return {
        key: value
        for key in ("name", "type", "node_id", "display_name", "selector", "description")
        if (value := getattr(output, key, None)) is not None
    }


def workflow_contract_output_from_payload(payload: Mapping[str, Any]) -> WorkflowContractOutput:
    return WorkflowContractOutput.from_toml_dict(dict(payload))


async def _attach_artifact_dimensions(client: ComfyUIClient, outputs: list[dict[str, Any]]) -> None:
    for output in outputs:
        output_type = str(output.get("type") or "").lower()
        artifacts = output.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            filename = str(artifact.get("filename") or "")
            kind = output_kind(output_type, filename)
            if artifact_dimensions(artifact) != (1, 1):
                continue
            params = _artifact_view_params(artifact)
            if kind == "image":
                dimensions = await _image_dimensions_from_artifact(client, params)
            elif kind == "video":
                dimensions = await _video_dimensions_from_artifact(client, params)
            else:
                continue
            if dimensions is None:
                continue
            artifact["width"], artifact["height"] = dimensions


async def _localize_client_outputs(
    client: ComfyUIClient,
    prompt_id: str,
    outputs: list[dict[str, Any]],
    artifact_dir: Path,
    *,
    temp_only: bool,
) -> None:
    for output_index, output in enumerate(outputs):
        artifacts = output.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact_index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                continue
            if artifact.get("serve_artifact"):
                continue
            if temp_only and str(artifact.get("type") or "").lower() != "temp":
                continue
            try:
                response = await client.fetch_output(_artifact_view_params(artifact))
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                continue
            filename = _safe_artifact_filename(
                artifact.get("filename"),
                fallback=f"artifact_{output_index}_{artifact_index}{_extension_for_content_type(response.content_type)}",
            )
            ref = _write_local_artifact(artifact_dir, prompt_id, filename, response.body)
            artifact["serve_artifact"] = ref
            artifact["url"] = f"/outputs/view?serve_artifact={quote(ref, safe='/')}"
            artifact["content_type"] = response.content_type


async def _image_dimensions_from_artifact(
    client: ComfyUIClient,
    params: Mapping[str, str],
) -> tuple[int, int] | None:
    try:
        response = await client.fetch_output(params)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return None
    return _image_dimensions_from_bytes(response.body)


async def _video_dimensions_from_artifact(
    client: ComfyUIClient,
    params: Mapping[str, str],
) -> tuple[int, int] | None:
    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            client.output_view_url(params),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None

    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return None
    if process.returncode != 0:
        return None
    return _video_dimensions_from_ffprobe_json(stdout)


def _video_dimensions_from_ffprobe_json(data: bytes) -> tuple[int, int] | None:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    streams = payload.get("streams") if isinstance(payload, Mapping) else None
    if not isinstance(streams, list) or not streams:
        return None
    stream = streams[0]
    if not isinstance(stream, Mapping):
        return None
    width = _positive_int(stream.get("width"))
    height = _positive_int(stream.get("height"))
    if width is None or height is None:
        return None
    return (width, height)


def artifact_dimensions(artifact: Mapping[str, Any]) -> tuple[int, int]:
    width = _positive_int(artifact.get("width"))
    height = _positive_int(artifact.get("height"))
    if width is None or height is None:
        return (1, 1)
    return (width, height)


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _image_dimensions_from_bytes(body: bytes) -> tuple[int, int] | None:
    if body.startswith(b"\x89PNG\r\n\x1a\n") and len(body) >= 24:
        width, height = struct.unpack(">II", body[16:24])
        return (width, height) if width > 0 and height > 0 else None

    if body.startswith((b"GIF87a", b"GIF89a")) and len(body) >= 10:
        width, height = struct.unpack("<HH", body[6:10])
        return (width, height) if width > 0 and height > 0 else None

    if body.startswith(b"BM") and len(body) >= 26:
        width = abs(struct.unpack("<i", body[18:22])[0])
        height = abs(struct.unpack("<i", body[22:26])[0])
        return (width, height) if width > 0 and height > 0 else None

    if body.startswith(b"\xff\xd8"):
        return _jpeg_dimensions_from_bytes(body)

    if len(body) >= 30 and body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return _webp_dimensions_from_bytes(body)

    return None


def _jpeg_dimensions_from_bytes(body: bytes) -> tuple[int, int] | None:
    index = 2
    while index + 9 < len(body):
        if body[index] != 0xFF:
            index += 1
            continue
        while index < len(body) and body[index] == 0xFF:
            index += 1
        if index >= len(body):
            return None
        marker = body[index]
        index += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(body):
            return None
        segment_length = struct.unpack(">H", body[index : index + 2])[0]
        if segment_length < 2 or index + segment_length > len(body):
            return None
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if segment_length < 7:
                return None
            height, width = struct.unpack(">HH", body[index + 3 : index + 7])
            return (width, height) if width > 0 and height > 0 else None
        index += segment_length
    return None


def _webp_dimensions_from_bytes(body: bytes) -> tuple[int, int] | None:
    chunk_type = body[12:16]
    if chunk_type == b"VP8X" and len(body) >= 30:
        width = 1 + int.from_bytes(body[24:27], "little")
        height = 1 + int.from_bytes(body[27:30], "little")
        return (width, height) if width > 0 and height > 0 else None
    if chunk_type == b"VP8 " and len(body) >= 30:
        width = struct.unpack("<H", body[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", body[28:30])[0] & 0x3FFF
        return (width, height) if width > 0 and height > 0 else None
    if chunk_type == b"VP8L" and len(body) >= 25:
        b0, b1, b2, b3 = body[21:25]
        width = 1 + (((b1 & 0x3F) << 8) | b0)
        height = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        return (width, height) if width > 0 and height > 0 else None
    return None


def _artifact_view_url(artifact: Mapping[str, Any]) -> str:
    query = urlencode(_artifact_view_params(artifact))
    return f"/outputs/view?{query}"


def _artifact_view_params(artifact: Mapping[str, Any]) -> dict[str, str]:
    return {
        "filename": str(artifact.get("filename") or ""),
        "subfolder": str(artifact.get("subfolder") or ""),
        "type": str(artifact.get("type") or "output"),
    }


def _staged_upload_payload(upload: StagedUpload, index: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "field_name": f"file_{index}",
        "input_name": upload.input_name,
        "filename": upload.filename,
        "comfyui_filename": upload.comfyui_filename,
        "content_type": upload.content_type,
    }
    if upload.size is not None:
        payload["size"] = upload.size
    return payload


def _safe_artifact_filename(value: Any, *, fallback: str = "artifact.bin") -> str:
    raw = str(value or fallback).strip().replace("\\", "/").split("/")[-1]
    safe = "".join(char for char in raw if char.isalnum() or char in {"-", "_", "."}).strip(" .")
    return safe if safe and any(char.isalnum() for char in safe) else fallback


def _safe_artifact_path_segment(value: Any) -> str:
    return "".join(char for char in str(value or "") if char.isalnum() or char in {"-", "_"})


def _write_local_artifact(artifact_dir: Path, prompt_id: str, filename: str, body: bytes) -> str:
    safe_prompt_id = _safe_artifact_path_segment(prompt_id) or f"prompt_{uuid.uuid4().hex}"
    safe_filename = _safe_artifact_filename(filename)
    target_dir = artifact_dir / safe_prompt_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_filename
    if target_path.exists():
        stem = target_path.stem
        suffix = target_path.suffix
        target_path = target_dir / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"
        safe_filename = target_path.name
    temp_path = target_path.with_name(f".{target_path.name}.tmp")
    temp_path.write_bytes(body)
    temp_path.replace(target_path)
    return f"{safe_prompt_id}/{safe_filename}"


def _extension_for_content_type(content_type: str) -> str:
    extension = mimetypes.guess_extension(content_type.split(";", 1)[0].strip().lower())
    return extension or ".bin"
