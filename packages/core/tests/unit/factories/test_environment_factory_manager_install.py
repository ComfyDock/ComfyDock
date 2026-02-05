"""Unit tests for manager install identifier resolution."""

from importlib import metadata

from comfygit_core.constants import MANAGER_GITHUB_URL, MANAGER_NODE_ID
from comfygit_core.factories import environment_factory


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
