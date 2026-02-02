"""Unit tests for SemanticMerger.

Tests the intelligent pyproject.toml merging based on workflow resolutions.
"""


from comfygit_core.merging.semantic_merger import SemanticMerger


class TestSemanticMerger:
    """Test SemanticMerger functionality."""

    def test_model_sources_unioned(self):
        """Both branches have same model with different sources - should union."""
        base = {
            "tool": {
                "comfygit": {
                    "models": {
                        "abc123": {
                            "filename": "model.safetensors",
                            "sources": ["civitai://123"],
                        }
                    },
                    "workflows": {"wf1": {"models": ["abc123"]}},
                }
            }
        }
        target = {
            "tool": {
                "comfygit": {
                    "models": {
                        "abc123": {
                            "filename": "model.safetensors",
                            "sources": ["huggingface://model"],
                        }
                    },
                    "workflows": {"wf1": {"models": ["abc123"]}},
                }
            }
        }

        merger = SemanticMerger()
        result = merger.merge(
            base_config=base,
            target_config=target,
            workflow_resolutions={},
            merged_workflow_files=["wf1"],
        )

        sources = result["tool"]["comfygit"]["models"]["abc123"]["sources"]
        assert "civitai://123" in sources
        assert "huggingface://model" in sources

    def test_manual_dependency_groups_preserved(self):
        """User-added dependency groups should survive merge."""
        base = {
            "dependency-groups": {
                "comfy-mtb-9bb64296": ["dep1"],  # auto-generated (hash suffix)
                "my-test-deps": ["pytest"],  # manual (no hash)
            },
            "tool": {"comfygit": {"workflows": {}}},
        }
        target = {
            "dependency-groups": {
                "comfy-mtb-9bb64296": ["dep2"],  # different auto version
                "other-manual": ["black"],  # different manual
            },
            "tool": {"comfygit": {"workflows": {}}},
        }

        merger = SemanticMerger()
        result = merger.merge(
            base_config=base,
            target_config=target,
            workflow_resolutions={},
            merged_workflow_files=[],
        )

        # Auto groups NOT copied (regenerated later)
        assert "comfy-mtb-9bb64296" not in result.get("dependency-groups", {})
        # Manual groups from BOTH preserved
        assert "my-test-deps" in result["dependency-groups"]
        assert "other-manual" in result["dependency-groups"]

    def test_local_uv_config_preserved(self):
        """Platform-specific UV config should never merge from remote."""
        base = {
            "tool": {
                "uv": {
                    "constraint-dependencies": ["torch==2.5.1+cu129"],
                    "index": [{"name": "pytorch-cu129", "url": "https://..."}],
                },
                "comfygit": {
                    "torch_backend": "cu129",
                    "workflows": {},
                },
            }
        }
        target = {
            "tool": {
                "uv": {
                    "constraint-dependencies": ["torch==2.5.1+cpu"],
                    "index": [{"name": "pytorch-cpu", "url": "https://..."}],
                },
                "comfygit": {
                    "torch_backend": "cpu",
                    "workflows": {},
                },
            }
        }

        merger = SemanticMerger()
        result = merger.merge(
            base_config=base,
            target_config=target,
            workflow_resolutions={},
            merged_workflow_files=[],
        )

        # Base (local) UV config preserved
        assert result["tool"]["uv"]["constraint-dependencies"] == [
            "torch==2.5.1+cu129"
        ]
        assert result["tool"]["comfygit"]["torch_backend"] == "cu129"

    def test_workflow_resolution_take_base(self):
        """Workflow with take_base resolution keeps base version's config."""
        base = {
            "tool": {
                "comfygit": {
                    "workflows": {
                        "wf1": {"nodes": ["node-a"], "models": ["model-a"]}
                    },
                    "nodes": {"node-a": {"version": "1.0"}},
                    "models": {"model-a": {"filename": "a.safetensors"}},
                }
            }
        }
        target = {
            "tool": {
                "comfygit": {
                    "workflows": {
                        "wf1": {"nodes": ["node-b"], "models": ["model-b"]}
                    },
                    "nodes": {"node-b": {"version": "2.0"}},
                    "models": {"model-b": {"filename": "b.safetensors"}},
                }
            }
        }

        merger = SemanticMerger()
        result = merger.merge(
            base_config=base,
            target_config=target,
            workflow_resolutions={"wf1": "take_base"},
            merged_workflow_files=["wf1"],
        )

        # Should have base workflow config
        wf1 = result["tool"]["comfygit"]["workflows"]["wf1"]
        assert "node-a" in wf1["nodes"]
        assert "model-a" in wf1["models"]

    def test_workflow_resolution_take_target(self):
        """Workflow with take_target resolution uses target version's config."""
        base = {
            "tool": {
                "comfygit": {
                    "workflows": {
                        "wf1": {"nodes": ["node-a"], "models": ["model-a"]}
                    },
                    "nodes": {"node-a": {"version": "1.0"}},
                    "models": {"model-a": {"filename": "a.safetensors"}},
                }
            }
        }
        target = {
            "tool": {
                "comfygit": {
                    "workflows": {
                        "wf1": {"nodes": ["node-b"], "models": ["model-b"]}
                    },
                    "nodes": {"node-b": {"version": "2.0"}},
                    "models": {"model-b": {"filename": "b.safetensors"}},
                }
            }
        }

        merger = SemanticMerger()
        result = merger.merge(
            base_config=base,
            target_config=target,
            workflow_resolutions={"wf1": "take_target"},
            merged_workflow_files=["wf1"],
        )

        # Should have target workflow config
        wf1 = result["tool"]["comfygit"]["workflows"]["wf1"]
        assert "node-b" in wf1["nodes"]
        assert "model-b" in wf1["models"]

    def test_mixed_workflow_resolutions(self):
        """Mixed resolutions correctly combine nodes from both branches."""
        base = {
            "tool": {
                "comfygit": {
                    "workflows": {
                        "wf1": {"nodes": ["node-a"]},
                        "wf2": {"nodes": ["node-c"]},
                    },
                    "nodes": {
                        "node-a": {"version": "1.0"},
                        "node-c": {"version": "1.0"},
                    },
                }
            }
        }
        target = {
            "tool": {
                "comfygit": {
                    "workflows": {
                        "wf1": {"nodes": ["node-b"]},
                        "wf2": {"nodes": ["node-d"]},
                    },
                    "nodes": {
                        "node-b": {"version": "2.0"},
                        "node-d": {"version": "2.0"},
                    },
                }
            }
        }

        merger = SemanticMerger()
        result = merger.merge(
            base_config=base,
            target_config=target,
            workflow_resolutions={"wf1": "take_base", "wf2": "take_target"},
            merged_workflow_files=["wf1", "wf2"],
        )

        nodes = result["tool"]["comfygit"]["nodes"]
        # wf1 (take_base) needs node-a
        assert "node-a" in nodes
        # wf2 (take_target) needs node-d
        assert "node-d" in nodes

    def test_new_workflow_from_target_added(self):
        """New workflow from target branch gets added with its deps."""
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
                    "workflows": {
                        "wf1": {"nodes": ["node-a"]},
                        "wf2": {"nodes": ["node-b"]},  # new workflow
                    },
                    "nodes": {
                        "node-a": {"version": "1.0"},
                        "node-b": {"version": "2.0"},
                    },
                }
            }
        }

        merger = SemanticMerger()
        result = merger.merge(
            base_config=base,
            target_config=target,
            workflow_resolutions={},
            merged_workflow_files=["wf1", "wf2"],
        )

        # Both workflows should exist
        assert "wf1" in result["tool"]["comfygit"]["workflows"]
        assert "wf2" in result["tool"]["comfygit"]["workflows"]
        # Both nodes should be included
        assert "node-a" in result["tool"]["comfygit"]["nodes"]
        assert "node-b" in result["tool"]["comfygit"]["nodes"]

    def test_target_only_workflow_uses_target_node_entry(self):
        """Node from target-only workflow should use target's node entry, not base."""
        base = {
            "tool": {
                "comfygit": {
                    "workflows": {"wf1": {"nodes": ["node-a"]}},
                    "nodes": {
                        "node-a": {"version": "1.0", "source": "base-source"},
                        "shared-node": {"version": "1.0", "source": "base-source"},
                    },
                }
            }
        }
        target = {
            "tool": {
                "comfygit": {
                    "workflows": {
                        # wf2 only exists in target, references shared-node
                        "wf2": {"nodes": ["shared-node"]},
                    },
                    "nodes": {
                        "shared-node": {"version": "2.0", "source": "target-source"},
                    },
                }
            }
        }

        merger = SemanticMerger()
        result = merger.merge(
            base_config=base,
            target_config=target,
            workflow_resolutions={},
            merged_workflow_files=["wf1", "wf2"],
        )

        nodes = result["tool"]["comfygit"]["nodes"]
        # wf2 came from target (not in base), so shared-node should use target entry
        assert nodes["shared-node"]["version"] == "2.0"
        assert nodes["shared-node"]["source"] == "target-source"

    def test_mixed_source_node_prefers_target(self):
        """Node used by both base and target workflows should prefer target entry."""
        base = {
            "tool": {
                "comfygit": {
                    "workflows": {
                        "wf1": {"nodes": ["shared-node"]},
                    },
                    "nodes": {
                        "shared-node": {"version": "1.0", "source": "base-source"},
                    },
                }
            }
        }
        target = {
            "tool": {
                "comfygit": {
                    "workflows": {
                        "wf2": {"nodes": ["shared-node"]},
                    },
                    "nodes": {
                        "shared-node": {"version": "2.0", "source": "target-source"},
                    },
                }
            }
        }

        merger = SemanticMerger()
        result = merger.merge(
            base_config=base,
            target_config=target,
            workflow_resolutions={"wf1": "take_base", "wf2": "take_target"},
            merged_workflow_files=["wf1", "wf2"],
        )

        nodes = result["tool"]["comfygit"]["nodes"]
        # Node used by both, but wf2 is take_target, so target entry should win
        assert nodes["shared-node"]["version"] == "2.0"
        assert nodes["shared-node"]["source"] == "target-source"
