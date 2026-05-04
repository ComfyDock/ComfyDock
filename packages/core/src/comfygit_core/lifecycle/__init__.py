"""Lifecycle helpers shared by ComfyGit CLI and manager integrations."""

from .switch_observer import (
    SWITCH_LOGS_ROUTE,
    SWITCH_STATUS_ROUTE,
    SUPERVISOR_HEALTH_ROUTE,
    SUPERVISOR_INFO_FILE,
    SUPERVISOR_LOG_FILE,
    SWITCH_STATUS_FILE,
    SwitchObserverServer,
    append_switch_log,
    build_switch_observer_payload,
    cleanup_supervisor_advertisement,
    cleanup_switch_status,
    read_supervisor_advertisement,
    read_switch_logs,
    read_switch_status,
    write_supervisor_advertisement,
    write_switch_status,
)

__all__ = [
    "SWITCH_LOGS_ROUTE",
    "SWITCH_STATUS_ROUTE",
    "SUPERVISOR_HEALTH_ROUTE",
    "SUPERVISOR_INFO_FILE",
    "SUPERVISOR_LOG_FILE",
    "SWITCH_STATUS_FILE",
    "SwitchObserverServer",
    "append_switch_log",
    "build_switch_observer_payload",
    "cleanup_supervisor_advertisement",
    "cleanup_switch_status",
    "read_supervisor_advertisement",
    "read_switch_logs",
    "read_switch_status",
    "write_supervisor_advertisement",
    "write_switch_status",
]
