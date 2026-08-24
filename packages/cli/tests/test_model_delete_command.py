import argparse

from comfygit_cli.cli import create_parser
from comfygit_cli.global_commands import GlobalCommands


def test_model_delete_parser_accepts_identifier_and_yes():
    parser = create_parser()

    args = parser.parse_args(["model", "delete", "abc123", "--yes"])

    assert args.model_command == "delete"
    assert args.identifier == "abc123"
    assert args.yes is True
    assert args.apply is False
    assert args.location_id is None


def test_model_delete_parser_supports_explicit_location_apply_and_json():
    parser = create_parser()

    args = parser.parse_args([
        "model", "delete", "abc123", "--location-id", "7", "--apply", "--json"
    ])

    assert args.location_id == 7
    assert args.apply is True
    assert args.json_output is True


def test_model_delete_removes_files_and_index_entries(test_workspace, capsys):
    model_hash = "abc123def4567890"
    models_dir = test_workspace.get_models_directory()
    model_path = models_dir / "checkpoints" / "delete-me.safetensors"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"model")

    test_workspace.model_repository.ensure_model(
        model_hash,
        model_path.stat().st_size,
        blake3_hash="b" * 64,
    )
    test_workspace.model_repository.add_location(
        model_hash=model_hash,
        base_directory=models_dir,
        relative_path="checkpoints/delete-me.safetensors",
        filename=model_path.name,
        mtime=model_path.stat().st_mtime,
    )
    test_workspace.model_repository.add_source(
        model_hash,
        "huggingface",
        "https://huggingface.co/example/model/resolve/main/delete-me.safetensors",
    )

    commands = GlobalCommands()
    commands.__dict__["workspace"] = test_workspace

    commands.model_delete(argparse.Namespace(identifier=model_hash, yes=True))

    output = capsys.readouterr().out
    assert "Deleted 1 selected location" in output
    assert not model_path.exists()
    assert test_workspace.model_repository.get_model(model_hash) is None


def test_model_delete_defaults_to_dry_run(test_workspace, capsys):
    model_hash = "d1e123def4567890"
    models_dir = test_workspace.get_models_directory()
    model_path = models_dir / "checkpoints" / "keep-me.safetensors"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"model")
    test_workspace.model_repository.ensure_model(
        model_hash,
        model_path.stat().st_size,
        blake3_hash="b" * 64,
    )
    test_workspace.model_repository.add_location(
        model_hash=model_hash,
        base_directory=models_dir,
        relative_path="checkpoints/keep-me.safetensors",
        filename=model_path.name,
        mtime=model_path.stat().st_mtime,
    )
    test_workspace.model_repository.add_source(
        model_hash,
        "huggingface",
        "https://huggingface.co/example/model/resolve/main/keep-me.safetensors",
    )
    commands = GlobalCommands()
    commands.__dict__["workspace"] = test_workspace

    commands.model_delete(
        argparse.Namespace(
            identifier=model_hash,
            yes=False,
            apply=False,
            location_id=None,
            all_locations=False,
            allow_referenced=False,
            allow_incomplete_recovery=False,
            json_output=False,
        )
    )

    output = capsys.readouterr().out
    assert "Dry run only" in output
    assert model_path.exists()
