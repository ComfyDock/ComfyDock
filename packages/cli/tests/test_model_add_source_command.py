import argparse
from types import SimpleNamespace

import pytest
from comfygit_cli.global_commands import GlobalCommands


class _WorkspaceWithoutActiveEnv:
    def get_active_environment(self):
        return None


class _WorkspaceWithNamedEnv:
    def __init__(self, env):
        self.env = env
        self.requested_name = None

    def get_environment(self, name):
        self.requested_name = name
        return self.env


class _SourceEnv:
    def __init__(self):
        self.calls = []

    def add_model_source(self, identifier, url):
        self.calls.append((identifier, url))
        return SimpleNamespace(
            success=True,
            model=SimpleNamespace(filename="model.safetensors"),
        )


def test_model_add_source_requires_active_or_target_environment(capsys):
    commands = GlobalCommands()
    commands.__dict__["workspace"] = _WorkspaceWithoutActiveEnv()

    with pytest.raises(SystemExit) as exc_info:
        commands.model_add_source(
            argparse.Namespace(
                model="abc123",
                url="https://example.com/model.safetensors",
                target_env=None,
            )
        )

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "No active environment" in err
    assert "cg use <name>" in err


def test_model_add_source_respects_target_environment(capsys):
    env = _SourceEnv()
    workspace = _WorkspaceWithNamedEnv(env)
    commands = GlobalCommands()
    commands.__dict__["workspace"] = workspace

    commands.model_add_source(
        argparse.Namespace(
            model="abc123",
            url="https://example.com/model.safetensors",
            target_env="target-env",
        )
    )

    assert workspace.requested_name == "target-env"
    assert env.calls == [("abc123", "https://example.com/model.safetensors")]
    assert "Added source" in capsys.readouterr().out
