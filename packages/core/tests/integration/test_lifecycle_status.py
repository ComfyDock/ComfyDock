"""Integration coverage for lifecycle status over real environment signals."""

from comfygit_core.models import NodeInfo


def _action_ids(lifecycle):
    return [action.id for action in lifecycle.actions]


def _issue_ids(lifecycle):
    return [issue.id for issue in lifecycle.issues]


def test_lifecycle_status_reports_declared_node_missing_on_disk(test_env):
    test_env.pyproject.nodes.add(
        NodeInfo(
            name="ComfyUI-Impact-Pack",
            registry_id="comfyui-impact-pack",
            source="registry",
            version="1.0.0",
        ),
        "comfyui-impact-pack",
    )

    lifecycle = test_env.get_lifecycle_status()

    assert lifecycle.primary_action_id == "sync_missing_nodes"
    assert "missing_declared_nodes" in _issue_ids(lifecycle)
    assert "sync_missing_nodes" in _action_ids(lifecycle)
    assert lifecycle.layer("filesystem").status == "blocked"


def test_lifecycle_status_reports_leftover_untracked_node_folder(test_env):
    node_path = test_env.custom_nodes_path / "leftover-node"
    node_path.mkdir(parents=True)
    (node_path / "nodes.py").write_text("# leftover node\n", encoding="utf-8")

    lifecycle = test_env.get_lifecycle_status()

    assert lifecycle.primary_action_id == "review_untracked_node"
    assert "untracked_node_folder" in _issue_ids(lifecycle)
    review = next(action for action in lifecycle.actions if action.id == "review_untracked_node")
    remove = next(action for action in lifecycle.actions if action.id == "remove_untracked_node")
    assert review.confirmation_required is True
    assert remove.destructive is True


def test_lifecycle_status_reports_untracked_development_checkout(test_env):
    node_path = test_env.custom_nodes_path / "dev-node"
    node_path.mkdir(parents=True)
    (node_path / "nodes.py").write_text("# dev node\n", encoding="utf-8")
    (node_path / ".git").mkdir()
    (node_path / ".git" / "config").write_text("[core]\n", encoding="utf-8")

    lifecycle = test_env.get_lifecycle_status()

    assert lifecycle.primary_action_id == "track_dev_node"
    assert "untracked_development_node" in _issue_ids(lifecycle)
    assert "track_dev_node" in _action_ids(lifecycle)


def test_lifecycle_status_reports_uncommitted_manifest_changes_after_health_is_clean(test_env):
    config = test_env.pyproject.load()
    config["project"]["description"] = "dirty lifecycle test"
    test_env.pyproject.save(config)

    lifecycle = test_env.get_lifecycle_status()

    assert lifecycle.primary_action_id == "commit_snapshot"
    assert "uncommitted_changes" in _issue_ids(lifecycle)
    assert lifecycle.layer("snapshot").status == "attention"
