"""Tests for the `cg serve` command wiring."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import ClientSession, web
from comfygit_cli.cli import create_parser
from comfygit_cli.env_commands import EnvironmentCommands
from comfygit_cli.serve_runtime import (
    ComfyUIClient,
    ServeConfig,
    _content_type_for_filename,
    _generated_upload_filename,
    _prepare_contract_inputs,
    _stamp_output_cache_busters,
    create_app,
)


async def _with_test_server(
    handler: Callable[[web.Request], Awaitable[web.Response]],
    method: str,
    path: str,
) -> tuple[str, web.AppRunner]:
    app = web.Application()
    app.router.add_route(method, path, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets  # noqa: SLF001 - aiohttp exposes no public bound-port helper.
    port = sockets[0].getsockname()[1]
    return f"http://127.0.0.1:{port}", runner


async def _with_app_server(app: web.Application) -> tuple[str, web.AppRunner]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets  # noqa: SLF001 - aiohttp exposes no public bound-port helper.
    port = sockets[0].getsockname()[1]
    return f"http://127.0.0.1:{port}", runner


def test_serve_parser_defaults() -> None:
    parser = create_parser()

    args = parser.parse_args(["-e", "demo", "serve"])

    assert args.command == "serve"
    assert args.target_env == "demo"
    assert args.host == "127.0.0.1"
    assert args.port == 8190
    assert args.comfy_url == "http://127.0.0.1:8188"


def test_serve_parser_accepts_runtime_options() -> None:
    parser = create_parser()

    args = parser.parse_args(
        [
            "-e",
            "demo",
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--comfy-url",
            "http://127.0.0.1:8189",
        ]
    )

    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.comfy_url == "http://127.0.0.1:8189"
    assert args.max_request_mb == 256


def test_serve_parser_accepts_max_request_size() -> None:
    parser = create_parser()

    args = parser.parse_args(["-e", "demo", "serve", "--max-request-mb", "512"])

    assert args.max_request_mb == 512


@patch("comfygit_cli.env_commands.get_workspace_or_exit")
@patch("comfygit_cli.serve_runtime.serve_environment")
def test_serve_command_uses_selected_environment(mock_serve, mock_workspace) -> None:
    mock_env = MagicMock()
    mock_env.name = "demo"
    mock_workspace.return_value.get_environment.return_value = mock_env

    cmd = EnvironmentCommands()
    parser = create_parser()
    args = parser.parse_args(["-e", "demo", "serve", "--port", "9000"])

    cmd.serve(args)

    mock_workspace.return_value.get_environment.assert_any_call("demo")
    mock_serve.assert_called_once()
    called_env, called_config = mock_serve.call_args.args
    assert called_env is mock_env
    assert called_config.port == 9000
    assert called_config.max_request_bytes == 256 * 1024 * 1024


@patch("comfygit_cli.env_commands.get_workspace_or_exit")
@patch("comfygit_cli.serve_runtime.serve_environment")
def test_serve_command_uses_configured_request_size(mock_serve, mock_workspace) -> None:
    mock_env = MagicMock()
    mock_env.name = "demo"
    mock_workspace.return_value.get_environment.return_value = mock_env

    cmd = EnvironmentCommands()
    parser = create_parser()
    args = parser.parse_args(["-e", "demo", "serve", "--max-request-mb", "512"])

    cmd.serve(args)

    called_config = mock_serve.call_args.args[1]
    assert called_config.max_request_bytes == 512 * 1024 * 1024


@pytest.mark.asyncio
async def test_serve_app_serves_contract_studio_root() -> None:
    state = MagicMock()
    app = create_app(state)
    base_url, runner = await _with_app_server(app)
    try:
        async with ClientSession() as session:
            async with session.get(f"{base_url}/") as response:
                text = await response.text()

        assert response.status == 200
        assert "ComfyGit Studio" in text
        assert "root" in text
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_serve_app_suppresses_missing_favicon() -> None:
    state = MagicMock()
    app = create_app(state)
    base_url, runner = await _with_app_server(app)
    try:
        async with ClientSession() as session:
            async with session.get(f"{base_url}/favicon.ico") as response:
                await response.read()

        assert response.status == 204
    finally:
        await runner.cleanup()


def test_serve_app_uses_configured_request_limit() -> None:
    state = SimpleNamespace(
        config=ServeConfig(
            host="127.0.0.1",
            port=8190,
            comfy_url="http://127.0.0.1:8188",
            max_request_bytes=512 * 1024 * 1024,
        )
    )

    app = create_app(state)

    assert app._client_max_size == 512 * 1024 * 1024  # noqa: SLF001 - aiohttp stores this setting privately.


@pytest.mark.asyncio
async def test_comfyui_client_submit_prompt_returns_prompt_id() -> None:
    async def handler(request: web.Request) -> web.Response:
        body = await request.json()
        assert body == {"prompt": {"1": {"class_type": "Test", "inputs": {}}}}
        return web.json_response({"prompt_id": "abc123"})

    base_url, runner = await _with_test_server(handler, "POST", "/prompt")
    try:
        client = ComfyUIClient(base_url)

        assert await client.submit_prompt({"1": {"class_type": "Test", "inputs": {}}}) == "abc123"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_comfyui_client_unwraps_prompt_history() -> None:
    history_payload = {
        "abc123": {
            "outputs": {
                "9": {
                    "images": [
                        {"filename": "image.png", "subfolder": "", "type": "output"}
                    ]
                }
            }
        }
    }

    async def handler(_request: web.Request) -> web.Response:
        return web.json_response(history_payload)

    base_url, runner = await _with_test_server(handler, "GET", "/history/abc123")
    try:
        client = ComfyUIClient(base_url)

        assert await client.get_history("abc123") == history_payload["abc123"]
    finally:
        await runner.cleanup()


def test_stamp_output_cache_busters_updates_save_image_prefix() -> None:
    prompt = {
        "8": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "ComfyUI", "images": ["4", 0]},
        },
        "9": {
            "class_type": "PreviewImage",
            "inputs": {"images": ["4", 0]},
        },
    }
    outputs = (
        SimpleNamespace(type="image", node_id="8"),
        SimpleNamespace(type="image", node_id="9"),
    )

    _stamp_output_cache_busters(prompt, outputs, "abc123")

    assert prompt["8"]["inputs"]["filename_prefix"] == "ComfyUI_abc123"
    assert "filename_prefix" not in prompt["9"]["inputs"]


@pytest.mark.asyncio
async def test_upload_slot_writes_to_comfyui_input_dir(tmp_path) -> None:
    state = SimpleNamespace(
        config=ServeConfig(
            host="127.0.0.1",
            port=8190,
            comfy_url="http://127.0.0.1:8188",
            max_request_bytes=1024,
        ),
        env=SimpleNamespace(comfyui_path=tmp_path / "ComfyUI"),
        uploads={},
    )
    app = create_app(state)
    base_url, runner = await _with_app_server(app)
    try:
        async with ClientSession() as session:
            async with session.post(
                f"{base_url}/uploads/prepare",
                json={"filename": "folder/source.png", "mime_type": "image/png", "size": 11},
            ) as response:
                prepared = await response.json()

            assert response.status == 200
            assert prepared["file_ref"]["kind"] == "file_ref"
            assert prepared["file_ref"]["filename"] == "source.png"
            assert not str(prepared["file_ref"]["ref"]).endswith("source.png")

            async with session.put(
                f"{base_url}{prepared['upload_url']}",
                data=b"image-bytes",
                headers={"content-type": "image/png"},
            ) as response:
                uploaded = await response.json()

            assert response.status == 200
            assert uploaded["status"] == "ready"

            async with session.get(
                f"{base_url}/uploads/{prepared['upload_id']}/status",
            ) as response:
                status = await response.json()

        assert response.status == 200
        assert status["status"] == "ready"
        record = state.uploads[prepared["upload_id"]]
        assert record.path == tmp_path / "ComfyUI" / "input" / record.comfyui_filename
        assert record.path.read_bytes() == b"image-bytes"
    finally:
        await runner.cleanup()


def test_upload_filename_and_mime_helpers_share_media_type_map() -> None:
    assert _content_type_for_filename("clip.mp4") == "video/mp4"
    assert _content_type_for_filename("sound.wav") == "audio/wav"
    assert _content_type_for_filename("photo.jpeg") == "image/jpeg"

    assert _generated_upload_filename("video/mp4", stem="clip") == "clip.mp4"
    assert _generated_upload_filename("audio/x-wav", stem="sound") == "sound.wav"
    assert _generated_upload_filename("image/jpg", stem="photo") == "photo.jpg"


@pytest.mark.asyncio
async def test_prepare_contract_inputs_resolves_file_refs() -> None:
    state = SimpleNamespace(
        uploads={
            "upload_abc123": SimpleNamespace(
                status="ready",
                comfyui_filename="upload_abc123_source.png",
            )
        },
        manifest_snapshot=lambda: SimpleNamespace(
            workflows={
                "demo": SimpleNamespace(
                    execution_contract=SimpleNamespace(
                        contracts={
                            "default": SimpleNamespace(
                                inputs=[
                                    SimpleNamespace(name="source_image", type="image"),
                                    SimpleNamespace(name="prompt", type="string"),
                                ]
                            )
                        }
                    )
                )
            }
        ),
    )

    prepared = await _prepare_contract_inputs(
        state,
        "demo",
        "default",
        {
            "source_image": {
                "kind": "file_ref",
                "ref": "upload_abc123",
                "filename": "source.png",
            },
            "prompt": "keep this",
        },
    )

    assert prepared == {
        "source_image": "upload_abc123_source.png",
        "prompt": "keep this",
    }


@pytest.mark.asyncio
async def test_prepare_contract_inputs_rejects_inline_image_bytes() -> None:
    state = SimpleNamespace(
        uploads={},
        manifest_snapshot=lambda: SimpleNamespace(
            workflows={
                "demo": SimpleNamespace(
                    execution_contract=SimpleNamespace(
                        contracts={
                            "default": SimpleNamespace(
                                inputs=[SimpleNamespace(name="source_image", type="image")]
                            )
                        }
                    )
                )
            }
        ),
    )

    with pytest.raises(ValueError, match="Upload the file first"):
        await _prepare_contract_inputs(
            state,
            "demo",
            "default",
            {"source_image": {"data_url": "data:image/png;base64,aW1hZ2UtYnl0ZXM="}},
        )
