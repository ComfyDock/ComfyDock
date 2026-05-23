"""Tests for Environment facade methods that hide manager internals from adapters."""

from __future__ import annotations


def test_runtime_config_facades_expose_manifest_and_torch_state(test_env):
    status = test_env.get_torch_backend_status()

    assert status.backend == "cu121"
    assert status.is_configured is True
    assert status.backend_file == test_env.cec_path / ".pytorch-backend"
    assert test_env.get_python_version() == "3.12"
    assert test_env.get_manifest_path() == test_env.pyproject.path
    assert test_env.load_manifest_config()["project"]["name"] == "comfygit-env-test-env"


def test_dependency_group_removal_facade_returns_typed_result(test_env):
    config = test_env.pyproject.load()
    config["dependency-groups"] = {
        "optional-cuda": ["sageattention>=1.0", "xformers"],
    }
    test_env.pyproject.save(config)

    result = test_env.remove_dependencies_from_group(
        "optional-cuda",
        ["sageattention", "missing-package"],
    )

    assert result.removed == ["sageattention"]
    assert result.skipped == ["missing-package"]
    assert result.to_dict() == {
        "removed": ["sageattention"],
        "skipped": ["missing-package"],
    }


def test_overlay_facades_create_and_activate_template(test_env):
    created = test_env.create_overlay_template("facade-test")

    assert created.created is True
    assert created.scope == "shared"
    assert created.path.exists()
    assert "[overlay]" in created.path.read_text(encoding="utf-8")

    overlays = {overlay.name: overlay for overlay in test_env.list_overlays()}
    assert overlays["facade-test"].is_active is False

    enabled = test_env.enable_overlay("facade-test")
    assert enabled.name == "facade-test"
    assert enabled.changed is True
    assert enabled.is_compatible is True

    enabled_again = test_env.enable_overlay("facade-test")
    assert enabled_again.changed is False

    disabled = test_env.disable_overlay("facade-test")
    assert disabled.changed is True
