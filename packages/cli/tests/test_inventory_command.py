import argparse
import json

from comfygit_cli.cli import create_parser
from comfygit_cli.global_commands import GlobalCommands


def test_inventory_parser_accepts_json():
    args = create_parser().parse_args(["inventory", "--json"])

    assert args.json_output is True
    assert args.storage is False
    assert args.func.__name__ == "inventory"


def test_inventory_parser_accepts_explicit_storage_measurement():
    args = create_parser().parse_args(["inventory", "--storage"])

    assert args.storage is True


def test_inventory_json_uses_typed_core_projection(test_workspace, capsys):
    commands = GlobalCommands()
    commands.__dict__["workspace"] = test_workspace

    commands.inventory(argparse.Namespace(json_output=True))

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 2
    assert payload["kind"] == "workspace_inventory"
    assert payload["workspace_path"] == str(test_workspace.path)
    assert payload["models_directory"] == str(test_workspace.get_models_directory())
    assert payload["models"] == []
    assert payload["environments"] == []


def test_model_index_list_json_uses_model_inventory(test_workspace, capsys):
    models_dir = test_workspace.get_models_directory()
    model_path = models_dir / "checkpoints" / "inventory.safetensors"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"model")
    model_hash = test_workspace.model_repository.calculate_short_hash(model_path)
    test_workspace.model_repository.ensure_model(
        model_hash,
        model_path.stat().st_size,
        blake3_hash="b" * 64,
    )
    test_workspace.model_repository.add_location(
        model_hash,
        models_dir,
        "checkpoints/inventory.safetensors",
        model_path.name,
        model_path.stat().st_mtime,
    )
    commands = GlobalCommands()
    commands.__dict__["workspace"] = test_workspace

    commands.model_index_list(argparse.Namespace(json_output=True, duplicates=False))

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["short_hash"] == model_hash
    assert payload[0]["locations"][0]["relative_path"] == "checkpoints/inventory.safetensors"
