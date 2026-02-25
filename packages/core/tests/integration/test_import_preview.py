"""Integration tests for import preview functionality."""
import json
import tempfile
from pathlib import Path

import pytest
import tomlkit
from comfygit_core.factories.workspace_factory import WorkspaceFactory


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace_path = Path(temp_dir) / "workspace"
        workspace = WorkspaceFactory.create(workspace_path)

        # Create minimal registry data files to avoid network dependency
        cache_dir = workspace_path / "comfygit_cache" / "custom_nodes"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Create empty node_mappings.json
        mappings_file = cache_dir / "node_mappings.json"
        with open(mappings_file, "w") as f:
            json.dump({"mappings": []}, f)

        yield workspace


@pytest.fixture
def sample_cec_dir():
    """Create a sample .cec directory structure."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cec_path = Path(temp_dir) / ".cec"
        cec_path.mkdir()

        # Create pyproject.toml
        pyproject_data = {
            "tool": {
                "comfygit": {
                    "comfyui_version": "v0.2.7",
                    "comfyui_version_type": "release",
                    "models": {
                        "abc123": {
                            "filename": "model1.safetensors",
                            "relative_path": "checkpoints/model1.safetensors",
                            "sources": ["https://example.com/model1.safetensors"]
                        },
                        "def456": {
                            "filename": "model2.safetensors",
                            "relative_path": "loras/model2.safetensors",
                            "sources": []
                        }
                    },
                    "nodes": {
                        "rgthree-comfy": {
                            "source": "registry"
                        }
                    },
                    "workflows": {
                        "workflow1": {
                            "models": [
                                {"hash": "abc123", "criticality": "required"}
                            ]
                        }
                    }
                }
            }
        }

        pyproject_path = cec_path / "pyproject.toml"
        with open(pyproject_path, "w") as f:
            tomlkit.dump(pyproject_data, f)

        yield cec_path


def test_analyze_import_returns_analysis(temp_workspace, sample_cec_dir):
    """Test that import analyzer returns analysis."""
    # Analyze directly using ImportAnalyzer
    analysis = temp_workspace.import_analyzer.analyze_import(sample_cec_dir)

    # Verify analysis contents
    assert analysis.total_models == 2
    assert analysis.total_nodes == 1
    assert analysis.total_workflows == 1
    assert analysis.total_overlays == 0
    assert analysis.comfyui_version == "v0.2.7"
    assert analysis.comfyui_version_type == "release"

    # Verify no environment was created
    environments = temp_workspace.list_environments()
    assert len(environments) == 0


def test_analyze_import_model_breakdown(temp_workspace, sample_cec_dir):
    """Test that preview correctly analyzes model availability."""
    analysis = temp_workspace.import_analyzer.analyze_import(sample_cec_dir)

    # Both models should not be locally available (fresh workspace)
    assert analysis.models_locally_available == 0
    assert analysis.models_needing_download == 1  # abc123 has source
    assert analysis.models_without_sources == 1  # def456 has no source
    assert analysis.needs_model_downloads is True


def test_analyze_import_node_breakdown(temp_workspace, sample_cec_dir):
    """Test that preview correctly analyzes nodes."""
    analysis = temp_workspace.import_analyzer.analyze_import(sample_cec_dir)

    assert analysis.total_nodes == 1
    assert analysis.registry_nodes == 1
    assert analysis.dev_nodes == 0
    assert analysis.git_nodes == 0


def test_download_strategy_recommendation(temp_workspace, sample_cec_dir):
    """Test that download strategy recommendation is correct."""
    analysis = temp_workspace.import_analyzer.analyze_import(sample_cec_dir)

    # Has models without sources, should recommend "required"
    assert analysis.get_download_strategy_recommendation() == "required"
