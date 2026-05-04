import json
import socket
from urllib.request import urlopen

from comfygit_cli.supervisor_control import SupervisorControlServer


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
    (metadata_dir / ".switch_status.json").write_text(
        json.dumps(
            {
                "state": "syncing",
                "progress": 30,
                "message": "Syncing target environment",
                "target_env": "target",
                "source_env": "source",
            }
        ),
        encoding="utf-8",
    )

    port = _free_port()
    server = SupervisorControlServer(tmp_path, "127.0.0.1", port)
    try:
        server.start()
        server.append_log("Switch request accepted")

        status = _get_json(f"http://127.0.0.1:{port}/v2/comfygit/switch_status")
        logs = _get_json(f"http://127.0.0.1:{port}/v2/comfygit/switch_logs")

        assert status["state"] == "syncing"
        assert status["target_env"] == "target"
        assert logs["logs"][-1]["message"] == "Switch request accepted"
        assert (metadata_dir / ".supervisor_control.json").exists()
    finally:
        server.stop()

    assert not (metadata_dir / ".supervisor_control.json").exists()
