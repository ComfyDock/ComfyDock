"""Coverage for staged node dependency provisioning during sync."""

from types import SimpleNamespace


def _progressive_sync_result() -> dict:
    return {
        "packages_synced": True,
        "dependency_groups_installed": [],
        "dependency_groups_failed": [],
    }


def _prepare_sync(test_env, monkeypatch):
    monkeypatch.setattr(test_env, "_ensure_schema_migrated", lambda: False)
    monkeypatch.setattr(test_env.package_config, "ensure_exists", lambda: None)
    monkeypatch.setattr(
        test_env.pyproject.uv_config,
        "set_exclude_dependencies",
        lambda _packages: None,
    )
    monkeypatch.setattr(
        test_env.pyproject,
        "resolve_sync_extras",
        lambda extras, all_extras: (extras, all_extras),
    )
    monkeypatch.setattr(
        test_env.uv_manager,
        "sync_dependencies_progressive",
        lambda **_kwargs: _progressive_sync_result(),
    )
    monkeypatch.setattr(
        test_env,
        "status",
        lambda: SimpleNamespace(
            comparison=SimpleNamespace(version_mismatches=[]),
        ),
    )
    monkeypatch.setattr(
        test_env.node_manager,
        "sync_nodes_to_filesystem",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        test_env.workflow_manager,
        "restore_all_from_cec",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        test_env.model_symlink_manager,
        "create_symlink",
        lambda: None,
    )
    monkeypatch.setattr(
        test_env.user_content_manager,
        "create_directories",
        lambda: None,
    )
    monkeypatch.setattr(
        test_env.user_content_manager,
        "create_symlinks",
        lambda: None,
    )
    monkeypatch.setattr(
        "comfygit_core.utils.environment_cleanup.mark_environment_complete",
        lambda *_args, **_kwargs: None,
    )


def test_sync_runs_one_final_uv_sync_after_staging_node_groups(test_env, monkeypatch):
    _prepare_sync(test_env, monkeypatch)

    sync_calls: list[dict] = []

    monkeypatch.setattr(
        test_env.node_manager,
        "provision_missing_node_dependencies",
        lambda: ["test-node-abcd1234"],
    )
    monkeypatch.setattr(
        test_env.uv_manager,
        "sync_project",
        lambda **kwargs: sync_calls.append(kwargs) or "",
    )

    result = test_env.sync(
        model_strategy="skip",
        overlay_names=["shared"],
        extras=["gpu"],
    )

    assert result.success is True
    assert result.dependency_groups_installed == ["test-node-abcd1234"]
    assert len(sync_calls) == 1
    assert sync_calls[0]["all_groups"] is True
    assert sync_calls[0]["overlay_names"] == ["shared"]
    assert sync_calls[0]["extras"] == ["gpu"]
    assert sync_calls[0]["pytorch_manager"] is test_env.pytorch_manager


def test_sync_skips_final_uv_sync_when_no_node_groups_are_staged(test_env, monkeypatch):
    _prepare_sync(test_env, monkeypatch)

    sync_calls: list[dict] = []

    monkeypatch.setattr(
        test_env.node_manager,
        "provision_missing_node_dependencies",
        lambda: [],
    )
    monkeypatch.setattr(
        test_env.uv_manager,
        "sync_project",
        lambda **kwargs: sync_calls.append(kwargs) or "",
    )

    result = test_env.sync(model_strategy="skip")

    assert result.success is True
    assert result.dependency_groups_installed == []
    assert sync_calls == []
