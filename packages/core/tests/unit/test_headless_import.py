"""Tests for headless import/materialization manifest handling."""


def test_prepare_headless_import_removes_tracked_manager(test_env) -> None:
    config = test_env.pyproject.load()
    config.setdefault("tool", {}).setdefault("comfygit", {}).setdefault("nodes", {})[
        "comfygit-manager"
    ] = {
        "name": "comfygit-manager",
        "repository": "https://github.com/comfygit-ai/comfygit-manager.git",
        "version": "dev",
        "source": "development",
    }
    config.setdefault("dependency-groups", {})["comfygit-manager-b8a6c4eb"] = [
        "comfygit-core==0.3.22",
        "watchdog>=6.0.0",
    ]
    config["tool"]["comfygit"].setdefault("workflows", {})["smoke"] = {
        "path": "workflows/smoke.json",
    }
    config["tool"]["comfygit"].setdefault("models", {})["abc123"] = {
        "filename": "model.safetensors",
        "relative_path": "checkpoints/model.safetensors",
        "category": "checkpoints",
    }
    test_env.pyproject.save(config)

    test_env._prepare_headless_import()

    updated = test_env.pyproject.load()
    comfygit_config = updated["tool"]["comfygit"]
    assert comfygit_config["headless"] is True
    assert "comfygit-manager" not in comfygit_config.get("nodes", {})
    assert "comfygit-manager-b8a6c4eb" not in updated.get("dependency-groups", {})
