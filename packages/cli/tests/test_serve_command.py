"""Tests for the `cg serve` command wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from comfygit_cli.cli import create_parser
from comfygit_cli.env_commands import EnvironmentCommands
from comfygit_cli.serve_runtime import ComfyUIClient


def test_serve_parser_defaults() -> None:
    parser = create_parser()

    args = parser.parse_args(["-e", "demo", "serve"])

    assert args.command == "serve"
    assert args.target_env == "demo"
    assert args.host == "127.0.0.1"
    assert args.port == 8190
    assert args.comfy_url == "http://127.0.0.1:8188"


def test_serve_parser_accepts_runtime_options() -> None:
    parser = create_parser()

    args = parser.parse_args(
        [
            "-e",
            "demo",
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--comfy-url",
            "http://127.0.0.1:8189",
        ]
    )

    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.comfy_url == "http://127.0.0.1:8189"


@patch("comfygit_cli.env_commands.get_workspace_or_exit")
@patch("comfygit_cli.serve_runtime.serve_environment")
def test_serve_command_uses_selected_environment(mock_serve, mock_workspace) -> None:
    mock_env = MagicMock()
    mock_env.name = "demo"
    mock_workspace.return_value.get_environment.return_value = mock_env

    cmd = EnvironmentCommands()
    parser = create_parser()
    args = parser.parse_args(["-e", "demo", "serve", "--port", "9000"])

    cmd.serve(args)

    mock_workspace.return_value.get_environment.assert_any_call("demo")
    mock_serve.assert_called_once()
    called_env, called_config = mock_serve.call_args.args
    assert called_env is mock_env
    assert called_config.port == 9000


@patch("comfygit_cli.serve_runtime.requests.post")
def test_comfyui_client_submit_prompt_returns_prompt_id(mock_post) -> None:
    response = MagicMock()
    response.json.return_value = {"prompt_id": "abc123"}
    mock_post.return_value = response

    client = ComfyUIClient("http://127.0.0.1:8188")

    assert client.submit_prompt({"1": {"class_type": "Test", "inputs": {}}}) == "abc123"
    response.raise_for_status.assert_called_once()
    mock_post.assert_called_once()


@patch("comfygit_cli.serve_runtime.requests.get")
def test_comfyui_client_unwraps_prompt_history(mock_get) -> None:
    response = MagicMock()
    response.json.return_value = {
        "abc123": {
            "outputs": {
                "9": {
                    "images": [
                        {"filename": "image.png", "subfolder": "", "type": "output"}
                    ]
                }
            }
        }
    }
    mock_get.return_value = response

    client = ComfyUIClient("http://127.0.0.1:8188")

    assert client.get_history("abc123") == response.json.return_value["abc123"]
