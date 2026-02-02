"""Unit tests for workflow hash utility.

Tests content-based hashing and normalization:
- Hash computation is deterministic
- Normalization removes volatile fields
- UI changes don't affect hash
- Semantic changes affect hash
- Hash stability across saves
"""
import copy
import json

import pytest
from comfygit_core.utils.workflow_hash import compute_workflow_hash, normalize_workflow


@pytest.fixture
def sample_workflow():
    """Create sample workflow data."""
    return {
        "nodes": [
            {
                "id": 1,
                "type": "CheckpointLoaderSimple",
                "pos": [100, 200],
                "widgets_values": ["model.safetensors"]
            },
            {
                "id": 2,
                "type": "KSampler",
                "pos": [300, 200],
                "widgets_values": [123, "fixed", 20, 8.0, "euler", "normal", 1.0]
            }
        ],
        "links": [[1, 0, 2, 0, "MODEL"]],
        "extra": {
            "ds": {"scale": 1.0, "offset": [0, 0]},
            "frontendVersion": "1.2.3"
        },
        "version": 0.4
    }


@pytest.fixture
def workflow_file(tmp_path, sample_workflow):
    """Create a workflow JSON file."""
    workflow_path = tmp_path / "test_workflow.json"
    with open(workflow_path, 'w') as f:
        json.dump(sample_workflow, f, indent=2)
    return workflow_path


class TestHashDeterminism:
    """Test that hash computation is deterministic."""

    def test_hash_is_deterministic_and_identical_workflows_match(self, workflow_file, tmp_path, sample_workflow):
        """Computing hash multiple times and across files should return same value."""
        # Same file, multiple computations
        hash1 = compute_workflow_hash(workflow_file)
        hash2 = compute_workflow_hash(workflow_file)

        assert hash1 == hash2
        assert isinstance(hash1, str)
        assert len(hash1) == 16  # 64-bit hash in hex

        # Different files, identical content
        file1 = tmp_path / "workflow1.json"
        file2 = tmp_path / "workflow2.json"

        with open(file1, 'w') as f:
            json.dump(sample_workflow, f)
        with open(file2, 'w') as f:
            json.dump(sample_workflow, f)

        hash3 = compute_workflow_hash(file1)
        hash4 = compute_workflow_hash(file2)

        assert hash3 == hash4


class TestNormalizationRemovesVolatileFields:
    """Test that normalization removes volatile fields."""

    def test_normalization_removes_volatile_fields(self, sample_workflow):
        """Normalization should remove UI state, frontendVersion, and revision."""
        workflow = copy.deepcopy(sample_workflow)
        workflow["revision"] = 42

        normalized = normalize_workflow(workflow)

        # extra.ds (UI state) should be removed
        if "extra" in normalized:
            assert "ds" not in normalized["extra"]
            assert "frontendVersion" not in normalized["extra"]

        # revision counter should be removed
        assert "revision" not in normalized


class TestUIChangesDoNotAffectHash:
    """Test that UI-only changes don't change the hash."""

    def test_ui_and_metadata_changes_produce_same_hash(self, tmp_path, sample_workflow):
        """Changing pan/zoom, frontend version, and revision should not affect hash."""
        file1 = tmp_path / "workflow1.json"
        file2 = tmp_path / "workflow2.json"

        # Write first workflow with initial values
        workflow1 = copy.deepcopy(sample_workflow)
        workflow1["revision"] = 1
        with open(file1, 'w') as f:
            json.dump(workflow1, f)

        # Modify all volatile fields
        workflow2 = copy.deepcopy(sample_workflow)
        workflow2["extra"]["ds"]["scale"] = 2.0
        workflow2["extra"]["ds"]["offset"] = [100, 200]
        workflow2["extra"]["frontendVersion"] = "9.9.9"
        workflow2["revision"] = 999

        with open(file2, 'w') as f:
            json.dump(workflow2, f)

        hash1 = compute_workflow_hash(file1)
        hash2 = compute_workflow_hash(file2)

        assert hash1 == hash2


class TestSemanticChangesCauseHashChange:
    """Test that semantic changes produce different hashes."""

    def test_structural_changes_produce_different_hashes(self, tmp_path, sample_workflow):
        """Adding nodes and changing node types should produce different hashes."""
        file1 = tmp_path / "workflow1.json"
        file2 = tmp_path / "workflow2.json"
        file3 = tmp_path / "workflow3.json"

        # Original workflow
        with open(file1, 'w') as f:
            json.dump(sample_workflow, f)

        # Add node
        workflow2 = copy.deepcopy(sample_workflow)
        workflow2["nodes"].append({
            "id": 3,
            "type": "SaveImage",
            "widgets_values": []
        })
        with open(file2, 'w') as f:
            json.dump(workflow2, f)

        # Change node type
        workflow3 = copy.deepcopy(sample_workflow)
        workflow3["nodes"][0]["type"] = "CheckpointLoaderAdvanced"
        with open(file3, 'w') as f:
            json.dump(workflow3, f)

        hash1 = compute_workflow_hash(file1)
        hash2 = compute_workflow_hash(file2)
        hash3 = compute_workflow_hash(file3)

        # All should be different
        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3

    def test_widget_and_link_changes_produce_different_hashes(self, tmp_path, sample_workflow):
        """Changing widget values and connections should produce different hashes."""
        file1 = tmp_path / "workflow1.json"
        file2 = tmp_path / "workflow2.json"

        with open(file1, 'w') as f:
            json.dump(sample_workflow, f)

        # Change widget value and link
        workflow2 = copy.deepcopy(sample_workflow)
        workflow2["nodes"][0]["widgets_values"][0] = "different_model.safetensors"
        workflow2["links"][0][4] = "CLIP"  # Change link type

        with open(file2, 'w') as f:
            json.dump(workflow2, f)

        hash1 = compute_workflow_hash(file1)
        hash2 = compute_workflow_hash(file2)

        assert hash1 != hash2


class TestSeedNormalization:
    """Test that randomize seed mode normalization works."""

    def test_randomize_seed_normalized_to_zero(self, tmp_path):
        """When control_after_generate is randomize/increment, seed should be normalized."""
        workflow1 = {
            "nodes": [{
                "id": 1,
                "type": "KSampler",
                "widgets_values": [12345, "randomize", 20, 8.0]
            }]
        }

        workflow2 = {
            "nodes": [{
                "id": 1,
                "type": "KSampler",
                "widgets_values": [67890, "randomize", 20, 8.0]
            }]
        }

        file1 = tmp_path / "workflow1.json"
        file2 = tmp_path / "workflow2.json"

        with open(file1, 'w') as f:
            json.dump(workflow1, f)

        with open(file2, 'w') as f:
            json.dump(workflow2, f)

        hash1 = compute_workflow_hash(file1)
        hash2 = compute_workflow_hash(file2)

        # Different random seeds should produce same hash (normalized)
        assert hash1 == hash2

    def test_fixed_seed_not_normalized(self, tmp_path):
        """When control_after_generate is fixed, different seeds should produce different hash."""
        workflow1 = {
            "nodes": [{
                "id": 1,
                "type": "KSampler",
                "widgets_values": [12345, "fixed", 20, 8.0]
            }]
        }

        workflow2 = {
            "nodes": [{
                "id": 1,
                "type": "KSampler",
                "widgets_values": [67890, "fixed", 20, 8.0]
            }]
        }

        file1 = tmp_path / "workflow1.json"
        file2 = tmp_path / "workflow2.json"

        with open(file1, 'w') as f:
            json.dump(workflow1, f)

        with open(file2, 'w') as f:
            json.dump(workflow2, f)

        hash1 = compute_workflow_hash(file1)
        hash2 = compute_workflow_hash(file2)

        # Fixed seeds should produce different hash (not normalized)
        assert hash1 != hash2


class TestHashStability:
    """Test that hashes are stable across saves and formatting changes."""

    def test_hash_stable_after_save_load_and_formatting_changes(self, tmp_path, sample_workflow):
        """Hash should be stable after save/load and with different JSON formatting."""
        workflow_path = tmp_path / "workflow.json"
        file1 = tmp_path / "workflow1.json"
        file2 = tmp_path / "workflow2.json"

        # Save workflow
        with open(workflow_path, 'w') as f:
            json.dump(sample_workflow, f)

        hash1 = compute_workflow_hash(workflow_path)

        # Load and re-save (simulating ComfyUI round-trip)
        with open(workflow_path) as f:
            loaded = json.load(f)
        with open(workflow_path, 'w') as f:
            json.dump(loaded, f)

        hash2 = compute_workflow_hash(workflow_path)

        # Test different formatting
        with open(file1, 'w') as f:
            json.dump(sample_workflow, f, indent=2)
        with open(file2, 'w') as f:
            json.dump(sample_workflow, f, indent=None)  # Compact

        hash3 = compute_workflow_hash(file1)
        hash4 = compute_workflow_hash(file2)

        # All should be same
        assert hash1 == hash2 == hash3 == hash4


class TestNormalizationEdgeCases:
    """Test normalization handles edge cases correctly."""

    def test_edge_case_workflows_hash_consistently(self, tmp_path):
        """Empty workflows, missing fields, and null values should hash consistently."""
        # Empty workflow
        empty_wf = {"nodes": [], "links": []}
        empty_path = tmp_path / "empty.json"
        with open(empty_path, 'w') as f:
            json.dump(empty_wf, f)

        hash_empty1 = compute_workflow_hash(empty_path)
        hash_empty2 = compute_workflow_hash(empty_path)
        assert hash_empty1 == hash_empty2

        # Workflow without extra field
        no_extra_wf = {"nodes": [{"id": 1, "type": "TestNode"}]}
        no_extra_path = tmp_path / "no_extra.json"
        with open(no_extra_path, 'w') as f:
            json.dump(no_extra_wf, f)

        hash_no_extra = compute_workflow_hash(no_extra_path)
        assert isinstance(hash_no_extra, str)
        assert len(hash_no_extra) == 16

        # Workflow with null values
        null_wf = {
            "nodes": [{
                "id": 1,
                "type": "TestNode",
                "widgets_values": [None, "value", None]
            }]
        }
        null_path = tmp_path / "with_nulls.json"
        with open(null_path, 'w') as f:
            json.dump(null_wf, f)

        hash_null1 = compute_workflow_hash(null_path)
        hash_null2 = compute_workflow_hash(null_path)
        assert hash_null1 == hash_null2


class TestKeyOrdering:
    """Test that key ordering doesn't affect hash."""

    def test_different_key_order_same_hash(self, tmp_path):
        """Different JSON key ordering should produce same hash."""
        workflow1 = {
            "nodes": [{"id": 1, "type": "Test", "pos": [0, 0]}],
            "links": [],
            "version": 0.4
        }

        workflow2 = {
            "version": 0.4,
            "links": [],
            "nodes": [{"pos": [0, 0], "type": "Test", "id": 1}]
        }

        file1 = tmp_path / "workflow1.json"
        file2 = tmp_path / "workflow2.json"

        with open(file1, 'w') as f:
            json.dump(workflow1, f)

        with open(file2, 'w') as f:
            json.dump(workflow2, f)

        hash1 = compute_workflow_hash(file1)
        hash2 = compute_workflow_hash(file2)

        # Normalization should sort keys for determinism
        assert hash1 == hash2
