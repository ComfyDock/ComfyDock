from comfygit_cli import cli


class _FakeStream:
    def __init__(self):
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


def test_configure_stdio_encoding_sets_replacement_errors_on_windows(monkeypatch):
    stdout = _FakeStream()
    stderr = _FakeStream()

    monkeypatch.setattr(cli.os, "name", "nt")
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)

    cli._configure_stdio_encoding()

    assert stdout.calls == [{"errors": "replace"}]
    assert stderr.calls == [{"errors": "replace"}]


def test_configure_stdio_encoding_does_not_touch_non_windows(monkeypatch):
    stdout = _FakeStream()

    monkeypatch.setattr(cli.os, "name", "posix")
    monkeypatch.setattr(cli.sys, "stdout", stdout)

    cli._configure_stdio_encoding()

    assert stdout.calls == []
