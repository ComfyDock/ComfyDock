"""Worker-side WebSocket tunnel client."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from ..worker.server import WorkerServer
from .handler import TunnelHandler

MAX_MESSAGE_BYTES = 1_000_000
PING_INTERVAL_SECONDS = 30.0
AUTH_TIMEOUT_SECONDS = 10.0
MAX_RECONNECT_SECONDS = 30.0


def normalize_cloud_ws_url(cloud_url: str) -> str:
    parsed = urlsplit(cloud_url)
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        raise ValueError("Cloud URL must start with http://, https://, ws://, or wss://")
    if not parsed.netloc:
        raise ValueError("Cloud URL must include a hostname")

    if parsed.scheme == "http":
        scheme = "ws"
    elif parsed.scheme == "https":
        scheme = "wss"
    else:
        scheme = parsed.scheme

    path = parsed.path or ""
    if path in {"", "/"}:
        path = "/api/workers/ws"
    elif not path.endswith("/api/workers/ws"):
        path = path.rstrip("/") + "/api/workers/ws"

    return urlunsplit((scheme, parsed.netloc, path, "", ""))


class TunnelClient:
    """Maintains an outbound worker tunnel connection to a remote coordination service."""

    def __init__(self, cloud_url: str, token: str, worker_server: WorkerServer):
        self.websocket_url = normalize_cloud_ws_url(cloud_url)
        self.token = token
        self.worker_server = worker_server
        self.handler = TunnelHandler(worker_server)
        self._stop_event = asyncio.Event()
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self.worker_id: str | None = None

    async def run(self) -> None:
        backoff = 1.0

        while not self._stop_event.is_set():
            try:
                await self._run_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stop_event.is_set():
                    break

                print(f"Cloud tunnel disconnected: {exc}")
                print(f"Reconnecting in {int(backoff)}s...")
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, MAX_RECONNECT_SECONDS)

        await self.close()

    async def close(self) -> None:
        self._stop_event.set()
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _run_once(self) -> None:
        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(
                self.websocket_url,
                autoping=False,
                heartbeat=None,
                max_msg_size=MAX_MESSAGE_BYTES,
            )
            await self._send_json({"type": "auth", "token": self.token})

            auth_message = await self._receive_json(timeout=AUTH_TIMEOUT_SECONDS)
            if auth_message.get("type") == "auth_error":
                raise RuntimeError(str(auth_message.get("message") or "Tunnel auth failed"))
            if auth_message.get("type") != "auth_ok":
                raise RuntimeError("Tunnel auth handshake returned an unexpected response")

            self.worker_id = str(auth_message.get("worker_id") or "")
            print(f"Connected to {self.websocket_url}")

            ping_task = asyncio.create_task(self._ping_loop())
            try:
                while not self._stop_event.is_set():
                    message = await self._receive_json()
                    await self.handle_message(message)
            finally:
                ping_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ping_task
        finally:
            self.worker_id = None
            if self._ws is not None and not self._ws.closed:
                await self._ws.close()
            if self._session is not None and not self._session.closed:
                await self._session.close()
            self._ws = None
            self._session = None

    async def _ping_loop(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(PING_INTERVAL_SECONDS)
            await self._send_json({"type": "ping"})

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("Tunnel websocket is not connected")

        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        if len(encoded.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise RuntimeError("Tunnel message exceeds the 1MB size limit")
        await self._ws.send_str(encoded)

    async def _receive_json(self, *, timeout: float | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("Tunnel websocket is not connected")

        message = await self._ws.receive(timeout=timeout)
        if message.type != aiohttp.WSMsgType.TEXT:
            if message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}:
                raise RuntimeError("Cloud tunnel closed the connection")
            if message.type == aiohttp.WSMsgType.ERROR:
                raise RuntimeError("Cloud tunnel websocket reported an error")
            raise RuntimeError(f"Unexpected websocket message type: {message.type}")

        raw = message.data
        if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise RuntimeError("Tunnel message exceeds the 1MB size limit")

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Cloud tunnel sent invalid JSON") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("Cloud tunnel sent a non-object message")
        return payload

    async def handle_message(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("type") or "")

        if message_type == "pong":
            return

        if message_type == "ping":
            await self._send_json({"type": "pong"})
            return

        try:
            response = await self.handler.handle_message(message)
        except Exception as exc:
            request_id = message.get("request_id")
            if isinstance(request_id, str) and request_id:
                await self._send_json(
                    {
                        "type": "error",
                        "request_id": request_id,
                        "message": str(exc),
                    }
                )
            else:
                print(f"Tunnel handler error: {exc}")
            return

        await self._send_json(response)
