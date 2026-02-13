from __future__ import annotations

import argparse

from comfygit_cli import update_commands


def test_cg_update_check_prints_notice(monkeypatch, capsys):
    monkeypatch.setattr(
        update_commands.update_checker,
        "check_for_update",
        lambda **kwargs: update_commands.update_checker.UpdateCheckResult(
            current_version="0.1.0",
            latest_version="0.2.0",
            update_available=True,
            should_notify=True,
        ),
    )
    marked = {"v": None}
    monkeypatch.setattr(update_commands.update_checker, "mark_notified", lambda v, **k: marked.__setitem__("v", v))
    monkeypatch.setattr(update_commands.update_checker, "format_update_notice", lambda c, l: f"{c}->{l}")

    cmd = update_commands.UpdateCommands()
    cmd.update(argparse.Namespace(check=True))

    out = capsys.readouterr().out
    assert "0.1.0->0.2.0" in out
    assert "Releases:" in out
    assert marked["v"] == "0.2.0"


def test_cg_update_prefers_uv_tool_when_detected(monkeypatch, capsys):
    monkeypatch.setattr(update_commands.update_checker, "get_current_version", lambda: "0.1.0")
    monkeypatch.setattr(update_commands, "_uv_available", lambda: True)
    monkeypatch.setattr(update_commands, "_installed_via_uv_tool", lambda: True)
    monkeypatch.setattr(update_commands, "_pip_available", lambda: True)

    ran = {"cmd": None}

    def _run(cmd):
        ran["cmd"] = cmd
        return 0

    monkeypatch.setattr(update_commands, "_run", _run)

    cmd = update_commands.UpdateCommands()
    cmd.update(argparse.Namespace(check=False))

    assert ran["cmd"] == ["uv", "tool", "upgrade", "comfygit"]
    assert "Updated." in capsys.readouterr().out

