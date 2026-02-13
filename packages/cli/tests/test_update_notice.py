from __future__ import annotations

import threading

from comfygit_cli.utils import update_notice


def test_maybe_print_update_notice_prints_once(monkeypatch, capsys):
    notified = {"latest": None}

    def _mark(latest, **kwargs):
        notified["latest"] = latest

    monkeypatch.setattr(update_notice.update_checker, "mark_notified", _mark)
    monkeypatch.setattr(update_notice.update_checker, "format_update_notice", lambda c, l: f"{c}->{l}")

    done = threading.Event()
    done.set()
    handle = update_notice.UpdateCheckHandle(
        done=done,
        result=update_notice.update_checker.UpdateCheckResult(
            current_version="0.1.0",
            latest_version="0.2.0",
            update_available=True,
            should_notify=True,
        ),
    )

    update_notice.maybe_print_update_notice(handle)
    out = capsys.readouterr()
    assert out.err.strip() == "0.1.0->0.2.0"
    assert notified["latest"] == "0.2.0"


def test_maybe_print_update_notice_noop_when_not_done(capsys):
    handle = update_notice.UpdateCheckHandle(done=threading.Event(), result=None)
    update_notice.maybe_print_update_notice(handle)
    out = capsys.readouterr()
    assert out.err == ""

