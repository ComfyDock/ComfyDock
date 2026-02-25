"""Integration tests for overlay-related git flows and lock behavior."""

from __future__ import annotations

import json
import threading

import pytest

from comfygit_core.models.exceptions import CDEnvironmentError


def test_execute_atomic_merge_runs_post_merge_sync(test_env, monkeypatch):
    """Successful atomic merge should trigger post-merge environment sync."""
    env = test_env

    workflows_dir = env.cec_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)

    wf1_v1 = {"version": "1.0", "nodes": {"1": {"class_type": "KSampler"}}}
    wf2_v1 = {"version": "1.0", "nodes": {"1": {"class_type": "KSampler"}}}
    (workflows_dir / "wf1.json").write_text(json.dumps(wf1_v1), encoding="utf-8")
    (workflows_dir / "wf2.json").write_text(json.dumps(wf2_v1), encoding="utf-8")
    env.git_manager.commit_all("Add workflows v1")

    env.git_manager.create_branch("feature")
    env.git_manager.switch_branch("feature")

    wf1_v2 = {"version": "2.0", "nodes": {"1": {"class_type": "KSamplerAdvanced"}}}
    wf2_v2 = {"version": "2.0", "nodes": {"1": {"class_type": "KSamplerAdvanced"}}}
    (workflows_dir / "wf1.json").write_text(json.dumps(wf1_v2), encoding="utf-8")
    (workflows_dir / "wf2.json").write_text(json.dumps(wf2_v2), encoding="utf-8")
    env.git_manager.commit_all("Update workflows to v2")

    env.git_manager.switch_branch("main")

    sync_calls: list[dict] = []

    def _fake_sync(old_nodes, preserve_uncommitted=False):
        sync_calls.append(
            {
                "old_nodes": dict(old_nodes),
                "preserve_uncommitted": preserve_uncommitted,
            }
        )

    monkeypatch.setattr(env.git_orchestrator, "_sync_environment_after_git", _fake_sync)

    result = env.execute_atomic_merge(
        "feature",
        {"wf1": "take_target", "wf2": "take_base"},
    )

    assert result.success, result.error
    assert len(sync_calls) == 1
    assert sync_calls[0]["preserve_uncommitted"] is False
    assert isinstance(sync_calls[0]["old_nodes"], dict)


def test_revert_commit_rejects_concurrent_calls(test_env, monkeypatch):
    """Concurrent revert attempts should fail with environment lock error."""
    env = test_env

    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def _slow_revert(commit: str) -> None:
        calls.append(commit)
        entered.set()
        assert release.wait(timeout=2)

    monkeypatch.setattr(env.git_orchestrator, "revert_commit", _slow_revert)

    worker = threading.Thread(target=lambda: env.revert_commit("first"), daemon=True)
    worker.start()
    assert entered.wait(timeout=1)

    with pytest.raises(CDEnvironmentError, match="Another ComfyGit operation is running"):
        env.revert_commit("second")

    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert calls == ["first"]
