"""ComfyUI endpoint parsing and readiness checks for lifecycle supervisors."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError
from urllib.request import urlopen


class ProcessLike(Protocol):
    returncode: int | None

    def poll(self) -> int | None:
        pass


@dataclass(frozen=True)
class ComfyUIEndpoint:
    """Resolved ComfyUI endpoint for local supervisor readiness checks."""

    bind_host: str
    check_host: str
    port: int

    @property
    def base_url(self) -> str:
        host = self.check_host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self.port}"


def _parse_port(value: str, current_port: int) -> int:
    """Parse a ComfyUI port override, retaining the current port on invalid input."""
    try:
        return int(value)
    except ValueError:
        return current_port


def resolve_comfyui_endpoint(
    args: list[str] | tuple[str, ...] | None,
    *,
    default_host: str = "127.0.0.1",
    default_port: int = 8188,
) -> ComfyUIEndpoint:
    """Resolve the effective ComfyUI listen endpoint from launch args.

    ComfyUI accepts `--port <port>` or `--port=<port>`, and `--listen` either
    with an explicit host or as a flag that binds all interfaces. Later args
    win, matching normal CLI override behavior.
    """
    bind_host = default_host
    port = default_port
    tokens = list(args or [])
    index = 0

    while index < len(tokens):
        token = tokens[index]

        if token == "--port" and index + 1 < len(tokens):
            port = _parse_port(tokens[index + 1], port)
            index += 2
            continue

        if token.startswith("--port="):
            port = _parse_port(token.split("=", 1)[1], port)
            index += 1
            continue

        if token == "--listen":
            if index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
                bind_host = tokens[index + 1]
                index += 2
            else:
                bind_host = "0.0.0.0"
                index += 1
            continue

        if token.startswith("--listen="):
            bind_host = token.split("=", 1)[1] or "0.0.0.0"
            index += 1
            continue

        index += 1

    return ComfyUIEndpoint(
        bind_host=bind_host,
        check_host=readiness_host_for_bind(bind_host),
        port=port,
    )


def readiness_host_for_bind(bind_host: str) -> str:
    """Map a bind address to a host reachable from the same supervisor."""
    host = (bind_host or "").strip()
    if host in {"", "0.0.0.0", "::", "[::]", "*"}:
        return "127.0.0.1"
    return host.strip("[]")


def is_comfyui_ready(
    endpoint: ComfyUIEndpoint,
    *,
    paths: tuple[str, ...] = ("/system_stats", "/"),
    timeout: float = 2.0,
) -> bool:
    """Return whether ComfyUI responds on one of the expected HTTP paths."""
    for path in paths:
        try:
            with urlopen(f"{endpoint.base_url}{path}", timeout=timeout) as response:
                if 200 <= response.status < 500:
                    return True
        except HTTPError as exc:
            if 400 <= exc.code < 500:
                return True
        except (OSError, ValueError):
            continue
    return False


def wait_for_comfyui_ready(
    proc: ProcessLike,
    endpoint: ComfyUIEndpoint,
    *,
    timeout: float,
    interval: float = 1.0,
    stable_successes: int = 1,
    log: Callable[[str, str], None] | None = None,
    log_interval: float = 10.0,
) -> bool:
    """Wait for ComfyUI readiness or process exit."""
    deadline = time.monotonic() + timeout
    last_log_at = 0.0
    successes = 0

    while time.monotonic() < deadline:
        if proc.poll() is not None:
            if log:
                log(
                    f"ComfyUI exited before readiness check succeeded (code {proc.returncode})",
                    "error",
                )
            return False

        if is_comfyui_ready(endpoint):
            successes += 1
            if successes >= stable_successes:
                return True
        else:
            successes = 0

        now = time.monotonic()
        if log and now - last_log_at >= log_interval:
            log(f"Still waiting for ComfyUI readiness at {endpoint.base_url}", "info")
            last_log_at = now
        time.sleep(interval)

    if log:
        log(f"Timed out waiting for ComfyUI readiness at {endpoint.base_url}", "error")
    return False
