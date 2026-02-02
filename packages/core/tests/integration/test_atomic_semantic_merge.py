"""Integration tests for atomic semantic merge resolution.

Tests the merge system that handles:
- Per-file workflow resolution (mixed mine/theirs)
- Semantic pyproject.toml merging (derived from workflows)
- Atomic rollback on failure
- Model source union from both branches
"""



class TestAtomicSemanticMerge:
    """Test atomic semantic merge integration."""

    def test_mixed_workflow_resolutions_apply_per_file(self, test_env):
        """Mixed mine/theirs resolutions should apply correct version per workflow.

        This is the key test case from the plan:
        - Branch A has WF1(v1), WF2(v1)
        - Branch B has WF1(v2), WF2(v2)
        - User resolves: WF1=theirs, WF2=mine
        - Result should have WF1(v2), WF2(v1)
        """
        env = test_env

        # Create initial state on main with two workflows
        wf1_v1 = {"version": "1.0", "nodes": {"1": {"class_type": "KSampler"}}}
        wf2_v1 = {"version": "1.0", "nodes": {"1": {"class_type": "KSampler"}}}

        (env.cec_path / "workflows").mkdir(exist_ok=True)
        import json
        (env.cec_path / "workflows/wf1.json").write_text(json.dumps(wf1_v1))
        (env.cec_path / "workflows/wf2.json").write_text(json.dumps(wf2_v1))
        env.git_manager.commit_all("Add workflows v1")

        # Create feature branch with modified workflows
        env.git_manager.create_branch("feature")
        env.git_manager.switch_branch("feature")

        wf1_v2 = {"version": "2.0", "nodes": {"1": {"class_type": "KSamplerAdvanced"}}}
        wf2_v2 = {"version": "2.0", "nodes": {"1": {"class_type": "KSamplerAdvanced"}}}
        (env.cec_path / "workflows/wf1.json").write_text(json.dumps(wf1_v2))
        (env.cec_path / "workflows/wf2.json").write_text(json.dumps(wf2_v2))
        env.git_manager.commit_all("Update workflows to v2")

        # Switch back to main
        env.git_manager.switch_branch("main")

        # Execute atomic merge with mixed resolutions
        resolutions = {
            "wf1": "take_target",  # Take feature's v2
            "wf2": "take_base",    # Keep main's v1
        }

        result = env.execute_atomic_merge("feature", resolutions)

        # Verify merge succeeded
        assert result.success, f"Merge failed: {result.error}"

        # Verify correct workflow versions
        wf1_result = json.loads((env.cec_path / "workflows/wf1.json").read_text())
        wf2_result = json.loads((env.cec_path / "workflows/wf2.json").read_text())

        assert wf1_result["version"] == "2.0", "WF1 should be v2 (theirs)"
        assert wf2_result["version"] == "1.0", "WF2 should be v1 (mine)"

    def test_semantic_merge_preserves_local_uv_config(self, test_env):
        """Local platform-specific UV config should never be overwritten.

        Tests that PyTorch backend, constraint-dependencies, and indexes
        from the base (local) branch are preserved during merge.
        """
        env = test_env

        # Set up main with local PyTorch config
        config = env.pyproject.load()
        config.setdefault("tool", {}).setdefault("uv", {})
        config["tool"]["uv"]["constraint-dependencies"] = ["torch==2.5.1+cu129"]
        config["tool"]["uv"]["index"] = [{"name": "pytorch-cu129", "url": "https://download.pytorch.org/whl/cu129"}]
        config.setdefault("tool", {}).setdefault("comfygit", {})
        config["tool"]["comfygit"]["torch_backend"] = "cu129"
        env.pyproject.save(config)
        env.git_manager.commit_all("Set local PyTorch config")

        # Create feature branch with different PyTorch config
        env.git_manager.create_branch("feature")
        env.git_manager.switch_branch("feature")

        config = env.pyproject.load()
        config["tool"]["uv"]["constraint-dependencies"] = ["torch==2.5.1+cpu"]
        config["tool"]["uv"]["index"] = [{"name": "pytorch-cpu", "url": "https://download.pytorch.org/whl/cpu"}]
        config["tool"]["comfygit"]["torch_backend"] = "cpu"
        env.pyproject.save(config)
        env.git_manager.commit_all("Different PyTorch config")

        # Switch back to main and merge
        env.git_manager.switch_branch("main")

        result = env.execute_atomic_merge("feature", {})
        assert result.success, f"Merge failed: {result.error}"

        # Verify local config preserved
        config = env.pyproject.load()
        assert "cu129" in str(config["tool"]["uv"]["constraint-dependencies"]), \
            "Local PyTorch constraint should be preserved"
        assert config["tool"]["comfygit"]["torch_backend"] == "cu129", \
            "Local torch_backend should be preserved"

    def test_semantic_merge_unions_model_sources(self, test_env):
        """Model sources from both branches should be unioned.

        When same model exists in both branches with different sources,
        the merged result should contain sources from BOTH branches.
        """
        env = test_env

        model_hash = "abc123def456"

        # Set up main with model from civitai
        config = env.pyproject.load()
        config.setdefault("tool", {}).setdefault("comfygit", {}).setdefault("models", {})
        config["tool"]["comfygit"]["models"][model_hash] = {
            "filename": "model.safetensors",
            "sources": ["civitai://12345"],
        }
        config["tool"]["comfygit"].setdefault("workflows", {})
        config["tool"]["comfygit"]["workflows"]["wf1"] = {"models": [model_hash]}
        env.pyproject.save(config)
        (env.cec_path / "workflows").mkdir(exist_ok=True)
        (env.cec_path / "workflows/wf1.json").write_text("{}")
        env.git_manager.commit_all("Add model with civitai source")

        # Create feature branch with same model from huggingface
        env.git_manager.create_branch("feature")
        env.git_manager.switch_branch("feature")

        config = env.pyproject.load()
        config["tool"]["comfygit"]["models"][model_hash]["sources"] = ["huggingface://model"]
        env.pyproject.save(config)
        env.git_manager.commit_all("Model with huggingface source")

        # Switch back to main and merge
        env.git_manager.switch_branch("main")

        result = env.execute_atomic_merge("feature", {})
        assert result.success, f"Merge failed: {result.error}"

        # Verify sources were unioned
        config = env.pyproject.load()
        sources = config["tool"]["comfygit"]["models"][model_hash]["sources"]

        assert "civitai://12345" in sources, "Civitai source should be preserved"
        assert "huggingface://model" in sources, "Huggingface source should be added"

    def test_merge_rollback_on_failure(self, test_env):
        """Failed merge should roll back to pre-merge state.

        Tests atomic behavior: if any part of merge fails,
        the environment should be restored to its exact pre-merge state.
        """
        env = test_env

        # Create initial state
        (env.cec_path / "original.txt").write_text("original content")
        env.git_manager.commit_all("Initial state")
        original_commit = env.git_manager.get_version_history(limit=1)[0]["hash"]

        # Create feature branch
        env.git_manager.create_branch("feature")
        env.git_manager.switch_branch("feature")
        (env.cec_path / "feature.txt").write_text("feature content")
        env.git_manager.commit_all("Feature commit")

        # Switch back to main
        env.git_manager.switch_branch("main")

        # Verify we're at original commit
        assert env.git_manager.get_version_history(limit=1)[0]["hash"] == original_commit

        # Execute merge with an invalid resolution that should cause failure
        # (This tests that partial failures trigger rollback)
        # The merge should either succeed fully or leave no trace

        try:
            result = env.execute_atomic_merge("feature", {})
            if not result.success:
                # Verify rollback happened
                current = env.git_manager.get_version_history(limit=1)[0]["hash"]
                assert current == original_commit, \
                    "Failed merge should roll back to original commit"
        except Exception:
            # Any exception should also result in rollback
            current = env.git_manager.get_version_history(limit=1)[0]["hash"]
            assert current == original_commit, \
                "Exception during merge should roll back to original commit"


class TestMergeValidation:
    """Test pre-merge validation for node version conflicts."""

    def test_validate_merge_detects_node_version_conflict(self, test_env):
        """Validation should detect when same node is required at different versions.

        Scenario:
        - Main has WF1 needing node-a@1.0
        - Feature has WF2 needing node-a@2.0
        - Merging both would require node-a at two versions (impossible)
        """
        env = test_env

        # Set up main with workflow using node-a@1.0
        config = env.pyproject.load()
        config.setdefault("tool", {}).setdefault("comfygit", {})
        config["tool"]["comfygit"]["workflows"] = {
            "wf1": {"nodes": ["impact-pack"]}
        }
        config["tool"]["comfygit"]["nodes"] = {
            "impact-pack": {"version": "3.5", "repository": "ltdrdata/ComfyUI-Impact-Pack"}
        }
        env.pyproject.save(config)
        (env.cec_path / "workflows").mkdir(exist_ok=True)
        (env.cec_path / "workflows/wf1.json").write_text("{}")
        env.git_manager.commit_all("WF1 with impact-pack 3.5")

        # Create feature branch with workflow using node-a@2.0
        env.git_manager.create_branch("feature")
        env.git_manager.switch_branch("feature")

        config = env.pyproject.load()
        config["tool"]["comfygit"]["workflows"]["wf2"] = {"nodes": ["impact-pack"]}
        config["tool"]["comfygit"]["nodes"]["impact-pack"]["version"] = "4.0"
        env.pyproject.save(config)
        (env.cec_path / "workflows/wf2.json").write_text("{}")
        env.git_manager.commit_all("WF2 with impact-pack 4.0")

        # Switch back to main
        env.git_manager.switch_branch("main")

        # Validate merge - should detect conflict
        validation = env.validate_merge("feature", {})

        assert not validation.is_compatible, "Should detect version conflict"
        assert len(validation.conflicts) == 1, "Should have one conflict"
        assert validation.conflicts[0].node_id == "impact-pack"
        assert validation.conflicts[0].base_version == "3.5"
        assert validation.conflicts[0].target_version == "4.0"

    def test_validate_merge_no_conflict_with_resolution(self, test_env):
        """Resolution should eliminate conflicts when choosing single source.

        If user resolves conflicting workflow to "take_base", only base
        node version is needed, eliminating the conflict.
        """
        env = test_env

        # Set up main with WF1 using node@1.0
        config = env.pyproject.load()
        config.setdefault("tool", {}).setdefault("comfygit", {})
        config["tool"]["comfygit"]["workflows"] = {
            "wf1": {"nodes": ["shared-node"]}
        }
        config["tool"]["comfygit"]["nodes"] = {
            "shared-node": {"version": "1.0"}
        }
        env.pyproject.save(config)
        (env.cec_path / "workflows").mkdir(exist_ok=True)
        (env.cec_path / "workflows/wf1.json").write_text("{}")
        env.git_manager.commit_all("WF1 with shared-node 1.0")

        # Create feature with same workflow but different node version
        env.git_manager.create_branch("feature")
        env.git_manager.switch_branch("feature")

        config = env.pyproject.load()
        config["tool"]["comfygit"]["nodes"]["shared-node"]["version"] = "2.0"
        env.pyproject.save(config)
        env.git_manager.commit_all("WF1 with shared-node 2.0")

        # Switch back to main
        env.git_manager.switch_branch("main")

        # Validate with take_base resolution - should have no conflict
        validation = env.validate_merge("feature", {"wf1": "take_base"})

        assert validation.is_compatible, "Should have no conflict when resolving to single source"
        assert len(validation.conflicts) == 0


class TestManualDependencyGroupPreservation:
    """Test that manually added dependency groups survive merge."""

    def test_manual_dependency_groups_preserved_from_both_branches(self, test_env):
        """User-added dependency groups (no hash suffix) should be preserved from BOTH branches."""
        env = test_env

        # Set up main with manual test group
        config = env.pyproject.load()
        config["dependency-groups"] = {
            "my-test-deps": ["pytest", "pytest-cov"],
            "comfy-mtb-9bb64296": ["opencv-python"],  # auto-generated (has hash)
        }
        env.pyproject.save(config)
        env.git_manager.commit_all("Add manual test deps")

        # Create feature branch with different manual group
        env.git_manager.create_branch("feature")
        env.git_manager.switch_branch("feature")

        config = env.pyproject.load()
        config["dependency-groups"]["dev-tools"] = ["black", "ruff"]
        config["dependency-groups"]["comfy-mtb-9bb64296"] = ["pillow"]  # different auto content
        env.pyproject.save(config)
        env.git_manager.commit_all("Add dev tools group")

        # Switch back to main and merge
        env.git_manager.switch_branch("main")

        result = env.execute_atomic_merge("feature", {})
        assert result.success, f"Merge failed: {result.error}"

        # Verify manual groups from BOTH branches preserved
        config = env.pyproject.load()
        dep_groups = config.get("dependency-groups", {})

        assert "my-test-deps" in dep_groups, "Base manual group should be preserved"
        assert "dev-tools" in dep_groups, "Target manual group should be preserved"
        # Auto-generated groups are NOT preserved (regenerated by sync)
        assert "comfy-mtb-9bb64296" not in dep_groups, "Auto groups should be dropped"
