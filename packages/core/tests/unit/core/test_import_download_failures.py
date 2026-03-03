"""Coverage for import behavior when model downloads fail."""

import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from comfygit_core.core.environment import Environment
from comfygit_core.managers.environment_model_manager import EnvironmentModelManager
from comfygit_core.managers.git_manager import GitManager
from comfygit_core.models.exceptions import CDModelDownloadError


def _create_import_tarball(base_dir: Path, pyproject_content: str) -> Path:
    export_content = base_dir / "export_content"
    export_content.mkdir()
    (export_content / "pyproject.toml").write_text(pyproject_content, encoding="utf-8")

    tarball = base_dir / "import_download_failures.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(export_content / "pyproject.toml", arcname="pyproject.toml")
    return tarball


def _minimal_pyproject() -> str:
    return """
[project]
name = "comfygit-env-test"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "v0.3.20"
python_version = "3.12"
nodes = {}
"""


def test_import_raises_after_commit_when_model_downloads_fail(
    test_workspace, tmp_path, mock_comfyui_clone, mock_github_api, mock_pytorch_probe, monkeypatch
):
    """Import should commit changes, then raise CDModelDownloadError on failed downloads."""
    tarball = _create_import_tarball(tmp_path, _minimal_pyproject())
    commit_calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        EnvironmentModelManager,
        "prepare_import_with_model_strategy",
        lambda self, _strategy: ["workflow_a.json"],
    )
    monkeypatch.setattr(
        Environment,
        "resolve_workflow",
        lambda self, **_kwargs: SimpleNamespace(
            download_results=[SimpleNamespace(success=False, filename="missing-model.safetensors")]
        ),
    )
    monkeypatch.setattr(
        Environment,
        "sync",
        lambda self, **_kwargs: SimpleNamespace(success=True, nodes_installed=[], errors=[]),
    )
    monkeypatch.setattr(GitManager, "has_uncommitted_changes", lambda self: True)

    def _track_commit(self, message: str, add_all: bool = True):
        commit_calls.append((message, add_all))

    monkeypatch.setattr(GitManager, "commit_with_identity", _track_commit)

    with pytest.raises(CDModelDownloadError) as exc:
        test_workspace.import_environment(
            tarball_path=tarball,
            name="import-download-failure",
            model_strategy="all",
            no_manager=True,
        )

    assert commit_calls == [("Imported environment", True)]
    assert exc.value.failures == [("workflow_a.json", "missing-model.safetensors")]
    assert "missing-model.safetensors" in str(exc.value)


def test_import_skip_strategy_does_not_resolve_or_raise_on_download_failures(
    test_workspace, tmp_path, mock_comfyui_clone, mock_github_api, mock_pytorch_probe, monkeypatch
):
    """Skip strategy should not resolve workflows and should complete without error."""
    tarball = _create_import_tarball(tmp_path, _minimal_pyproject())

    def _fail_resolve_workflow(self, **_kwargs):
        raise AssertionError("resolve_workflow should not be called")

    monkeypatch.setattr(
        EnvironmentModelManager,
        "prepare_import_with_model_strategy",
        lambda self, _strategy: ["workflow_a.json"],
    )
    monkeypatch.setattr(Environment, "resolve_workflow", _fail_resolve_workflow)
    monkeypatch.setattr(
        Environment,
        "sync",
        lambda self, **_kwargs: SimpleNamespace(success=True, nodes_installed=[], errors=[]),
    )

    env = test_workspace.import_environment(
        tarball_path=tarball,
        name="import-download-skip",
        model_strategy="skip",
        no_manager=True,
    )

    assert env.name == "import-download-skip"
