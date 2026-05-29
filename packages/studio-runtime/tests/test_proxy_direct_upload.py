from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import aiohttp
import pytest
from aiohttp import web
from comfygit_studio.runtime import (
    WorkerArtifactUploadTarget,
    _worker_callback_outputs_and_uploads,
)


async def _with_app_server(app: web.Application) -> tuple[str, web.AppRunner]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = cast(Any, site._server).sockets  # noqa: SLF001 - aiohttp exposes no bound-port helper.
    port = sockets[0].getsockname()[1]
    return f"http://127.0.0.1:{port}", runner


class FakeComfyClient:
    def __init__(self, body: bytes = b"video-bytes", content_type: str = "video/mp4") -> None:
        self.body = body
        self.content_type = content_type
        self.fetches: list[dict[str, str]] = []

    async def fetch_output(self, params: dict[str, str], request_headers: dict[str, str]):
        self.fetches.append(dict(params))
        return SimpleNamespace(body=self.body, content_type=self.content_type)


def _state(client: FakeComfyClient):
    return SimpleNamespace(client=client)


def _video_outputs() -> list[dict[str, Any]]:
    return [
        {
            "name": "save_video",
            "type": "video",
            "artifacts": [
                {
                    "filename": "ComfyUI_00001_.mp4",
                    "subfolder": "video",
                    "type": "output",
                }
            ],
        }
    ]


@pytest.mark.asyncio
async def test_worker_callback_uses_local_file_direct_upload_target(tmp_path: Path) -> None:
    target_path = tmp_path / "artifact.mp4"
    client = FakeComfyClient(body=b"direct-upload-video")
    targets = (
        WorkerArtifactUploadTarget(
            upload_id="upl_123",
            output_name="save_video",
            artifact_index=0,
            transport={"kind": "local_file_put", "path": str(target_path)},
            storage_ref={"provider": "cloud_local", "path": str(target_path)},
            expected_content_type="video/mp4",
        ),
    )

    callback_outputs, uploads = await _worker_callback_outputs_and_uploads(
        _state(client),
        _video_outputs(),
        artifact_upload_targets=targets,
    )

    assert uploads == []
    assert target_path.read_bytes() == b"direct-upload-video"
    artifact = callback_outputs[0]["artifacts"][0]
    assert artifact["upload_id"] == "upl_123"
    assert artifact["storage_ref"] == {"provider": "cloud_local", "path": str(target_path)}
    assert artifact["filename"] == "ComfyUI_00001_.mp4"
    assert artifact["content_type"] == "video/mp4"
    assert artifact["kind"] == "video"
    assert artifact["size_bytes"] == len(b"direct-upload-video")
    assert artifact["sha256"] == hashlib.sha256(b"direct-upload-video").hexdigest()
    assert "upload_field" not in artifact


@pytest.mark.asyncio
async def test_worker_callback_uses_supabase_signed_upload_target() -> None:
    received: dict[str, Any] = {}

    async def upload_handler(request: web.Request) -> web.Response:
        assert request.method == "PUT"
        reader = await request.multipart()
        part = await reader.next()
        assert isinstance(part, aiohttp.BodyPartReader)
        received["field"] = part.name
        received["filename"] = part.filename
        received["content_type"] = part.headers.get("Content-Type")
        received["body"] = await part.read()
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_put("/upload", upload_handler)
    base_url, runner = await _with_app_server(app)
    try:
        client = FakeComfyClient(body=b"supabase-upload-video")
        targets = (
            WorkerArtifactUploadTarget(
                upload_id="upl_456",
                output_name="save_video",
                artifact_index=0,
                transport={
                    "kind": "supabase_signed_upload",
                    "url": f"{base_url}/upload",
                    "headers": {"content-type": "video/mp4"},
                },
                storage_ref={"provider": "supabase", "bucket": "run-artifacts", "path": "runs/run/video.mp4"},
                expected_content_type="video/mp4",
            ),
        )

        callback_outputs, uploads = await _worker_callback_outputs_and_uploads(
            _state(client),
            _video_outputs(),
            artifact_upload_targets=targets,
        )
    finally:
        await runner.cleanup()

    assert uploads == []
    assert received == {
        "field": "file",
        "filename": "ComfyUI_00001_.mp4",
        "content_type": "video/mp4",
        "body": b"supabase-upload-video",
    }
    artifact = callback_outputs[0]["artifacts"][0]
    assert artifact["upload_id"] == "upl_456"
    assert artifact["storage_ref"]["provider"] == "supabase"
    assert artifact["sha256"] == hashlib.sha256(b"supabase-upload-video").hexdigest()


@pytest.mark.asyncio
async def test_worker_callback_falls_back_to_multipart_upload_without_target() -> None:
    client = FakeComfyClient(body=b"fallback-video")

    callback_outputs, uploads = await _worker_callback_outputs_and_uploads(_state(client), _video_outputs())

    assert len(uploads) == 1
    assert uploads[0].field_name == "artifact_0_0"
    assert uploads[0].filename == "ComfyUI_00001_.mp4"
    assert uploads[0].content_type == "video/mp4"
    assert uploads[0].body == b"fallback-video"
    artifact = callback_outputs[0]["artifacts"][0]
    assert artifact["upload_field"] == "artifact_0_0"
    assert "upload_id" not in artifact
