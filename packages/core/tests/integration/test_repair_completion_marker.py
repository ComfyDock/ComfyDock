"""Integration tests for repair command completion marker management.

Tests the scenario where an environment loses its .complete marker
(e.g., from manual git pull) and repair should restore it.
"""


from comfygit_core.utils.environment_cleanup import (
    COMPLETION_MARKER,
    is_environment_complete,
)


class TestRepairCompletionMarker:
    """Test repair command manages .complete marker correctly."""

    def test_repair_adds_completion_marker(self, test_env):
        """Repair should add .complete marker if missing.

        Scenario:
        1. Environment exists but .complete marker is missing (e.g., manual git pull)
        2. Environment won't show up in list_environments()
        3. Running repair should add .complete marker
        4. Environment should then be visible
        """
        # ARRANGE: Remove completion marker (simulate manual git pull scenario)
        marker_file = test_env.cec_path / COMPLETION_MARKER
        if marker_file.exists():
            marker_file.unlink()

        # Verify marker is missing
        assert not is_environment_complete(test_env.cec_path), (
            "Completion marker should not exist before repair"
        )

        # Verify environment would be hidden from list
        # (test_env fixture doesn't call list_environments, but this verifies the check)
        assert not is_environment_complete(test_env.cec_path)

        # ACT: Run repair (sync)
        sync_result = test_env.sync()

        # ASSERT: Completion marker should be created
        assert sync_result.success, "Sync should succeed"
        assert is_environment_complete(test_env.cec_path), (
            "Repair should create .complete marker, making environment visible to list_environments()"
        )
        assert marker_file.exists(), "Marker file should exist"

    def test_repair_preserves_existing_completion_marker(self, test_env):
        """Repair should not break if .complete marker already exists."""
        # ARRANGE: Ensure marker exists
        marker_file = test_env.cec_path / COMPLETION_MARKER
        marker_file.touch()
        assert is_environment_complete(test_env.cec_path)

        # ACT: Run repair
        sync_result = test_env.sync()

        # ASSERT: Marker should still exist
        assert sync_result.success
        assert is_environment_complete(test_env.cec_path)
        assert marker_file.exists()

    def test_dry_run_does_not_create_completion_marker(self, test_env):
        """Dry run should not create .complete marker."""
        # ARRANGE: Remove marker
        marker_file = test_env.cec_path / COMPLETION_MARKER
        if marker_file.exists():
            marker_file.unlink()
        assert not is_environment_complete(test_env.cec_path)

        # ACT: Run sync in dry run mode
        sync_result = test_env.sync(dry_run=True)

        # ASSERT: Marker should NOT be created in dry run
        assert sync_result.success
        assert not is_environment_complete(test_env.cec_path), (
            "Dry run should not create completion marker"
        )
        assert not marker_file.exists()

    def test_failed_sync_does_not_create_completion_marker(self, test_env):
        """Failed sync should not create .complete marker."""
        # ARRANGE: Remove marker and corrupt pyproject to force sync failure
        marker_file = test_env.cec_path / COMPLETION_MARKER
        if marker_file.exists():
            marker_file.unlink()

        # Corrupt pyproject.toml to cause sync failure
        config = test_env.pyproject.load()
        config["project"]["dependencies"] = ["nonexistent-package-that-will-fail==999.999.999"]
        test_env.pyproject.save(config)

        # ACT: Run sync (should fail)
        sync_result = test_env.sync()

        # ASSERT: Sync should fail and marker should NOT be created
        assert not sync_result.success, "Sync should fail with invalid dependency"
        assert not is_environment_complete(test_env.cec_path), (
            "Failed sync should not create completion marker"
        )
        assert not marker_file.exists()

    def test_git_pull_scenario(self, test_env, test_workspace):
        """Full scenario: User manually git pulls .cec/ and loses .complete marker.

        This is the exact bug scenario:
        1. User imports environment (has .complete)
        2. User pushes to remote (.complete is gitignored, not pushed)
        3. Another user manually pulls .cec/ changes
        4. .complete is missing locally
        5. Environment invisible to list_environments()
        6. Running repair should fix it
        """
        # ARRANGE: Simulate environment after manual git pull
        marker_file = test_env.cec_path / COMPLETION_MARKER
        if marker_file.exists():
            marker_file.unlink()

        # Verify environment is "invisible" (completion check fails)
        assert not is_environment_complete(test_env.cec_path)

        # Verify test_workspace.list_environments() would skip this environment
        visible_envs = test_workspace.list_environments()
        env_names = [e.name for e in visible_envs]
        assert test_env.name not in env_names, (
            "Environment without .complete should not appear in list_environments()"
        )

        # ACT: User runs repair
        sync_result = test_env.sync()

        # ASSERT: Environment should now be visible
        assert sync_result.success
        assert is_environment_complete(test_env.cec_path)

        # Environment should now appear in list
        visible_envs = test_workspace.list_environments()
        env_names = [e.name for e in visible_envs]
        assert test_env.name in env_names, (
            "Environment should be visible after repair adds .complete marker"
        )
