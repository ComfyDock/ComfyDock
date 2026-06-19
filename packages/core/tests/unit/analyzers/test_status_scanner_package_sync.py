from pathlib import Path
from unittest.mock import MagicMock

from comfygit_core.analyzers.status_scanner import StatusScanner


def test_package_sync_check_passes_backend_override_to_uv(tmp_path: Path):
    uv = MagicMock()
    uv.sync_project.return_value = ""
    pyproject = MagicMock()
    pyproject.resolve_sync_extras.return_value = ([], False)

    scanner = StatusScanner(
        uv=uv,
        pyproject=pyproject,
        venv_path=tmp_path / ".venv",
        comfyui_path=tmp_path / "ComfyUI",
        pytorch_manager=MagicMock(),
    )

    status = scanner.check_packages_sync(backend_override="cu126")

    assert status.in_sync is True
    uv.sync_project.assert_called_once()
    assert uv.sync_project.call_args.kwargs["backend_override"] == "cu126"
