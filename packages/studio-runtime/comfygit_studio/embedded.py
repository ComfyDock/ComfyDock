"""Embedded Studio runtime helpers for hosts that already run aiohttp."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web
from comfygit_core import Environment

from .runtime import (
    SERVE_STATE_KEY,
    STUDIO_API_BASE_PATH_KEY,
    STUDIO_STATIC_DIR_KEY,
    ServeConfig,
    ServeState,
    cancel_run_handler,
    contracts_handler,
    favicon_handler,
    gallery_delete_handler,
    gallery_handler,
    health_handler,
    openapi_handler,
    output_view_handler,
    run_contract_handler,
    runs_handler,
    single_contract_handler,
    single_run_handler,
    studio_index_handler,
    upload_prepare_handler,
    upload_put_handler,
    upload_status_handler,
    worker_callback_handler,
)

_EMBEDDED_SESSION_KEY = web.AppKey("comfygit_studio_embedded_session", aiohttp.ClientSession)
_EMBEDDED_ENV_PATH_KEY = web.AppKey("comfygit_studio_embedded_env_path", str)
_EMBEDDED_URL_KEY = web.AppKey("comfygit_studio_embedded_url", str)
_EMBEDDED_COMFY_URL_KEY = web.AppKey("comfygit_studio_embedded_comfy_url", str)


@dataclass(frozen=True)
class EmbeddedStudioResult:
    """Browser-facing metadata for an embedded Studio runtime."""

    status: str
    url: str | None
    env_name: str
    started: bool = False
    reused: bool = False
    comfy_url: str | None = None
    mode: str = "embedded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "url": self.url,
            "env_name": self.env_name,
            "started": self.started,
            "reused": self.reused,
            "comfy_url": self.comfy_url,
            "mode": self.mode,
        }


def register_embedded_studio_routes(
    app: web.Application,
    *,
    route_api_prefix: str,
    route_ui_prefix: str,
    public_api_base_path: str,
) -> None:
    """Register namespaced Studio UI and API routes on an existing app."""

    configure_embedded_studio_app(app, public_api_base_path=public_api_base_path)
    app.add_routes(
        create_embedded_studio_routes(
            route_api_prefix=route_api_prefix,
            route_ui_prefix=route_ui_prefix,
        )
    )
    app.on_cleanup.append(close_embedded_studio)


def configure_embedded_studio_app(
    app: web.Application,
    *,
    public_api_base_path: str,
    static_dir: Path | None = None,
) -> None:
    """Configure static assets and browser-facing API base path before startup."""

    app[STUDIO_STATIC_DIR_KEY] = static_dir or _studio_static_dir()
    app[STUDIO_API_BASE_PATH_KEY] = _normalize_public_prefix(public_api_base_path)


def create_embedded_studio_routes(
    *,
    route_api_prefix: str,
    route_ui_prefix: str,
) -> web.RouteTableDef:
    """Create namespaced Studio routes for ComfyUI/Manager-style hosts."""

    routes = web.RouteTableDef()
    api_prefix = _normalize_route_prefix(route_api_prefix)
    ui_prefix = _normalize_route_prefix(route_ui_prefix)

    def configured(handler):
        async def wrapped(request: web.Request) -> web.StreamResponse:
            return await handler(request)

        return wrapped

    routes.get(_route_path(ui_prefix, "/"))(configured(studio_index_handler))
    routes.get(ui_prefix)(configured(studio_index_handler))
    routes.get(_route_path(ui_prefix, "/assets/{tail:.*}"))(configured(_studio_asset_handler))
    routes.get(_route_path(ui_prefix, "/favicon.ico"))(configured(favicon_handler))
    routes.get(_route_path(ui_prefix, "/{tail:.*}"))(configured(studio_index_handler))

    api_routes = (
        ("GET", "/openapi.json", openapi_handler),
        ("GET", "/health", health_handler),
        ("GET", "/contracts", contracts_handler),
        ("GET", "/contracts/{workflow}/{contract}", single_contract_handler),
        ("POST", "/uploads/prepare", upload_prepare_handler),
        ("PUT", "/uploads/{upload_id}", upload_put_handler),
        ("GET", "/uploads/{upload_id}/status", upload_status_handler),
        ("GET", "/gallery", gallery_handler),
        ("DELETE", "/gallery/{item_id}", gallery_delete_handler),
        ("GET", "/runs", runs_handler),
        ("GET", "/runs/{run_id}", single_run_handler),
        ("POST", "/runs/{run_id}/cancel", cancel_run_handler),
        ("POST", "/worker-callback/runs/{run_id}", worker_callback_handler),
        ("POST", "/contracts/{workflow}/{contract}/run", run_contract_handler),
        ("GET", "/outputs/view", output_view_handler),
    )
    for method, path, handler in api_routes:
        routes.route(method, _route_path(api_prefix, path))(configured(handler))

    return routes


async def open_embedded_studio(
    app: web.Application,
    env: Environment,
    *,
    public_scheme: str,
    public_host: str,
    public_ui_path: str,
    comfy_url: str,
    max_request_bytes: int = 256 * 1024 * 1024,
) -> EmbeddedStudioResult:
    """Create or reuse the embedded Studio runtime for an environment."""

    env_path = str(Path(env.path).resolve())
    url = _public_url(public_scheme, public_host, public_ui_path)
    existing_env_path = app.get(_EMBEDDED_ENV_PATH_KEY)
    existing_comfy_url = app.get(_EMBEDDED_COMFY_URL_KEY)
    if existing_env_path == env_path and existing_comfy_url == comfy_url and SERVE_STATE_KEY in app:
        app[_EMBEDDED_URL_KEY] = url
        return EmbeddedStudioResult(
            status="running",
            url=url,
            env_name=env.name,
            reused=True,
            comfy_url=comfy_url,
        )

    await _close_current_state(app)

    session = aiohttp.ClientSession()
    config = ServeConfig(
        host="embedded",
        port=0,
        comfy_url=comfy_url,
        max_request_bytes=max_request_bytes,
        state="local",
        gallery="private",
        state_db=_embedded_state_db(env),
    )
    app[SERVE_STATE_KEY] = ServeState(env, config, session)
    app[_EMBEDDED_SESSION_KEY] = session
    app[_EMBEDDED_ENV_PATH_KEY] = env_path
    app[_EMBEDDED_URL_KEY] = url
    app[_EMBEDDED_COMFY_URL_KEY] = comfy_url

    return EmbeddedStudioResult(
        status="running",
        url=url,
        env_name=env.name,
        started=True,
        comfy_url=comfy_url,
    )


def get_embedded_studio_status(
    app: web.Application,
    env: Environment,
    *,
    public_scheme: str,
    public_host: str,
    public_ui_path: str,
) -> EmbeddedStudioResult:
    env_path = str(Path(env.path).resolve())
    if app.get(_EMBEDDED_ENV_PATH_KEY) == env_path and SERVE_STATE_KEY in app:
        url = app.get(_EMBEDDED_URL_KEY) or _public_url(public_scheme, public_host, public_ui_path)
        comfy_url = app.get(_EMBEDDED_COMFY_URL_KEY)
        return EmbeddedStudioResult(
            status="running",
            url=url,
            env_name=env.name,
            reused=True,
            comfy_url=comfy_url,
        )
    return EmbeddedStudioResult(status="stopped", url=None, env_name=env.name)


async def close_embedded_studio(app: web.Application) -> None:
    await _close_current_state(app)


async def _close_current_state(app: web.Application) -> None:
    state = app.get(SERVE_STATE_KEY)
    tasks: list[asyncio.Task[Any]] = []
    if isinstance(state, ServeState):
        state.state_store.close()
        tasks.extend(set(state.background_tasks))
        tasks.extend(set(state.active_run_tasks.values()))
        for task in tasks:
            task.cancel()
    session = app.get(_EMBEDDED_SESSION_KEY)
    if isinstance(session, aiohttp.ClientSession):
        await session.close()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    app.pop(SERVE_STATE_KEY, None)
    app.pop(_EMBEDDED_SESSION_KEY, None)
    app.pop(_EMBEDDED_ENV_PATH_KEY, None)
    app.pop(_EMBEDDED_URL_KEY, None)
    app.pop(_EMBEDDED_COMFY_URL_KEY, None)


def _embedded_state_db(env: Environment) -> Path:
    workspace_path = Path(env.workspace.path).resolve()
    state_dir = workspace_path / ".metadata" / "studio"
    return state_dir / f"{_safe_name(env.name)}.sqlite"


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return safe or "environment"


def _public_url(scheme: str, host: str, path: str) -> str:
    normalized_path = "/" + str(path or "").strip("/")
    return f"{scheme}://{host}{normalized_path}/"


async def _studio_asset_handler(request: web.Request) -> web.StreamResponse:
    assets_root = (request.app[STUDIO_STATIC_DIR_KEY] / "assets").resolve()
    requested = request.match_info.get("tail", "")
    candidate = (assets_root / requested).resolve()
    if not candidate.is_file() or assets_root not in candidate.parents:
        return web.json_response({"error": "not_found"}, status=404)
    return web.FileResponse(candidate)


def _studio_static_dir() -> Path:
    from importlib import resources

    return Path(str(resources.files("comfygit_studio").joinpath("static")))


def _normalize_route_prefix(prefix: str) -> str:
    normalized = "/" + str(prefix or "").strip("/")
    return "" if normalized == "/" else normalized


def _normalize_public_prefix(prefix: str) -> str:
    normalized = "/" + str(prefix or "").strip("/")
    return "" if normalized == "/" else normalized


def _route_path(prefix: str, path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    if not prefix:
        return path
    if path == "/":
        return f"{prefix}/"
    return f"{prefix}{path}"
