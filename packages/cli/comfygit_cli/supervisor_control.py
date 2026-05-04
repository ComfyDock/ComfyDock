"""Small restart-stable status server for ``cg run`` supervision."""
from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class SupervisorControlServer:
    """Expose switch status and recent supervisor log lines outside ComfyUI."""

    def __init__(self, workspace_path: Path, host: str, port: int) -> None:
        self.workspace_path = workspace_path
        self.metadata_dir = workspace_path / ".metadata"
        self.host = host
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.log_file = self.metadata_dir / "supervisor-switch.log"
        self.info_file = self.metadata_dir / ".supervisor_control.json"

    def start(self) -> None:
        if self.port <= 0:
            return

        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        handler = self._make_handler()
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="ComfyGitSupervisorControl",
            daemon=True,
        )
        self._thread.start()
        self.info_file.write_text(
            json.dumps({"host": self.host, "port": self.port}, indent=2),
            encoding="utf-8",
        )
        self.append_log(f"Supervisor control server listening on {self.host}:{self.port}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self.info_file.unlink(missing_ok=True)

    def append_log(self, message: str, level: str = "info") -> None:
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "message": message,
        }
        with self.log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def _read_status(self) -> dict[str, Any]:
        status_file = self.metadata_dir / ".switch_status.json"
        if status_file.exists():
            try:
                return json.loads(status_file.read_text(encoding="utf-8"))
            except Exception as exc:
                return {
                    "state": "unknown",
                    "progress": 0,
                    "message": f"Could not read switch status: {exc}",
                }
        return {
            "state": "idle",
            "progress": 0,
            "message": "No switch in progress",
        }

    def _read_logs(self, line_count: int) -> list[dict[str, Any]]:
        if not self.log_file.exists():
            return []
        lines = self.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        entries: list[dict[str, Any]] = []
        for line in lines[-line_count:]:
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    entries.append(parsed)
                    continue
            except Exception:
                pass
            entries.append({"timestamp": None, "level": "info", "message": line})
        return entries

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        control = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_OPTIONS(self) -> None:
                self._send_json({})

            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0]
                if path in {"/health", "/v2/comfygit/supervisor/health"}:
                    self._send_json({"status": "alive", "port": control.port})
                    return

                if path in {"/status", "/v2/comfygit/switch_status"}:
                    self._send_json(control._read_status())
                    return

                if path in {"/logs", "/v2/comfygit/switch_logs"}:
                    self._send_json({"logs": control._read_logs(80)})
                    return

                self.send_error(404, "Not Found")

            def _send_json(self, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler
