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
        assert config["dependency-groups"]["comfygit-system"] == ["uv>=0.7"]

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
