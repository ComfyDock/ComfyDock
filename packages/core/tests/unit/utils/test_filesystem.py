from pathlib import Path

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
            target,
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
            target,
            {
                "ignore_errors": True,
                "onexc": filesystem._handle_remove_readonly,
            },
        )
    ]
