from pathlib import Path

import pytest

from comfygit_core.utils import filesystem


def test_rmtree_uses_onerror_on_windows_when_onexc_is_unavailable(monkeypatch, tmp_path):
    calls = []

    def fake_rmtree(path, **kwargs):
        calls.append((path, kwargs))

    target = tmp_path / "target"
    target.mkdir()

    monkeypatch.setattr("comfygit_core.utils.filesystem.platform.system", lambda: "Windows")
    monkeypatch.setattr(filesystem, "_SUPPORTS_RMTREE_ONEXC", False)
    monkeypatch.setattr("comfygit_core.utils.filesystem.shutil.rmtree", fake_rmtree)

    filesystem.rmtree(target)

    assert calls == [
        (
            filesystem._windows_long_path(target),
            {
                "ignore_errors": False,
                "onerror": filesystem._handle_remove_readonly,
            },
        )
    ]


def test_rmtree_uses_onexc_on_windows_when_available(monkeypatch, tmp_path):
    calls = []

    def fake_rmtree(path, **kwargs):
        calls.append((path, kwargs))

    target = tmp_path / "target"
    target.mkdir()

    monkeypatch.setattr("comfygit_core.utils.filesystem.platform.system", lambda: "Windows")
    monkeypatch.setattr(filesystem, "_SUPPORTS_RMTREE_ONEXC", True)
    monkeypatch.setattr("comfygit_core.utils.filesystem.shutil.rmtree", fake_rmtree)

    filesystem.rmtree(Path(target), ignore_errors=True)

    assert calls == [
        (
            filesystem._windows_long_path(target),
            {
                "ignore_errors": True,
                "onexc": filesystem._handle_remove_readonly,
            },
        )
    ]


def test_remove_readonly_handler_propagates_retry_failure(monkeypatch, tmp_path):
    target = tmp_path / "locked-file"
    target.write_text("locked")

    monkeypatch.setattr("comfygit_core.utils.filesystem.os.chmod", lambda path, mode: None)

    def fail_again(path):
        raise PermissionError("still locked")

    with pytest.raises(PermissionError, match="still locked"):
        filesystem._handle_remove_readonly(
            fail_again,
            target,
            (PermissionError, PermissionError("locked"), None),
        )
