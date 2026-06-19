"""Tests for workflow file storage and sync helpers."""

import json
from unittest.mock import Mock

import pytest
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


def test_copy_workflow_captures_one_saved_workflow(tmp_path):
    """A single saved workflow can be captured without touching other files."""
    cache = Mock()
    store = _store(tmp_path, workflow_cache=cache)

    _write_json(store.comfyui_workflows / "draft.json", {"nodes": [{"id": 1}]})
    _write_json(store.comfyui_workflows / "other.json", {"nodes": [{"id": 2}]})

    result = store.copy_workflow("draft.json")

    assert result == store.cec_workflows / "draft.json"
    assert json.loads(result.read_text(encoding="utf-8")) == {"nodes": [{"id": 1}]}
    assert not (store.cec_workflows / "other.json").exists()
    cache.invalidate.assert_called_once_with(
        env_name="test-env",
        workflow_name="draft",
    )


def test_copy_workflow_preserves_dots_in_extensionless_workflow_names(tmp_path):
    """Workflow names may contain dots that are not file extensions."""
    cache = Mock()
    store = _store(tmp_path, workflow_cache=cache)
    name = "LTX-2.3_-_FML2V_First_Middle_Last_Frame_guider"

    _write_json(store.comfyui_workflows / f"{name}.json", {"nodes": [{"id": 1}]})

    result = store.copy_workflow(name)

    assert result == store.cec_workflows / f"{name}.json"
    assert result.exists()
    cache.invalidate.assert_called_once_with(
        env_name="test-env",
        workflow_name=name,
    )


def test_copy_workflow_requires_saved_comfyui_file(tmp_path):
    """Capturing a workflow must not invent tracked files that were never saved."""
    store = _store(tmp_path)

    with pytest.raises(FileNotFoundError):
        store.copy_workflow("missing")


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
