"""Public runtime lifecycle helpers for ComfyGit adapters."""

from collections.abc import Sequence
from pathlib import Path

from .constants import ACTIVE_TORCH_BACKEND_OVERRIDE_ENV
from .lifecycle.comfyui_readiness import (
    ComfyUIEndpoint,
    is_comfyui_ready,
    readiness_host_for_bind,
    resolve_comfyui_endpoint,
    wait_for_comfyui_ready,
)
from .lifecycle.switch_observer import (
    SUPERVISOR_HEALTH_ROUTE,
    SUPERVISOR_INFO_FILE,
    SUPERVISOR_LOG_FILE,
    SWITCH_LOGS_ROUTE,
    SWITCH_STATUS_FILE,
    SWITCH_STATUS_ROUTE,
    SwitchObserverServer,
    append_switch_log,
    build_switch_observer_payload,
    cleanup_supervisor_advertisement,
    cleanup_switch_status,
    metadata_dir_for,
    read_supervisor_advertisement,
    read_switch_logs,
    read_switch_status,
    write_supervisor_advertisement,
    write_switch_status,
)


def create_uv_venv(
    venv_path: Path,
    *,
    python: str = "3.12",
    install_packages: Sequence[str] = (),
    install_python: Path | None = None,
) -> None:
    """Create a virtual environment with uv and optionally install packages.

    Runtime adapters can use this helper for bootstrap work without importing
    the lower-level UVCommand integration directly.
    """
    from .integrations.uv_command import UVCommand

    uv = UVCommand()
    uv.venv(venv_path, python=python)

    if install_packages:
        uv.pip_install(
            list(install_packages),
            python=install_python,
        )


__all__ = [
    "ACTIVE_TORCH_BACKEND_OVERRIDE_ENV",
    "ComfyUIEndpoint",
    "SUPERVISOR_HEALTH_ROUTE",
    "SUPERVISOR_INFO_FILE",
    "SUPERVISOR_LOG_FILE",
    "SWITCH_LOGS_ROUTE",
    "SWITCH_STATUS_FILE",
    "SWITCH_STATUS_ROUTE",
    "SwitchObserverServer",
    "append_switch_log",
    "build_switch_observer_payload",
    "cleanup_supervisor_advertisement",
    "cleanup_switch_status",
    "create_uv_venv",
    "is_comfyui_ready",
    "metadata_dir_for",
    "read_supervisor_advertisement",
    "read_switch_logs",
    "read_switch_status",
    "readiness_host_for_bind",
    "resolve_comfyui_endpoint",
    "wait_for_comfyui_ready",
    "write_supervisor_advertisement",
    "write_switch_status",
]
