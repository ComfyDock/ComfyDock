"""Execution strategies for the ComfyGit serve runtime."""

from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol
from urllib.parse import urlencode

import aiohttp
from comfygit_core.services.workflow_execution import extract_contract_outputs


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
class RunExecutionRequest:
    """A contract prompt ready to execute through a serve executor."""

    prompt: dict[str, dict[str, Any]]
    outputs: tuple[Any, ...]
    wait: bool
    timeout_seconds: float
    poll_interval_seconds: float
    cache_token: str
    on_submitted: Callable[[str], Awaitable[None]] | None = None


@dataclass(frozen=True)
class RunExecutionResult:
    """Executor result normalized back into the serve contract shape."""

    status: str
    prompt_id: str
    outputs: list[dict[str, Any]] = field(default_factory=list)


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
        timeout: aiohttp.ClientTimeout,
    ) -> tuple[bytes, str, str | None]:
        async with session.get(url, params=params, timeout=timeout) as response:
            response.raise_for_status()
            body = await response.read()
            content_type = response.headers.get("content-type") or "application/octet-stream"
            disposition = response.headers.get("content-disposition")
        return body, content_type, disposition


class LocalComfyExecutor:
    """Run contract prompts against the configured local ComfyUI HTTP API."""

    def __init__(self, client: ComfyUIClient) -> None:
        self._client = client

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
        extracted_outputs = extract_contract_outputs(outputs, history)
        output_payloads = [_contract_output_payload(output) for output in extracted_outputs]
        await _attach_artifact_dimensions(self._client, output_payloads)
        return RunExecutionResult(status="completed", prompt_id=prompt_id, outputs=output_payloads)


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


async def _image_dimensions_from_artifact(
    client: ComfyUIClient,
    params: Mapping[str, str],
) -> tuple[int, int] | None:
    try:
        body, _, _ = await client.fetch_output(params)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return None
    return _image_dimensions_from_bytes(body)


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
