from __future__ import annotations

from datetime import datetime, timedelta, timezone

from comfygit_cli.utils import update_checker

UTC = timezone.utc


class _Resp:
    def __init__(self, v: str):
        self._v = v

    def raise_for_status(self) -> None:
        return

    def json(self):
        return {"info": {"version": self._v}}


def test_update_checker_caches_for_24h(monkeypatch, tmp_path):
    calls = {"n": 0}

    def _fake_get(url, timeout):
        assert "pypi.org/pypi/comfygit/json" in url
        assert timeout <= 2.0
        calls["n"] += 1
        return _Resp("0.9.0")

    monkeypatch.setattr(update_checker, "get_current_version", lambda: "0.1.0")
    monkeypatch.setattr(update_checker.requests, "get", _fake_get)

    now = datetime(2026, 2, 10, 0, 0, 0, tzinfo=UTC)
    r1 = update_checker.check_for_update(now=now, config_dir=tmp_path, environ={})
    assert r1 is not None
    assert r1.latest_version == "0.9.0"
    assert r1.update_available is True
    assert calls["n"] == 1

    # Within 24h, should use cache and not hit network again.
    r2 = update_checker.check_for_update(
        now=now + timedelta(hours=23),
        config_dir=tmp_path,
        environ={},
    )
    assert r2 is not None
    assert r2.latest_version == "0.9.0"
    assert calls["n"] == 1


def test_update_checker_respects_no_update_env(monkeypatch, tmp_path):
    def _boom(*args, **kwargs):
        raise AssertionError("network call should not happen when disabled")

    monkeypatch.setattr(update_checker, "get_current_version", lambda: "0.1.0")
    monkeypatch.setattr(update_checker.requests, "get", _boom)

    res = update_checker.check_for_update(
        now=datetime(2026, 2, 10, 0, 0, 0, tzinfo=UTC),
        config_dir=tmp_path,
        environ={"COMFYGIT_NO_UPDATE_CHECK": "1"},
    )
    assert res is None


def test_update_checker_mark_notified_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(update_checker, "get_current_version", lambda: "0.1.0")
    now = datetime(2026, 2, 10, 0, 0, 0, tzinfo=UTC)

    update_checker.mark_notified("1.2.3", config_dir=tmp_path, now=now)
    state = update_checker.load_state(update_checker.get_cache_path(tmp_path))
    assert state.last_notified_latest_version == "1.2.3"
