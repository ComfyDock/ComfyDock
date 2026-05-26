"""Tests for workflow file storage and sync helpers."""

import json
from unittest.mock import Mock

from comfygit_core.services.workflow_file_store import WorkflowFileStore


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _store(tmp_path, workflow_cache=None):
    return WorkflowFileStore(
        tmp_path / "ComfyUI",
        tmp_path / ".cec",
        environment_name="test-env",
        workflow_cache=workflow_cache,
    )


def test_workflows_differ_ignores_volatile_workflow_metadata(tmp_path):
    """UI-only metadata changes should not make workflows appear modified."""
    store = _store(tmp_path)

    tracked = {
        "id": "wf",
        "revision": 1,
        "nodes": [
            {
                "id": 1,
                "type": "KSampler",
                "widgets_values": [12345, "randomize", 20],
            },
        ],
        "extra": {"frontendVersion": "1.0", "ds": {"scale": 1}},
    }
    live = {
        "id": "wf",
        "revision": 9,
        "nodes": [
            {
                "id": 1,
                "type": "KSampler",
                "widgets_values": [99999, "randomize", 20],
            },
        ],
        "extra": {"frontendVersion": "2.0", "ds": {"scale": 2}},
    }

    _write_json(store.cec_workflows / "workflow.json", tracked)
    _write_json(store.comfyui_workflows / "workflow.json", live)

    assert store.workflows_differ("workflow") is False
    assert store.get_workflow_sync_status().synced == ["workflow"]


def test_copy_all_workflows_invalidates_modified_and_deleted_workflows(tmp_path):
    """Committing changed/deleted workflow files invalidates affected cache rows."""
    cache = Mock()
    store = _store(tmp_path, workflow_cache=cache)

    _write_json(store.cec_workflows / "changed.json", {"nodes": []})
    _write_json(store.comfyui_workflows / "changed.json", {"nodes": [{"id": 1}]})
    _write_json(store.cec_workflows / "deleted.json", {"nodes": []})

    results = store.copy_all_workflows()

    assert results["changed"] == store.cec_workflows / "changed.json"
    assert results["deleted"] == "deleted"
    assert not (store.cec_workflows / "deleted.json").exists()
    cache.invalidate.assert_any_call(env_name="test-env", workflow_name="changed")
    cache.invalidate.assert_any_call(env_name="test-env", workflow_name="deleted")
    assert cache.invalidate.call_count == 2


def test_restore_all_from_cec_removes_workflows_absent_from_tracked_storage(tmp_path):
    """Branch-style restore should remove live workflows absent from `.cec`."""
    store = _store(tmp_path)

    _write_json(store.comfyui_workflows / "local_only.json", {"nodes": []})

    results = store.restore_all_from_cec(preserve_uncommitted=False)

    assert results == {"local_only": "removed"}
    assert not (store.comfyui_workflows / "local_only.json").exists()


def test_restore_all_from_cec_can_preserve_uncommitted_workflows(tmp_path):
    """Safe branch operations can preserve live workflows not yet committed."""
    store = _store(tmp_path)

    _write_json(store.comfyui_workflows / "local_only.json", {"nodes": []})

    results = store.restore_all_from_cec(preserve_uncommitted=True)

    assert results == {}
    assert (store.comfyui_workflows / "local_only.json").exists()
