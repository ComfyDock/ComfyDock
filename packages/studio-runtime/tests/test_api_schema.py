from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import aiohttp
import pytest
from aiohttp import web
from comfygit_studio.api_schema import PUBLIC_STUDIO_API_ROUTES, studio_contract_api_openapi
from comfygit_studio.runtime import ServeConfig, ServeState, create_app, register_studio_routes
from comfygit_studio.state import ServeGalleryItem


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
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    return static_dir


def _gallery_item(item_id: str, created_at: str) -> ServeGalleryItem:
    return ServeGalleryItem(
        item_id=item_id,
        run_id=f"run_{item_id}",
        session_id="session1",
        scope_key="session1",
        workflow="workflow",
        contract="contract",
        status="done",
        output_type="image",
        inputs={},
        filename=f"{item_id}.png",
        url=f"/outputs/view?filename={item_id}.png&subfolder=&type=output",
        created_at=created_at,
    )


def test_checked_in_openapi_artifact_is_current() -> None:
    path = (
        Path(__file__).parents[1]
        / "comfygit_studio"
        / "openapi"
        / "studio-contract-api.v1.json"
    )

    assert json.loads(path.read_text(encoding="utf-8")) == studio_contract_api_openapi()


def test_openapi_public_routes_are_registered(tmp_path: Path) -> None:
    app = web.Application()
    register_studio_routes(app, static_dir=_static_dir(tmp_path), include_spa_fallback=False)

    registered = {(route.method, route.resource.canonical) for route in app.router.routes()}

    for method, path in PUBLIC_STUDIO_API_ROUTES:
        assert (method, path) in registered


@pytest.mark.asyncio
async def test_openapi_route_serves_public_spec(tmp_path: Path) -> None:
    async with aiohttp.ClientSession() as session:
        state = ServeState(
            _fake_env(tmp_path),
            ServeConfig(host="127.0.0.1", port=0, comfy_url="http://127.0.0.1:8188"),
            session,
        )
        app = create_app(state, static_dir=_static_dir(tmp_path))
        base_url, runner = await _with_app_server(app)
        try:
            async with session.get(f"{base_url}/openapi.json") as response:
                assert response.status == 200
                payload = await response.json()
        finally:
            await runner.cleanup()
            state.state_store.close()

    assert payload["info"]["title"] == "ComfyGit Studio Contract API"
    assert "/gallery" in payload["paths"]
    assert payload["paths"]["/gallery"]["get"]["operationId"] == "listGallery"


@pytest.mark.asyncio
async def test_gallery_cursor_pagination(tmp_path: Path) -> None:
    async with aiohttp.ClientSession() as session:
        state = ServeState(
            _fake_env(tmp_path),
            ServeConfig(host="127.0.0.1", port=0, comfy_url="http://127.0.0.1:8188"),
            session,
        )
        state.state_store.record_gallery_items(
            [
                _gallery_item("item_a", "2026-01-01T00:00:01.000Z"),
                _gallery_item("item_b", "2026-01-01T00:00:02.000Z"),
                _gallery_item("item_c", "2026-01-01T00:00:03.000Z"),
            ]
        )
        app = create_app(state, static_dir=_static_dir(tmp_path))
        base_url, runner = await _with_app_server(app)
        try:
            headers = {"X-ComfyGit-Studio-Session": "session1"}
            async with session.get(f"{base_url}/gallery?limit=2", headers=headers) as response:
                assert response.status == 200
                first_page = await response.json()
            async with session.get(
                f"{base_url}/gallery?limit=2&cursor={first_page['next_cursor']}",
                headers=headers,
            ) as response:
                assert response.status == 200
                second_page = await response.json()
            async with session.get(f"{base_url}/gallery", headers=headers) as response:
                assert response.status == 200
                full_page = await response.json()
            async with session.get(f"{base_url}/gallery?limit=0", headers=headers) as response:
                invalid_limit_status = response.status
            async with session.get(f"{base_url}/gallery?limit=2&cursor=bad", headers=headers) as response:
                invalid_cursor_status = response.status
        finally:
            await runner.cleanup()
            state.state_store.close()

    assert [item["id"] for item in first_page["items"]] == ["item_c", "item_b"]
    assert first_page["has_more"] is True
    assert first_page["next_cursor"]
    assert first_page["limit"] == 2
    assert [item["id"] for item in second_page["items"]] == ["item_a"]
    assert second_page["has_more"] is False
    assert second_page["next_cursor"] is None
    assert [item["id"] for item in full_page["items"]] == ["item_c", "item_b", "item_a"]
    assert full_page["has_more"] is False
    assert full_page["limit"] is None
    assert invalid_limit_status == 400
    assert invalid_cursor_status == 400
