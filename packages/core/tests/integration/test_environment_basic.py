"""Integration tests for basic environment operations."""


import pytest
from comfygit_core.factories.workspace_factory import WorkspaceFactory
from comfygit_core.models.exceptions import CDEnvironmentNotFoundError


def test_workspace_operations(tmp_path):
    """Test basic workspace operations - this works."""
    workspace_path = tmp_path / "test_workspace"

    # Initialize workspace
    workspace = WorkspaceFactory.create(workspace_path)

    # Verify workspace structure created
    assert workspace.path.exists()
    assert (workspace.path / ".metadata").exists()
    assert (workspace.path / "environments").exists()
    assert (workspace.path / "comfygit_cache").exists()

    # List environments (should be empty)
    environments = workspace.list_environments()
    assert len(environments) == 0


def test_environment_lifecycle_with_subprocess_mock(tmp_path, mock_comfyui_clone, mock_github_api):
    """Test environment lifecycle with mocked external dependencies."""
    import json

    # Create workspace
    workspace_path = tmp_path / "test_workspace"
    workspace = WorkspaceFactory.create(workspace_path)

    # Create empty node mappings file to avoid network fetch
    custom_nodes_cache = workspace.paths.cache / "custom_nodes"
    custom_nodes_cache.mkdir(parents=True, exist_ok=True)
    node_mappings = custom_nodes_cache / "node_mappings.json"
    with open(node_mappings, 'w') as f:
        json.dump({"mappings": {}, "packages": {}, "stats": {}}, f)

    # Set models directory (required for environment creation)
    models_dir = workspace_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    workspace.set_models_directory(models_dir)

    # Create environment (now using mocked clone from fixtures)
    env = workspace.create_environment(
        name="test-env",
        python_version="3.11",
        comfyui_version="master"
    )

    # Verify environment created
    assert env.name == "test-env"
    assert env.path.exists()

    # List environments
    environments = workspace.list_environments()
    assert len(environments) == 1
    assert environments[0].name == "test-env"

    # Set as active
    workspace.set_active_environment("test-env")
    active = workspace.get_active_environment()
    assert active.name == "test-env"

    # Delete environment
    workspace.delete_environment("test-env")

    # Verify deleted
    assert not env.path.exists()
    environments = workspace.list_environments()
    assert len(environments) == 0


def test_environment_errors(tmp_path):
    """Test error handling without environment creation."""

    workspace_path = tmp_path / "test_workspace"
    workspace = WorkspaceFactory.create(workspace_path)

    # Test that we can't delete non-existent environment
    with pytest.raises(CDEnvironmentNotFoundError):
        workspace.delete_environment("non-existent")

    # Test that we can't set non-existent environment as active
    with pytest.raises(CDEnvironmentNotFoundError):
        workspace.set_active_environment("non-existent")

    # Test getting non-existent environment raises error
    with pytest.raises(CDEnvironmentNotFoundError):
        workspace.get_environment("non-existent")
