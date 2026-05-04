from pathlib import Path

from comfygit_core.factories.environment_factory import EnvironmentFactory
from comfygit_core.models.materialization import MaterializeResult
from comfygit_core.utils.environment_cleanup import mark_environment_complete


def _write_portable_source(source: Path) -> None:
    source.mkdir(parents=True)
    (source / "pyproject.toml").write_text(
        """
[project]
name = "comfygit-env-source"
version = "0.1.0"
dependencies = []

[tool.comfygit]
schema_version = 2
comfyui_version = "v0.4.0"
python_version = "3.12"
nodes = {}
""".strip(),
        encoding="utf-8",
    )
    (source / ".python-version").write_text("3.12\n", encoding="utf-8")
    (source / "package_config.toml").write_text("[package]\n", encoding="utf-8")
    (source / "workflows").mkdir()
    (source / "workflows" / "test.json").write_text("{}", encoding="utf-8")
    (source / "workflow_api").mkdir()
    (source / "workflow_api" / "test.api.json").write_text("{}", encoding="utf-8")
    (source / "overlays").mkdir()
    (source / "overlays" / "shared.toml").write_text("[overlay]\n", encoding="utf-8")
    (source / "overlays" / ".local.toml").write_text("[overlay]\n", encoding="utf-8")
    (source / ".venv").mkdir()
    (source / ".complete").write_text("", encoding="utf-8")


def test_import_from_directory_copies_only_portable_files(test_workspace, tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_portable_source(source)

    env_path = test_workspace.paths.environments / "materialized"

    env = EnvironmentFactory.import_from_directory(
        source_path=source,
        name="materialized",
        env_path=env_path,
        workspace=test_workspace,
        torch_backend="cpu",
    )

    assert env.name == "materialized"
    assert (env.cec_path / "pyproject.toml").exists()
    assert (env.cec_path / ".python-version").read_text(encoding="utf-8") == "3.12\n"
    assert (env.cec_path / "package_config.toml").exists()
    assert (env.cec_path / "workflows" / "test.json").exists()
    assert (env.cec_path / "workflow_api" / "test.api.json").exists()
    assert (env.cec_path / "overlays" / "shared.toml").exists()
    assert not (env.cec_path / "overlays" / ".local.toml").exists()
    assert not (env.cec_path / ".venv").exists()
    assert not (env.cec_path / ".complete").exists()


def test_materialize_environment_uses_runtime_defaults(test_workspace, tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    _write_portable_source(source)
    calls: dict[str, object] = {}

    class FakeEnvironment:
        name = "runtime-env"

        def __init__(self, env_path: Path):
            self.path = env_path
            self.cec_path = env_path / ".cec"
            self.comfyui_path = env_path / "ComfyUI"
            self.torch_backend = "auto"
            self.cec_path.mkdir(parents=True)
            self.comfyui_path.mkdir(parents=True)

        def finalize_import(self, **kwargs):
            calls["finalize_kwargs"] = kwargs
            mark_environment_complete(self.cec_path)

    def fake_import_from_directory(**kwargs):
        calls["factory_kwargs"] = kwargs
        return FakeEnvironment(kwargs["env_path"])

    monkeypatch.setattr(EnvironmentFactory, "import_from_directory", fake_import_from_directory)

    result = test_workspace.materialize_environment(source, "runtime-env")

    assert isinstance(result, MaterializeResult)
    assert result.environment_name == "runtime-env"
    assert result.source_type == "directory"
    assert result.model_strategy == "skip"

    finalize_kwargs = calls["finalize_kwargs"]
    assert finalize_kwargs["model_strategy"] == "skip"
    assert finalize_kwargs["no_manager"] is True
    assert finalize_kwargs["create_import_commit"] is False
    assert finalize_kwargs["fail_on_sync_errors"] is True


def test_materialize_sets_models_dir_before_environment_construction(test_workspace, tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    _write_portable_source(source)
    events: list[str] = []

    original_set_models_directory = test_workspace.set_models_directory

    def wrapped_set_models_directory(path: Path, progress=None):
        events.append("set_models_directory")
        return original_set_models_directory(path, progress=progress)

    class FakeEnvironment:
        name = "runtime-env"
        torch_backend = "auto"

        def __init__(self, env_path: Path):
            events.append("construct_environment")
            self.path = env_path
            self.cec_path = env_path / ".cec"
            self.comfyui_path = env_path / "ComfyUI"
            self.cec_path.mkdir(parents=True)
            self.comfyui_path.mkdir(parents=True)

        def finalize_import(self, **kwargs):
            mark_environment_complete(self.cec_path)

    monkeypatch.setattr(test_workspace, "set_models_directory", wrapped_set_models_directory)
    monkeypatch.setattr(
        EnvironmentFactory,
        "import_from_directory",
        lambda **kwargs: FakeEnvironment(kwargs["env_path"]),
    )

    test_workspace.materialize_environment(source, "runtime-env", models_dir=models_dir)

    assert events == ["set_models_directory", "construct_environment"]
