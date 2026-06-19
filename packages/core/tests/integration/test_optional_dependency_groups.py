"""Test graceful handling of optional dependency groups during sync.

Tests that optional dependency groups (prefixed with 'optional-') can fail
without breaking the entire sync operation, while non-optional groups must succeed.
"""

from unittest.mock import patch

from comfygit_core.models.exceptions import UVCommandError


def run_sync_with_mocked_uv(test_env, sync_fn):
    """Run env sync while mocking both durable and disposable uv sync paths."""
    class FakeDisposableUV:
        def sync(self, verbose=False, **flags):
            return sync_fn(verbose=verbose, **flags)

    with (
        patch.object(test_env.uv_manager.uv, 'sync', side_effect=sync_fn),
        patch.object(test_env.uv_manager.uv, 'for_cwd', return_value=FakeDisposableUV()),
    ):
        return test_env.sync()


class TestOptionalDependencyGroups:
    """Test progressive dependency group installation with graceful fallback."""

    def test_sync_with_failing_optional_group_continues(self, test_env):
        """When optional group fails, sync should retry without it and continue."""
        # ARRANGE: Add optional and required groups to pyproject
        config = test_env.pyproject.load()

        # Add optional group (will simulate failure)
        config.setdefault("dependency-groups", {})
        config["dependency-groups"]["optional-cuda"] = ["sageattention>=2.2.0"]

        # Add node dependency group (must succeed)
        config["dependency-groups"]["comfyui-test-node"] = ["numpy>=1.20.0"]

        test_env.pyproject.save(config)

        # ACT: Mock uv.sync to fail when optional-cuda is included, succeed otherwise
        from comfygit_core.integrations.uv_command import CommandResult

        call_count = [0]
        def mock_sync(verbose=False, **flags):
            call_count[0] += 1
            group = flags.get('group', [])

            # Fail if trying to sync with optional-cuda in the group list
            if isinstance(group, list) and 'optional-cuda' in group:
                raise UVCommandError(
                    "Failed to install sageattention",
                    command=["uv", "sync", "--group", "optional-cuda"],
                    stderr="help: `sageattention` (v2.2.0) was included because `test:optional-cuda` (v1.0.0) depends on sageattention>=2.2.0",
                    stdout="",
                    returncode=1
                )
            # Otherwise return success
            return CommandResult(stdout="", stderr="", returncode=0, success=True)

        result = run_sync_with_mocked_uv(test_env, mock_sync)

        # ASSERT: Sync should succeed overall despite optional group failure
        assert result.success, "Sync should succeed despite optional group failure"
        assert result.packages_synced, "Base packages should be installed"

        # Failed optional groups should be tracked
        assert len(result.dependency_groups_failed) == 1
        assert result.dependency_groups_failed[0][0] == "optional-cuda"
        assert result.dependency_groups_skipped == ["optional-cuda"]

        # Portable manifest intent should be preserved.
        groups_after_sync = test_env.pyproject.dependencies.get_groups()
        assert "optional-cuda" in groups_after_sync

        # Required groups should succeed (installed in second call without optional-cuda)
        assert "comfyui-test-node" in result.dependency_groups_installed

    def test_sync_with_failing_required_group_fails(self, test_env):
        """When non-optional (required) group fails, sync should fail entirely."""
        # ARRANGE: Add required node dependency group
        config = test_env.pyproject.load()
        config.setdefault("dependency-groups", {})
        config["dependency-groups"]["comfyui-critical-node"] = ["nonexistent-package>=1.0.0"]
        test_env.pyproject.save(config)

        # ACT: Mock to fail when required group is in list (not prefixed with 'optional-')
        from comfygit_core.integrations.uv_command import CommandResult

        def mock_sync(verbose=False, **flags):
            group = flags.get('group', [])
            # Fail if comfyui-critical-node is in the group list
            if isinstance(group, list) and 'comfyui-critical-node' in group:
                raise UVCommandError(
                    "Failed to install nonexistent-package",
                    command=["uv", "sync", "--group", "comfyui-critical-node"],
                    stderr="error: package not found: nonexistent-package",
                    stdout="",
                    returncode=1
                )
            return CommandResult(stdout="", stderr="", returncode=0, success=True)

        result = run_sync_with_mocked_uv(test_env, mock_sync)

        # ASSERT: Sync should fail (result.success = False)
        assert not result.success, "Sync should fail when required group fails"
        assert len(result.errors) > 0, "Should have error messages"

    def test_sync_installs_groups_together(self, test_env):
        """All groups should be installed together in one batch call."""
        # ARRANGE: Add multiple groups
        config = test_env.pyproject.load()
        config.setdefault("dependency-groups", {})
        config["dependency-groups"]["optional-accel"] = ["pillow>=9.0.0"]
        config["dependency-groups"]["optional-extra"] = ["pyyaml>=5.0"]
        config["dependency-groups"]["comfyui-node-a"] = ["requests>=2.0.0"]
        test_env.pyproject.save(config)

        # ACT: Track sync calls
        from comfygit_core.integrations.uv_command import CommandResult
        sync_calls = []

        def track_sync(verbose=False, **flags):
            sync_calls.append(flags.copy())
            return CommandResult(stdout="", stderr="", returncode=0, success=True)

        result = run_sync_with_mocked_uv(test_env, track_sync)

        # ASSERT: Should have ONE install sync call with all groups. Sync may also
        # perform overlay-aware dry-run probes that should not count as installs.
        install_sync_calls = [call for call in sync_calls if not call.get("dry_run")]
        assert len(install_sync_calls) == 1, (
            f"Expected 1 install sync call, got {len(install_sync_calls)}"
        )

        # The call should have all groups in a list
        groups = install_sync_calls[0].get('group', [])
        assert isinstance(groups, list), "Group should be a list"
        assert set(groups) == {
            'comfygit-system',
            'optional-accel',
            'optional-extra',
            'comfyui-node-a',
        }

        # Result should track all groups as installed
        assert set(result.dependency_groups_installed) == {
            'comfygit-system',
            'optional-accel',
            'optional-extra',
            'comfyui-node-a',
        }

    def test_sync_result_tracks_all_group_outcomes(self, test_env):
        """SyncResult should track which groups succeeded and failed."""
        # ARRANGE: Mix of optional and required groups
        config = test_env.pyproject.load()
        config.setdefault("dependency-groups", {})
        config["dependency-groups"]["optional-good"] = ["pyyaml>=5.0"]
        config["dependency-groups"]["optional-bad"] = ["fake-package>=1.0"]
        config["dependency-groups"]["comfyui-node"] = ["requests>=2.0.0"]
        test_env.pyproject.save(config)

        # ACT: Mock to fail when optional-bad is in the group list, then succeed on retry
        from comfygit_core.integrations.uv_command import CommandResult

        def selective_mock_sync(verbose=False, **flags):
            group = flags.get('group', [])
            # Fail if optional-bad is in the group list
            if isinstance(group, list) and 'optional-bad' in group:
                raise UVCommandError(
                    "Failed to install fake-package",
                    command=["uv", "sync", "--group", "optional-bad"],
                    stderr="help: `fake-package` (v1.0) was included because `test:optional-bad` (v1.0.0) depends on fake-package>=1.0",
                    stdout="",
                    returncode=1
                )
            return CommandResult(stdout="", stderr="", returncode=0, success=True)

        result = run_sync_with_mocked_uv(test_env, selective_mock_sync)

        # ASSERT: Should track both successes and failures
        assert result.success, "Overall sync should succeed"

        # Successful groups (installed after removing optional-bad)
        assert "optional-good" in result.dependency_groups_installed
        assert "comfyui-node" in result.dependency_groups_installed

        # Failed groups
        assert len(result.dependency_groups_failed) == 1
        failed_group, error = result.dependency_groups_failed[0]
        assert failed_group == "optional-bad"
        assert result.dependency_groups_skipped == ["optional-bad"]
        assert "optional-bad" in test_env.pyproject.dependencies.get_groups()

    def test_all_optional_groups_fail_sync_still_succeeds(self, test_env):
        """If all optional groups fail but base deps succeed, sync should succeed."""
        # ARRANGE: Only optional groups, all will fail
        config = test_env.pyproject.load()
        config.setdefault("dependency-groups", {})
        config["dependency-groups"]["optional-a"] = ["fake-a>=1.0"]
        config["dependency-groups"]["optional-b"] = ["fake-b>=1.0"]
        test_env.pyproject.save(config)

        # ACT: Mock to fail when any optional groups are in the list
        from comfygit_core.integrations.uv_command import CommandResult

        def fail_optional_sync(verbose=False, **flags):
            group = flags.get('group', [])
            # Fail if any optional groups are being installed
            if isinstance(group, list):
                # Find the first optional group and fail with an error mentioning that specific group
                optional_groups = [g for g in group if g.startswith('optional-')]
                if optional_groups:
                    failing_group = optional_groups[0]
                    package_name = failing_group.replace('optional-', 'fake-')
                    raise UVCommandError(
                        "Failed",
                        command=["uv", "sync"],
                        stderr=f"help: `{package_name}` (v1.0) was included because `test:{failing_group}` (v1.0.0) depends on {package_name}>=1.0",
                        stdout="",
                        returncode=1
                    )
            # Succeed when no groups (base deps only)
            return CommandResult(stdout="", stderr="", returncode=0, success=True)

        result = run_sync_with_mocked_uv(test_env, fail_optional_sync)

        # ASSERT
        assert result.success, "Sync should succeed even if all optional groups fail"
        assert len(result.dependency_groups_failed) >= 1, "Should track at least one failed group"
        assert set(result.dependency_groups_skipped) >= {"optional-a", "optional-b"}
        groups_after_sync = test_env.pyproject.dependencies.get_groups()
        assert "optional-a" in groups_after_sync
        assert "optional-b" in groups_after_sync
        assert result.packages_synced, "Base dependencies should be installed"

    def test_empty_dependency_groups_works(self, test_env):
        """Sync should work fine with no dependency groups."""
        # ARRANGE: No dependency groups
        config = test_env.pyproject.load()
        config.pop("dependency-groups", None)
        test_env.pyproject.save(config)

        # ACT
        result = test_env.sync()

        # ASSERT
        assert result.success
        assert result.packages_synced
        assert result.dependency_groups_installed == ["comfygit-system"]
        assert len(result.dependency_groups_failed) == 0
