"""Smoke tests for the public comfygit_core import surface."""

from importlib import import_module


def test_core_entrypoints_are_importable():
    """Root and core package entrypoints should expose Environment/Workspace."""
    from comfygit_core import Environment, Workspace
    from comfygit_core.core import Environment as CoreEnvironment
    from comfygit_core.core import Workspace as CoreWorkspace

    assert Environment is CoreEnvironment
    assert Workspace is CoreWorkspace


def test_subpackages_import_and_define_all():
    """Every subpackage should import cleanly and expose a non-empty __all__."""
    subpackages = [
        "analyzers",
        "caching",
        "clients",
        "configs",
        "core",
        "factories",
        "infrastructure",
        "integrations",
        "logging",
        "managers",
        "merging",
        "models",
        "repositories",
        "resolvers",
        "services",
        "strategies",
        "utils",
        "validation",
    ]

    for package in subpackages:
        module = import_module(f"comfygit_core.{package}")
        exports = getattr(module, "__all__", None)
        assert isinstance(exports, (list, tuple)), f"{package} missing __all__ sequence"
        assert exports, f"{package} has empty __all__"

        # Verify every declared public symbol is actually resolvable.
        for export_name in exports:
            assert hasattr(module, export_name), (
                f"{package} export '{export_name}' is declared but not importable"
            )


def test_key_public_symbols_are_accessible():
    """Key convenience imports should resolve without direct module imports."""
    from comfygit_core.managers import GitManager, NodeManager
    from comfygit_core.models import ModelInfo, NodeInfo
    from comfygit_core.utils import pytorch_prober

    assert GitManager.__name__ == "GitManager"
    assert NodeManager.__name__ == "NodeManager"
    assert NodeInfo.__name__ == "NodeInfo"
    assert ModelInfo.__name__ == "ModelInfo"
    assert pytorch_prober.__name__.endswith("pytorch_prober")
