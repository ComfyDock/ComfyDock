"""Unit tests for environment factory."""

from importlib import metadata

from comfygit_core.constants import MANAGER_GITHUB_URL, MANAGER_NODE_ID
from comfygit_core.factories import environment_factory
from comfygit_core.factories.environment_factory import EnvironmentFactory


def test_manager_identifier_uses_github_release(monkeypatch):
    monkeypatch.setattr(metadata, "version", lambda name: "0.0.17")

    identifier = environment_factory._get_manager_install_identifier()

    assert identifier == f"{MANAGER_GITHUB_URL}@v0.0.17"


def test_manager_identifier_falls_back_when_missing(monkeypatch):
    def raise_not_found(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", raise_not_found)

    identifier = environment_factory._get_manager_install_identifier()

    assert identifier == MANAGER_NODE_ID


def test_manager_identifier_falls_back_for_dev_version(monkeypatch):
    monkeypatch.setattr(metadata, "version", lambda name: "0.0.18.dev1")

    identifier = environment_factory._get_manager_install_identifier()

    assert identifier == MANAGER_NODE_ID


class TestCreateInitialPyproject:
    """Tests for _create_initial_pyproject requires-python pinning."""

    def test_requires_python_pins_minor_version(self):
        """requires-python should pin to ==3.12.* not >=3.12."""
        config = EnvironmentFactory._create_initial_pyproject(
            "test-env", "3.12", "v0.3.50"
        )
        assert config["project"]["requires-python"] == "==3.12.*"

    def test_includes_comfygit_system_dependency_group(self):
        config = EnvironmentFactory._create_initial_pyproject(
            "test-env", "3.12", "v0.3.50"
        )
        assert config["dependency-groups"]["comfygit-system"] == ["uv>=0.11.8"]
        assert config["tool"]["uv"]["override-dependencies"] == ["uv>=0.11.8"]

    def test_requires_python_pins_minor_from_patch_version(self):
        """Even if user passes 3.12.7, pin to ==3.12.*."""
        config = EnvironmentFactory._create_initial_pyproject(
            "test-env", "3.12.7", "v0.3.50"
        )
        assert config["project"]["requires-python"] == "==3.12.*"

    def test_requires_python_pins_311(self):
        """Works for Python 3.11."""
        config = EnvironmentFactory._create_initial_pyproject(
            "test-env", "3.11", "v0.3.50"
        )
        assert config["project"]["requires-python"] == "==3.11.*"


def test_create_no_manager_skips_install_and_sets_headless(
    test_workspace, mock_comfyui_clone, mock_github_api, mock_pytorch_probe, monkeypatch
):
    """no_manager=True should skip manager install and persist headless marker."""
    from comfygit_core.managers.node_manager import NodeManager

    def _fail_add_node(self, identifier, *args, **kwargs):  # pragma: no cover - assertion path
        raise AssertionError(f"Unexpected manager install call: {identifier}")

    monkeypatch.setattr(NodeManager, "add_node", _fail_add_node)

    env = test_workspace.create_environment("headless-factory", no_manager=True)
    config = env.pyproject.load()

    assert config["tool"]["comfygit"]["headless"] is True
    nodes = config["tool"]["comfygit"].get("nodes", {})
    assert "comfygit-manager" not in nodes
