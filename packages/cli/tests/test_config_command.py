import argparse
import io
from unittest.mock import Mock

import pytest
from comfygit_cli.cli import create_parser
from comfygit_cli.global_commands import GlobalCommands
from comfygit_core.models import (
    CredentialMigrationResult,
    CredentialProvider,
    CredentialSource,
    CredentialStatus,
)


def test_config_rejects_secret_values_in_argv():
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["config", "--huggingface-token", "hf_test"])


def test_auth_set_accepts_only_provider_and_stdin_switch():
    parser = create_parser()

    args = parser.parse_args(["auth", "set", "huggingface", "--token-stdin"])

    assert args.command == "auth"
    assert args.provider == "huggingface"
    assert args.token_stdin is True

    with pytest.raises(SystemExit):
        parser.parse_args(["auth", "set", "huggingface", "hf_secret"])


def test_auth_set_reads_secret_from_stdin_without_rendering_it(monkeypatch, capsys):
    commands = GlobalCommands()
    workspace = Mock()
    commands.__dict__["workspace"] = workspace
    monkeypatch.setattr("sys.stdin", io.StringIO("hf_secret\n"))

    GlobalCommands.auth_set.__wrapped__(
        commands,
        argparse.Namespace(provider="huggingface", token_stdin=True),
    )

    workspace.set_huggingface_token.assert_called_once_with("hf_secret")
    assert "hf_secret" not in capsys.readouterr().out


def test_auth_status_reports_source_without_loading_or_displaying_secret(capsys):
    commands = GlobalCommands()
    workspace = Mock()
    commands.__dict__["workspace"] = workspace
    workspace.get_credential_status.side_effect = lambda provider: CredentialStatus(
        provider=provider,
        configured=provider == CredentialProvider.HUGGINGFACE,
        source=(
            CredentialSource.PROVIDER_NATIVE
            if provider == CredentialProvider.HUGGINGFACE
            else CredentialSource.NONE
        ),
    )

    GlobalCommands.auth_status.__wrapped__(commands, argparse.Namespace())

    output = capsys.readouterr().out
    assert "Hugging Face   Configured (provider login)" in output
    assert "CivitAI        Not configured (not configured)" in output
    workspace.get_huggingface_token.assert_not_called()


def test_auth_login_uses_huggingface_native_flow(monkeypatch, capsys):
    commands = GlobalCommands()
    workspace = Mock()
    commands.__dict__["workspace"] = workspace
    workspace.get_credential_status.return_value = CredentialStatus(
        CredentialProvider.HUGGINGFACE,
        True,
        CredentialSource.PROVIDER_NATIVE,
    )
    login = Mock()
    monkeypatch.setattr("huggingface_hub.login", login)

    GlobalCommands.auth_login.__wrapped__(
        commands,
        argparse.Namespace(provider="huggingface", force=True),
    )

    login.assert_called_once_with(skip_if_logged_in=False)
    assert "login configured" in capsys.readouterr().out


def test_auth_migrate_reports_provider_names_without_secrets(capsys):
    commands = GlobalCommands()
    workspace = Mock()
    commands.__dict__["workspace"] = workspace
    workspace.migrate_credentials.return_value = CredentialMigrationResult(
        migrated=(CredentialProvider.CIVITAI,),
        retained=(CredentialProvider.HUGGINGFACE,),
        errors=("huggingface: secure storage unavailable",),
    )

    with pytest.raises(SystemExit) as exc_info:
        GlobalCommands.auth_migrate.__wrapped__(commands, argparse.Namespace())

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "civitai" in captured.out
    assert "huggingface" in captured.err
    assert "secret" not in captured.out + captured.err


def test_auth_login_and_migrate_parser_surface():
    parser = create_parser()

    login_args = parser.parse_args(["auth", "login", "huggingface", "--force"])
    migrate_args = parser.parse_args(["auth", "migrate"])

    assert login_args.provider == "huggingface"
    assert login_args.force is True
    assert migrate_args.auth_command == "migrate"
