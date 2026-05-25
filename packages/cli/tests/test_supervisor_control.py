import json
import socket
from urllib.request import urlopen

from comfygit_core.runtime import (
    SUPERVISOR_INFO_FILE,
    SWITCH_LOGS_ROUTE,
    SWITCH_STATUS_FILE,
    SWITCH_STATUS_ROUTE,
    SwitchObserverServer,
    write_switch_status,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get_json(url: str) -> dict:
    with urlopen(url, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def test_supervisor_control_exposes_status_and_logs(tmp_path):
    metadata_dir = tmp_path / ".metadata"
    metadata_dir.mkdir()
    write_switch_status(
        metadata_dir,
        state="syncing",
        progress=30,
        message="Syncing target environment",
        target_env="target",
        source_env="source",
    )

    port = _free_port()
    server = SwitchObserverServer(tmp_path, "127.0.0.1", port, kind="manager_orchestrator")
    try:
        server.start()
        server.append_log("Switch request accepted")

        status = _get_json(f"http://127.0.0.1:{port}{SWITCH_STATUS_ROUTE}")
        logs = _get_json(f"http://127.0.0.1:{port}{SWITCH_LOGS_ROUTE}")

        assert status["state"] == "syncing"
        assert status["target_env"] == "target"
        assert logs["logs"][-1]["message"] == "Switch request accepted"
        assert (metadata_dir / SUPERVISOR_INFO_FILE).exists()
        assert json.loads((metadata_dir / SUPERVISOR_INFO_FILE).read_text())["kind"] == "manager_orchestrator"
        assert (metadata_dir / SWITCH_STATUS_FILE).exists()
    finally:
        server.stop()

    assert not (metadata_dir / SUPERVISOR_INFO_FILE).exists()
