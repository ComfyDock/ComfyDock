import argparse

from comfygit_cli.cli import create_parser
from comfygit_cli.global_commands import GlobalCommands


def test_model_delete_parser_accepts_identifier_and_yes():
    parser = create_parser()

    args = parser.parse_args(["model", "delete", "abc123", "--yes"])

    assert args.model_command == "delete"
    assert args.identifier == "abc123"
    assert args.yes is True


def test_model_delete_removes_files_and_index_entries(test_workspace, capsys):
    model_hash = "abc123def4567890"
    models_dir = test_workspace.get_models_directory()
    model_path = models_dir / "checkpoints" / "delete-me.safetensors"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"model")

    test_workspace.model_repository.ensure_model(model_hash, model_path.stat().st_size)
    test_workspace.model_repository.add_location(
        model_hash=model_hash,
        base_directory=models_dir,
        relative_path="checkpoints/delete-me.safetensors",
        filename=model_path.name,
        mtime=model_path.stat().st_mtime,
    )

    commands = GlobalCommands()
    commands.__dict__["workspace"] = test_workspace

    commands.model_delete(argparse.Namespace(identifier=model_hash, yes=True))

    output = capsys.readouterr().out
    assert "Deleted 1 file" in output
    assert "Model index cleaned" in output
    assert not model_path.exists()
    assert test_workspace.model_repository.get_model(model_hash) is None
