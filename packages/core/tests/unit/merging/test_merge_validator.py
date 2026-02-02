"""Unit tests for MergeValidator.

Tests pre-merge validation for node version conflicts.
"""


from comfygit_core.merging.merge_validator import MergeValidator


class TestMergeValidator:
    """Test MergeValidator functionality."""

    def test_no_conflicts_when_compatible(self):
        """Validation passes when all workflows use compatible node versions."""
        base = {
            "tool": {
                "comfygit": {
                    "workflows": {"wf1": {"nodes": ["node-a"]}},
                    "nodes": {"node-a": {"version": "1.0"}},
                }
            }
        }
        target = {
            "tool": {
                "comfygit": {
                    "workflows": {"wf2": {"nodes": ["node-b"]}},
                    "nodes": {"node-b": {"version": "2.0"}},
                }
            }
        }

        validator = MergeValidator()
        result = validator.validate(base, target, {})

        assert result.is_compatible
        assert len(result.conflicts) == 0
        assert "wf1" in result.merged_workflow_set
        assert "wf2" in result.merged_workflow_set

    def test_detects_version_conflict(self):
        """Detects conflict when same node required at different versions."""
        base = {
            "tool": {
                "comfygit": {
                    "workflows": {"wf1": {"nodes": ["impact-pack"]}},
                    "nodes": {"impact-pack": {"version": "3.5"}},
                }
            }
        }
        target = {
            "tool": {
                "comfygit": {
                    "workflows": {"wf2": {"nodes": ["impact-pack"]}},
                    "nodes": {"impact-pack": {"version": "4.0"}},
                }
            }
        }

        validator = MergeValidator()
        result = validator.validate(base, target, {})

        assert not result.is_compatible
        assert len(result.conflicts) == 1
        assert result.conflicts[0].node_id == "impact-pack"
        assert result.conflicts[0].base_version == "3.5"
        assert result.conflicts[0].target_version == "4.0"

    def test_resolution_affects_version_check(self):
        """Workflow resolution determines which node version is used."""
        base = {
            "tool": {
                "comfygit": {
                    "workflows": {"wf1": {"nodes": ["node-a"]}},
                    "nodes": {"node-a": {"version": "1.0"}},
                }
            }
        }
        target = {
            "tool": {
                "comfygit": {
                    "workflows": {"wf1": {"nodes": ["node-a"]}},
                    "nodes": {"node-a": {"version": "2.0"}},
                }
            }
        }

        validator = MergeValidator()

        # With take_target, only target version is used - no conflict
        result = validator.validate(base, target, {"wf1": "take_target"})
        assert result.is_compatible

        # With take_base, only base version is used - no conflict
        result = validator.validate(base, target, {"wf1": "take_base"})
        assert result.is_compatible

    def test_mixed_resolutions_can_cause_conflict(self):
        """Mixed resolutions can create conflicts across workflows."""
        base = {
            "tool": {
                "comfygit": {
                    "workflows": {
                        "wf1": {"nodes": ["shared-node"]},
                        "wf2": {"nodes": ["shared-node"]},
                    },
                    "nodes": {"shared-node": {"version": "1.0"}},
                }
            }
        }
        target = {
            "tool": {
                "comfygit": {
                    "workflows": {
                        "wf1": {"nodes": ["shared-node"]},
                        "wf2": {"nodes": ["shared-node"]},
                    },
                    "nodes": {"shared-node": {"version": "2.0"}},
                }
            }
        }

        validator = MergeValidator()
        # wf1 uses base version (1.0), wf2 uses target version (2.0)
        result = validator.validate(
            base, target, {"wf1": "take_base", "wf2": "take_target"}
        )

        assert not result.is_compatible
        assert len(result.conflicts) == 1
        assert result.conflicts[0].node_id == "shared-node"

    def test_computes_merged_workflow_set(self):
        """Correctly computes final workflow set from both branches."""
        base = {
            "tool": {
                "comfygit": {
                    "workflows": {"wf1": {}, "wf2": {}},
                }
            }
        }
        target = {
            "tool": {
                "comfygit": {
                    "workflows": {"wf2": {}, "wf3": {}},
                }
            }
        }

        validator = MergeValidator()
        result = validator.validate(base, target, {})

        # Should include all workflows from both branches
        assert set(result.merged_workflow_set) == {"wf1", "wf2", "wf3"}
