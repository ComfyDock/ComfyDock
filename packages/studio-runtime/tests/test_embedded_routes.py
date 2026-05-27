from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import aiohttp
import pytest
from aiohttp import web
from comfygit_studio.embedded import (
    close_embedded_studio,
    configure_embedded_studio_app,
    create_embedded_studio_routes,
    open_embedded_studio,
)
from comfygit_studio.runtime import SERVE_STATE_KEY, ServeConfig, ServeState, create_app


async def _with_app_server(app: web.Application) -> tuple[str, web.AppRunner]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = cast(Any, site._server).sockets  # noqa: SLF001 - aiohttp exposes no bound-port helper.
    port = sockets[0].getsockname()[1]
    return f"http://127.0.0.1:{port}", runner


def _fake_env(tmp_path: Path):
    workspace_path = tmp_path / "workspace"
    env_path = workspace_path / "environments" / "demo"
    env_path.mkdir(parents=True)
    return SimpleNamespace(
        name="demo",
        path=env_path,
        workspace=SimpleNamespace(path=workspace_path),
        workspace_paths=SimpleNamespace(metadata=workspace_path / ".metadata"),
    )


def _static_dir(tmp_path: Path) -> Path:
    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text(
        "<!doctype html><html><head></head><body><div id=\"root\"></div></body></html>",
        encoding="utf-8",
    )
    (assets_dir / "app.js").write_text("console.log('studio')", encoding="utf-8")
    return static_dir


@pytest.mark.asyncio
async def test_create_app_injects_runtime_api_base_path(tmp_path: Path) -> None:
    async with aiohttp.ClientSession() as session:
        state = ServeState(
            _fake_env(tmp_path),
            ServeConfig(host="127.0.0.1", port=0, comfy_url="http://127.0.0.1:8188"),
            session,
        )
        app = create_app(state, static_dir=_static_dir(tmp_path), api_base_path="/api/runtime")
        base_url, runner = await _with_app_server(app)
        try:
            async with session.get(f"{base_url}/") as response:
                assert response.status == 200
                text = await response.text()
        finally:
            await runner.cleanup()
            state.state_store.close()

    assert '"apiBasePath": "/api/runtime"' in text
    assert '"endpointName": "demo"' in text


@pytest.mark.asyncio
async def test_embedded_routes_are_namespaced_and_serve_assets(tmp_path: Path) -> None:
    static_dir = _static_dir(tmp_path)
    async with aiohttp.ClientSession() as session:
        state = ServeState(
            _fake_env(tmp_path),
            ServeConfig(host="embedded", port=0, comfy_url="http://127.0.0.1:8188"),
            session,
        )
        app = web.Application()
        app[SERVE_STATE_KEY] = state
        configure_embedded_studio_app(
            app,
            public_api_base_path="/api/v2/comfygit/studio/runtime",
            static_dir=static_dir,
        )
        routes = create_embedded_studio_routes(
            route_api_prefix="/v2/comfygit/studio/runtime",
            route_ui_prefix="/v2/comfygit/studio/ui",
        )
        app.add_routes(routes)
        base_url, runner = await _with_app_server(app)
        try:
            async with session.get(f"{base_url}/v2/comfygit/studio/ui/") as response:
                assert response.status == 200
                text = await response.text()
            async with session.get(f"{base_url}/v2/comfygit/studio/ui/assets/app.js") as response:
                assert response.status == 200
                asset_text = await response.text()
        finally:
            await runner.cleanup()
            state.state_store.close()

    assert '"apiBasePath": "/api/v2/comfygit/studio/runtime"' in text
    assert "console.log('studio')" in asset_text


@pytest.mark.asyncio
async def test_embedded_runtime_reuses_only_matching_environment_and_comfy_url(tmp_path: Path) -> None:
    app = web.Application()
    env = _fake_env(tmp_path)
    try:
        first = await open_embedded_studio(
            app,
            env,
            public_scheme="http",
            public_host="example.test",
            public_ui_path="/api/v2/comfygit/studio/ui",
            comfy_url="http://127.0.0.1:8188",
        )
        first_state = app[SERVE_STATE_KEY]
        second = await open_embedded_studio(
            app,
            env,
            public_scheme="http",
            public_host="example.test",
            public_ui_path="/api/v2/comfygit/studio/ui",
            comfy_url="http://127.0.0.1:8188",
        )
        second_state = app[SERVE_STATE_KEY]
        third = await open_embedded_studio(
            app,
            env,
            public_scheme="http",
            public_host="example.test",
            public_ui_path="/api/v2/comfygit/studio/ui",
            comfy_url="http://127.0.0.1:8189",
        )
        third_state = app[SERVE_STATE_KEY]
    finally:
        await close_embedded_studio(app)

    assert first.started is True
    assert second.reused is True
    assert first_state is second_state
    assert third.started is True
    assert third.reused is False
    assert third_state is not first_state
