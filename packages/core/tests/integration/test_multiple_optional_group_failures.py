"""Test handling of multiple optional dependency group failures during sync."""
from unittest.mock import MagicMock

import pytest
from comfygit_core.managers.uv_project_manager import UVProjectManager
from comfygit_core.models.exceptions import UVCommandError


@pytest.fixture
def mock_uv_manager(tmp_path):
    """Create a minimal UVProjectManager mock for testing progressive sync."""
    cec_path = tmp_path / ".cec"
    cec_path.mkdir()

    # Create a real pyproject manager mock
    pyproject = MagicMock()
    pyproject.dependencies = MagicMock()
    pyproject.path = cec_path / "pyproject.toml"  # Set path for project_path property

    # Track removed groups
    removed_groups = []

    def mock_remove_group(group):
        removed_groups.append(group)

    def mock_get_groups():
        # Start with all groups, remove as we go
        all_groups = {
            'optional-cuda': ['sageattention>=2.2.0'],
            'optional-tensorrt': ['tensorrt>=8.0.0'],
            'optional-xformers': ['xformers>=0.0.20'],
            'working-group': ['httpx'],
        }
        for group in removed_groups:
            all_groups.pop(group, None)
        return all_groups

    pyproject.dependencies.remove_group.side_effect = mock_remove_group
    pyproject.dependencies.get_groups.side_effect = mock_get_groups

    # Create UV manager mock
    uv_command = MagicMock()
    overlay_manager = MagicMock()
    overlay_manager.collect_overlays.return_value = []
    uv_manager = UVProjectManager(
        uv_command=uv_command,
        pyproject_manager=pyproject,
        overlay_manager=overlay_manager,
    )

    return uv_manager, removed_groups, cec_path


def test_multiple_optional_groups_fail_sequentially(mock_uv_manager):
    """Test that multiple failing optional groups are handled iteratively."""
    uv_manager, removed_groups, cec_path = mock_uv_manager

    call_count = [0]

    def mock_sync(**kwargs):
        group = kwargs.get('group', [])

        # Track calls
        call_count[0] += 1

        # Fail if specific optional groups are in the list
        if isinstance(group, list):
            if 'optional-cuda' in group:
                raise UVCommandError(
                    "Build failed",
                    command=['uv', 'sync'],
                    stderr="help: `sageattention` was included because `test:optional-cuda` depends on sageattention"
                )
            elif 'optional-tensorrt' in group:
                raise UVCommandError(
                    "Build failed",
                    command=['uv', 'sync'],
                    stderr="help: `tensorrt` was included because `test:optional-tensorrt` depends on tensorrt"
                )
            elif 'optional-xformers' in group:
                raise UVCommandError(
                    "Build failed",
                    command=['uv', 'sync'],
                    stderr="help: `xformers` was included because `test:optional-xformers` depends on xformers"
                )
        # Otherwise success

    uv_manager.sync_project = mock_sync

    # Create lockfile (will be deleted on each retry)
    lockfile = cec_path / "uv.lock"
    lockfile.touch()

    result = uv_manager.sync_dependencies_progressive(dry_run=False, callbacks=None)

    # Verify all three optional groups were removed
    assert len(removed_groups) == 3, f"Expected 3 removed groups, got {len(removed_groups)}: {removed_groups}"
    assert 'optional-cuda' in removed_groups
    assert 'optional-tensorrt' in removed_groups
    assert 'optional-xformers' in removed_groups

    # Verify result tracks all failures
    assert len(result["dependency_groups_failed"]) == 3
    failed_group_names = [g for g, _ in result["dependency_groups_failed"]]
    assert 'optional-cuda' in failed_group_names
    assert 'optional-tensorrt' in failed_group_names
    assert 'optional-xformers' in failed_group_names

    # Verify base install succeeded
    assert result["packages_synced"] is True

    # Verify we made exactly 4 attempts (3 failures + 1 success)
    assert call_count[0] == 4


def test_max_retries_prevents_infinite_loop(mock_uv_manager):
    """Test that we don't loop forever if groups keep failing."""
    uv_manager, removed_groups, cec_path = mock_uv_manager

    # Override get_groups to return many optional groups
    def mock_get_groups():
        all_groups = {f'optional-{i}': [f'pkg-{i}'] for i in range(15)}
        for group in removed_groups:
            all_groups.pop(group, None)
        return all_groups

    uv_manager.pyproject.dependencies.get_groups.side_effect = mock_get_groups

    call_count = [0]

    def mock_sync(**kwargs):
        group = kwargs.get('group', [])
        if isinstance(group, list) and len(group) > 0:
            # Always fail on the first optional group in the list
            first_optional = next((g for g in group if g.startswith('optional-')), None)
            if first_optional:
                call_count[0] += 1
                raise UVCommandError(
                    "Build failed",
                    command=['uv', 'sync'],
                    stderr=f"help: `pkg` was included because `test:{first_optional}` depends on pkg"
                )

    uv_manager.sync_project = mock_sync

    # Create lockfile
    lockfile = cec_path / "uv.lock"
    lockfile.touch()

    # Should raise RuntimeError after MAX_OPT_GROUP_RETRIES (10)
    with pytest.raises(RuntimeError, match="Failed to install dependencies after 10 attempts"):
        uv_manager.sync_dependencies_progressive(dry_run=False, callbacks=None)

    # Should have attempted exactly MAX_OPT_GROUP_RETRIES times
    assert call_count[0] == 10


def test_non_optional_group_failure_stops_immediately(mock_uv_manager):
    """Test that failures in non-optional (required) groups fail immediately without retry."""
    uv_manager, removed_groups, cec_path = mock_uv_manager

    # Override get_groups to include a required (non-optional) group
    def mock_get_groups():
        all_groups = {'required-node-group': ['some-pkg']}
        for group in removed_groups:
            all_groups.pop(group, None)
        return all_groups

    uv_manager.pyproject.dependencies.get_groups.side_effect = mock_get_groups

    # Fail with a required group
    def mock_sync(**kwargs):
        group = kwargs.get('group', [])
        if isinstance(group, list) and 'required-node-group' in group:
            raise UVCommandError(
                "Build failed",
                command=['uv', 'sync'],
                stderr="help: `pkg` was included because `test:required-node-group` depends on pkg"
            )

    uv_manager.sync_project = mock_sync

    lockfile = cec_path / "uv.lock"
    lockfile.touch()

    # Should raise immediately without retry (not an optional group)
    with pytest.raises(UVCommandError):
        uv_manager.sync_dependencies_progressive(dry_run=False, callbacks=None)

    # No groups should have been removed (error parsing won't find 'optional-' prefix)
    assert len(removed_groups) == 0

    # Lockfile should still exist (not deleted because we didn't retry)
    assert lockfile.exists()


def test_lockfile_deleted_on_each_retry(mock_uv_manager):
    """Test that uv.lock is deleted before each retry to force re-resolution."""
    uv_manager, removed_groups, cec_path = mock_uv_manager

    # Override get_groups to include an optional group
    def mock_get_groups():
        all_groups = {'optional-fail': ['some-pkg']}
        for group in removed_groups:
            all_groups.pop(group, None)
        return all_groups

    uv_manager.pyproject.dependencies.get_groups.side_effect = mock_get_groups

    call_count = [0]
    lockfile_deleted = [False]

    def mock_sync(**kwargs):
        group = kwargs.get('group', [])

        # Check if lockfile exists before each call after first
        lockfile = cec_path / "uv.lock"
        if call_count[0] > 0 and not lockfile.exists():
            lockfile_deleted[0] = True

        if isinstance(group, list) and 'optional-fail' in group:
            call_count[0] += 1
            raise UVCommandError(
                "Build failed",
                command=['uv', 'sync'],
                stderr="help: `pkg` was included because `test:optional-fail` depends on pkg"
            )
        # Success on second call (without optional-fail)
        call_count[0] += 1

    uv_manager.sync_project = mock_sync

    # Create initial lockfile
    lockfile = cec_path / "uv.lock"
    lockfile.touch()

    uv_manager.sync_dependencies_progressive(dry_run=False, callbacks=None)

    # Verify lockfile was deleted during retry
    assert lockfile_deleted[0] is True, "Lockfile should be deleted before retry"


def test_overlay_names_are_forwarded_to_sync_project(mock_uv_manager):
    """Ad-hoc overlay names should flow through progressive sync retries."""
    uv_manager, _, _ = mock_uv_manager

    uv_manager.pyproject.dependencies.get_groups.side_effect = lambda: {}
    seen_overlay_names = []

    def mock_sync(**kwargs):
        seen_overlay_names.append(kwargs.get("overlay_names"))

    uv_manager.sync_project = mock_sync

    result = uv_manager.sync_dependencies_progressive(
        dry_run=False,
        callbacks=None,
        overlay_names=["sageattention"],
    )

    assert result["packages_synced"] is True
    assert seen_overlay_names == [["sageattention"]]
