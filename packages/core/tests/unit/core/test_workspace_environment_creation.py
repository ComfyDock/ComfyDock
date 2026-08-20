import pytest
from comfygit_core.core.environment import Environment
from comfygit_core.models.exceptions import CDEnvironmentExistsError
from comfygit_core.utils.environment_cleanup import (
    DELETED_ENVIRONMENT_PREFIX,
    is_environment_complete,
    mark_environment_complete,
)


def test_create_environment_reclaims_incomplete_leftover_directory(test_workspace, monkeypatch):
    env_path = test_workspace.paths.environments / "test1"
    (env_path / ".cec" / ".venv-probe-stale").mkdir(parents=True)
    (env_path / ".venv").mkdir()

    def fake_create(*, name, env_path, workspace, **kwargs):
        assert not (env_path / ".cec" / ".venv-probe-stale").exists()
        assert not (env_path / ".venv").exists()

        cec_path = env_path / ".cec"
        cec_path.mkdir(parents=True)
        mark_environment_complete(cec_path)
        return Environment(name=name, path=env_path, workspace=workspace)

    monkeypatch.setattr(
        "comfygit_core.core.workspace.EnvironmentFactory.create",
        fake_create,
    )

    environment = test_workspace.create_environment("test1")

    assert environment.name == "test1"
    assert is_environment_complete(env_path / ".cec")


def test_create_environment_reports_incomplete_leftover_when_cleanup_fails(
    test_workspace,
    monkeypatch,
):
    env_path = test_workspace.paths.environments / "test1"
    (env_path / ".cec").mkdir(parents=True)

    monkeypatch.setattr(
        "comfygit_core.core.workspace.cleanup_partial_environment",
        lambda path: False,
    )

    with pytest.raises(CDEnvironmentExistsError, match="incomplete leftover directory"):
        test_workspace.create_environment("test1")


def test_list_environments_ignores_quarantined_environment_directories(test_workspace):
    quarantined_path = (
        test_workspace.paths.environments
        / f"{DELETED_ENVIRONMENT_PREFIX}test1-deadbeef"
    )
    cec_path = quarantined_path / ".cec"
    cec_path.mkdir(parents=True)
    mark_environment_complete(cec_path)

    assert [environment.name for environment in test_workspace.list_environments()] == []
