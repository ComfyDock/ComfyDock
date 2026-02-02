"""Tests for ImportAnalyzer service."""
import tempfile
from pathlib import Path

import pytest
import tomlkit
from comfygit_core.services.import_analyzer import ImportAnalyzer


@pytest.fixture
def sample_pyproject():
    """Create a sample pyproject.toml structure."""
    return {
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
                    },
                    "ghi789": {
                        "filename": "model3.safetensors",
                        "relative_path": "checkpoints/model3.safetensors",
                        "sources": ["https://example.com/model3.safetensors"]
                    }
                },
                "nodes": {
                    "rgthree-comfy": {
                        "source": "registry"
                    },
                    "my-dev-node": {
                        "source": "development"
                    },
                    "custom-git-node": {
                        "source": "git",
                        "install_spec": "https://github.com/user/repo.git"
                    }
                },
                "workflows": {
                    "workflow1": {
                        "models": [
                            {"hash": "abc123", "criticality": "required"},
                            {"hash": "def456", "criticality": "optional"}
                        ]
                    },
                    "workflow2": {
                        "models": [
                            {"hash": "ghi789", "criticality": "required"}
                        ]
                    }
                }
            }
        }
    }


@pytest.fixture
def mock_model_repository():
    """Mock model repository."""
    class MockModelRepository:
        def __init__(self):
            self.available_models = {"ghi789"}  # Only model3 is available locally

        def get_model(self, hash):
            """Return model if it exists in available set."""
            if hash in self.available_models:
                return {"hash": hash}
            return None

    return MockModelRepository()


@pytest.fixture
def mock_node_mapping_repository():
    """Mock node mapping repository."""
    class MockNodeMappingRepository:
        pass

    return MockNodeMappingRepository()


def test_analyze_models(sample_pyproject, mock_model_repository, mock_node_mapping_repository):
    """Test model analysis."""
    # Create temp directory with pyproject.toml
    with tempfile.TemporaryDirectory() as temp_dir:
        cec_path = Path(temp_dir) / ".cec"
        cec_path.mkdir()

        pyproject_path = cec_path / "pyproject.toml"
        with open(pyproject_path, "w") as f:
            tomlkit.dump(sample_pyproject, f)

        # Analyze
        analyzer = ImportAnalyzer(mock_model_repository, mock_node_mapping_repository)
        analysis = analyzer.analyze_import(cec_path)

        # Verify model analysis
        assert analysis.total_models == 3
        assert analysis.models_locally_available == 1  # ghi789
        assert analysis.models_needing_download == 1  # abc123 (has source, not local)
        assert analysis.models_without_sources == 1  # def456 (no sources, not local)

        # Verify individual models
        model1 = next(m for m in analysis.models if m.hash == "abc123")
        assert model1.filename == "model1.safetensors"
        assert not model1.locally_available
        assert model1.needs_download
        assert len(model1.sources) == 1
        assert "workflow1" in model1.workflows

        model2 = next(m for m in analysis.models if m.hash == "def456")
        assert not model2.locally_available
        assert not model2.needs_download  # No sources
        assert len(model2.sources) == 0

        model3 = next(m for m in analysis.models if m.hash == "ghi789")
        assert model3.locally_available
        assert not model3.needs_download  # Already available
        assert "workflow2" in model3.workflows


def test_analyze_nodes(sample_pyproject, mock_model_repository, mock_node_mapping_repository):
    """Test node analysis."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cec_path = Path(temp_dir) / ".cec"
        cec_path.mkdir()

        pyproject_path = cec_path / "pyproject.toml"
        with open(pyproject_path, "w") as f:
            tomlkit.dump(sample_pyproject, f)

        analyzer = ImportAnalyzer(mock_model_repository, mock_node_mapping_repository)
        analysis = analyzer.analyze_import(cec_path)

        # Verify node counts
        assert analysis.total_nodes == 3
        assert analysis.registry_nodes == 1
        assert analysis.dev_nodes == 1
        assert analysis.git_nodes == 1

        # Verify individual nodes
        registry_node = next(n for n in analysis.nodes if n.name == "rgthree-comfy")
        assert registry_node.source == "registry"
        assert not registry_node.is_dev_node

        dev_node = next(n for n in analysis.nodes if n.name == "my-dev-node")
        assert dev_node.source == "development"
        assert dev_node.is_dev_node

        git_node = next(n for n in analysis.nodes if n.name == "custom-git-node")
        assert git_node.source == "git"
        assert git_node.install_spec == "https://github.com/user/repo.git"


def test_analyze_workflows(sample_pyproject, mock_model_repository, mock_node_mapping_repository):
    """Test workflow analysis."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cec_path = Path(temp_dir) / ".cec"
        cec_path.mkdir()

        pyproject_path = cec_path / "pyproject.toml"
        with open(pyproject_path, "w") as f:
            tomlkit.dump(sample_pyproject, f)

        analyzer = ImportAnalyzer(mock_model_repository, mock_node_mapping_repository)
        analysis = analyzer.analyze_import(cec_path)

        # Verify workflow counts
        assert analysis.total_workflows == 2

        # Verify individual workflows
        workflow1 = next(w for w in analysis.workflows if w.name == "workflow1")
        assert workflow1.models_required == 1
        assert workflow1.models_optional == 1

        workflow2 = next(w for w in analysis.workflows if w.name == "workflow2")
        assert workflow2.models_required == 1
        assert workflow2.models_optional == 0


def test_summary_flags(sample_pyproject, mock_model_repository, mock_node_mapping_repository):
    """Test summary flags."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cec_path = Path(temp_dir) / ".cec"
        cec_path.mkdir()

        pyproject_path = cec_path / "pyproject.toml"
        with open(pyproject_path, "w") as f:
            tomlkit.dump(sample_pyproject, f)

        analyzer = ImportAnalyzer(mock_model_repository, mock_node_mapping_repository)
        analysis = analyzer.analyze_import(cec_path)

        # Verify summary flags
        assert analysis.needs_model_downloads  # abc123 needs download
        assert analysis.needs_node_installs  # registry and git nodes need install
        assert analysis.comfyui_version == "v0.2.7"
        assert analysis.comfyui_version_type == "release"


def test_download_strategy_recommendation(mock_model_repository, mock_node_mapping_repository):
    """Test download strategy recommendation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cec_path = Path(temp_dir) / ".cec"
        cec_path.mkdir()

        # Test 1: All models available - recommend skip
        pyproject1 = {
            "tool": {
                "comfygit": {
                    "models": {
                        "ghi789": {
                            "filename": "model3.safetensors",
                            "relative_path": "checkpoints/model3.safetensors",
                            "sources": []
                        }
                    },
                    "nodes": {},
                    "workflows": {}
                }
            }
        }

        pyproject_path = cec_path / "pyproject.toml"
        with open(pyproject_path, "w") as f:
            tomlkit.dump(pyproject1, f)

        analyzer = ImportAnalyzer(mock_model_repository, mock_node_mapping_repository)
        analysis = analyzer.analyze_import(cec_path)
        assert analysis.get_download_strategy_recommendation() == "skip"

        # Test 2: Models without sources - recommend required
        pyproject2 = {
            "tool": {
                "comfygit": {
                    "models": {
                        "def456": {
                            "filename": "model2.safetensors",
                            "relative_path": "loras/model2.safetensors",
                            "sources": []
                        }
                    },
                    "nodes": {},
                    "workflows": {}
                }
            }
        }

        with open(pyproject_path, "w") as f:
            tomlkit.dump(pyproject2, f)

        analysis = analyzer.analyze_import(cec_path)
        # Model without sources and not available locally
        # Recommendation is "required" - user must manually provide the model
        assert analysis.models_without_sources == 1
        assert analysis.get_download_strategy_recommendation() == "required"

        # Test 3: Models with sources - recommend all
        pyproject3 = {
            "tool": {
                "comfygit": {
                    "models": {
                        "abc123": {
                            "filename": "model1.safetensors",
                            "relative_path": "checkpoints/model1.safetensors",
                            "sources": ["https://example.com/model1.safetensors"]
                        }
                    },
                    "nodes": {},
                    "workflows": {}
                }
            }
        }

        with open(pyproject_path, "w") as f:
            tomlkit.dump(pyproject3, f)

        analysis = analyzer.analyze_import(cec_path)
        assert analysis.get_download_strategy_recommendation() == "all"
