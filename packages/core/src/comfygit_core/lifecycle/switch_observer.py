"""Restart-stable environment switch status and log observer primitives."""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SWITCH_STATUS_FILE = ".switch_status.json"
SUPERVISOR_LOG_FILE = "supervisor-switch.log"
SUPERVISOR_INFO_FILE = ".supervisor_control.json"

SWITCH_STATUS_ROUTE = "/v2/comfygit/switch_status"
SWITCH_LOGS_ROUTE = "/v2/comfygit/switch_logs"
SUPERVISOR_HEALTH_ROUTE = "/v2/comfygit/supervisor/health"
UTC = timezone.utc


def metadata_dir_for(workspace_path: Path) -> Path:
    return workspace_path / ".metadata"


def write_switch_status(
    metadata_dir: Path,
    *,
    state: str,
    progress: int = 0,
    message: str = "",
    **kwargs: Any,
) -> None:
    """Write the shared switch status document."""
    metadata_dir.mkdir(parents=True, exist_ok=True)
    status = {
        "state": state,
        "progress": progress,
        "message": message,
        "updated_at": time.time(),
        **kwargs,
    }
    (metadata_dir / SWITCH_STATUS_FILE).write_text(
        json.dumps(status, indent=2),
        encoding="utf-8",
    )


def read_switch_status(metadata_dir: Path) -> dict[str, Any] | None:
    """Read the shared switch status document."""
    status_file = metadata_dir / SWITCH_STATUS_FILE
    if not status_file.exists():
        return None

    try:
        return json.loads(status_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def cleanup_switch_status(metadata_dir: Path) -> None:
    (metadata_dir / SWITCH_STATUS_FILE).unlink(missing_ok=True)


def append_switch_log(metadata_dir: Path, message: str, level: str = "info") -> None:
    """Append one structured switch lifecycle log line."""
    metadata_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level,
        "message": message,
    }
    with (metadata_dir / SUPERVISOR_LOG_FILE).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def read_switch_logs(metadata_dir: Path, line_count: int = 80) -> list[dict[str, Any]]:
    """Read recent structured switch lifecycle log lines."""
    log_file = metadata_dir / SUPERVISOR_LOG_FILE
    if not log_file.exists():
        return []

    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    entries: list[dict[str, Any]] = []
    for line in lines[-line_count:]:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            entries.append(parsed)
            continue
        entries.append({"timestamp": None, "level": "info", "message": line})
    return entries


def write_supervisor_advertisement(
    workspace_path: Path,
    host: str,
    port: int,
    *,
    kind: str = "cg_run_supervisor",
    public_origin: str | None = None,
) -> None:
    metadata_dir = metadata_dir_for(workspace_path)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"host": host, "port": port, "kind": kind}
    if public_origin:
        payload["public_origin"] = public_origin.rstrip("/")
    (metadata_dir / SUPERVISOR_INFO_FILE).write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def read_supervisor_advertisement(workspace_path: Path) -> dict[str, Any] | None:
    info_file = metadata_dir_for(workspace_path) / SUPERVISOR_INFO_FILE
    if not info_file.exists():
        return None

    try:
        info = json.loads(info_file.read_text(encoding="utf-8"))
        info["port"] = int(info["port"])
        info["kind"] = str(info.get("kind") or "cg_run_supervisor")
        return info
    except Exception:
        return None


def cleanup_supervisor_advertisement(workspace_path: Path) -> None:
    (metadata_dir_for(workspace_path) / SUPERVISOR_INFO_FILE).unlink(missing_ok=True)


def build_switch_observer_payload(public_origin: str, kind: str = "cg_run_supervisor") -> dict[str, str]:
    origin = public_origin.rstrip("/")
    return {
        "kind": kind,
        "status_url": f"{origin}{SWITCH_STATUS_ROUTE}",
        "logs_url": f"{origin}{SWITCH_LOGS_ROUTE}",
    }


class SwitchObserverServer:
    """Expose switch status and recent lifecycle log lines outside ComfyUI."""

    def __init__(
        self,
        workspace_path: Path,
        host: str,
        port: int,
        *,
        kind: str = "cg_run_supervisor",
        public_origin: str | None = None,
        post_handlers: dict[str, Callable[[], dict[str, Any]]] | None = None,
    ) -> None:
        self.workspace_path = workspace_path
        self.metadata_dir = metadata_dir_for(workspace_path)
        self.host = host
        self.port = port
        self.kind = kind
        self.public_origin = public_origin.rstrip("/") if public_origin else None
        self.post_handlers = post_handlers or {}
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.port <= 0:
            return

        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        handler = self._make_handler()
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="ComfyGitSwitchObserver",
            daemon=True,
        )
        self._thread.start()
        write_supervisor_advertisement(
            self.workspace_path,
            self.host,
            self.port,
            kind=self.kind,
            public_origin=self.public_origin,
        )
        self.append_log(f"Supervisor control server listening on {self.host}:{self.port}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        cleanup_supervisor_advertisement(self.workspace_path)

    def append_log(self, message: str, level: str = "info") -> None:
        append_switch_log(self.metadata_dir, message, level=level)

    def _read_status(self) -> dict[str, Any]:
        status = read_switch_status(self.metadata_dir)
        if status:
            return status
        return {
            "state": "idle",
            "progress": 0,
            "message": "No switch in progress",
        }

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        control = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_OPTIONS(self) -> None:
                self._send_json({})

            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0]
                if path in {"/health", SUPERVISOR_HEALTH_ROUTE}:
                    self._send_json({"status": "alive", "port": control.port})
                    return

                if path in {"/status", SWITCH_STATUS_ROUTE}:
                    self._send_json(control._read_status())
                    return

                if path in {"/logs", SWITCH_LOGS_ROUTE}:
                    self._send_json({"logs": read_switch_logs(control.metadata_dir, 80)})
                    return

                self.send_error(404, "Not Found")

            def do_POST(self) -> None:
                path = self.path.split("?", 1)[0]
                handler = control.post_handlers.get(path)
                if not handler:
                    self.send_error(404, "Not Found")
                    return

                try:
                    self._send_json(handler())
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=500)

            def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


# Backward-compatible alias for callers that describe the owning process.
SupervisorControlServer = SwitchObserverServer
