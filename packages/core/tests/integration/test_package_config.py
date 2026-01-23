"""Integration tests for package configuration."""

from pathlib import Path


def test_new_environment_has_package_config(test_workspace, mock_comfyui_clone, mock_github_api):
    """Test that creating a new environment automatically creates package_config.toml."""
    import json

    # Create empty node mappings to avoid network fetch
    custom_nodes_cache = test_workspace.paths.cache / "custom_nodes"
    custom_nodes_cache.mkdir(parents=True, exist_ok=True)
    node_mappings = custom_nodes_cache / "node_mappings.json"
    with open(node_mappings, 'w') as f:
        json.dump({"mappings": {}, "packages": {}, "stats": {}}, f)

    # Set models directory
    models_dir = test_workspace.path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    test_workspace.set_models_directory(models_dir)

    # Create environment
    env = test_workspace.create_environment(
        name="test-env",
        python_version="3.11",
        comfyui_version="master"
    )

    # Verify package_config.toml exists
    package_config_path = env.cec_path / "package_config.toml"
    assert package_config_path.exists(), "package_config.toml should be created automatically"

    # Verify it has the expected structure
    import tomlkit
    with open(package_config_path) as f:
        config = tomlkit.load(f)

    # Check for substitutions section
    assert "substitutions" in config
    assert config["substitutions"].get("opencv-python") == "opencv-python-headless"

    # Check for exclude section
    assert "exclude" in config
    assert "packages" in config["exclude"]
    assert "opencv-python" in config["exclude"]["packages"]


def test_environment_pyproject_has_exclude_dependencies(test_workspace, mock_comfyui_clone, mock_github_api):
    """Test that new environment's pyproject.toml includes exclude-dependencies."""
    import json

    # Create empty node mappings to avoid network fetch
    custom_nodes_cache = test_workspace.paths.cache / "custom_nodes"
    custom_nodes_cache.mkdir(parents=True, exist_ok=True)
    node_mappings = custom_nodes_cache / "node_mappings.json"
    with open(node_mappings, 'w') as f:
        json.dump({"mappings": {}, "packages": {}, "stats": {}}, f)

    # Set models directory
    models_dir = test_workspace.path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    test_workspace.set_models_directory(models_dir)

    # Create environment
    env = test_workspace.create_environment(
        name="test-env",
        python_version="3.11",
        comfyui_version="master"
    )

    # Load pyproject.toml
    config = env.pyproject.load()

    # Verify exclude-dependencies exists
    assert "tool" in config
    assert "uv" in config["tool"]
    assert "exclude-dependencies" in config["tool"]["uv"]

    # Verify it includes opencv-python
    exclusions = config["tool"]["uv"]["exclude-dependencies"]
    assert "opencv-python" in exclusions
