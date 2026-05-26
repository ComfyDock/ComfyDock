from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from comfygit_core.services.workflow_file_store import WorkflowFileStore
from comfygit_core.services.workflow_state_cleanup import WorkflowStateCleanup


class _FakeManifestEdit:
    def __init__(self, config: dict):
        self.config = config
        self.changed = False

    def mark_changed(self) -> None:
        self.changed = True


class _FakeManifest:
    def __init__(self, config: dict):
        self.config = config
        self.last_edit: _FakeManifestEdit | None = None
        self.snapshot_workflows = {}

    @contextmanager
    def edit(self):
        edit = _FakeManifestEdit(self.config)
        self.last_edit = edit
        yield edit

    def snapshot(self, force_reload: bool = False):
        return SimpleNamespace(workflows=self.snapshot_workflows)


class _FakeWorkflowHandler:
    def __init__(self, config: dict):
        self.config = config

    def remove_workflows(self, workflow_names: list[str], config: dict | None = None) -> int:
        target = config or self.config
        workflows = target.get("tool", {}).get("comfygit", {}).get("workflows", {})

        removed = 0
        for name in workflow_names:
            if name in workflows:
                del workflows[name]
                removed += 1
        return removed


class _FakePyproject:
    def __init__(self, config: dict):
        self.manifest = _FakeManifest(config)
        self.workflows = _FakeWorkflowHandler(config)


def _file_store(tmp_path):
    return WorkflowFileStore(
        tmp_path / "ComfyUI",
        tmp_path / ".cec",
        environment_name="test-env",
    )


def _cleanup(tmp_path, config: dict) -> tuple[WorkflowStateCleanup, _FakePyproject]:
    pyproject = _FakePyproject(config)
    service = WorkflowStateCleanup(
        manifest=pyproject.manifest,
        workflows=pyproject.workflows,
        workflow_file_store=_file_store(tmp_path),
        cec_path=tmp_path / ".cec",
    )
    return service, pyproject


def test_cleanup_removes_manifest_workflows_missing_from_comfyui(tmp_path):
    config = {
        "tool": {
            "comfygit": {
                "workflows": {
                    "kept": {"path": "workflows/kept.json"},
                    "gone": {"path": "workflows/gone.json"},
                }
            }
        }
    }
    service, pyproject = _cleanup(tmp_path, config)
    service.workflow_file_store.workflow_path("kept").write_text("{}", encoding="utf-8")

    result = service.cleanup()

    workflows = config["tool"]["comfygit"]["workflows"]
    assert result.workflow_entries == 1
    assert result.api_prompts == 0
    assert "kept" in workflows
    assert "gone" not in workflows
    assert pyproject.manifest.last_edit is not None
    assert pyproject.manifest.last_edit.changed is True


def test_cleanup_api_prompts_normalizes_snapshot_references(tmp_path):
    config = {"tool": {"comfygit": {"workflows": {}}}}
    service, pyproject = _cleanup(tmp_path, config)

    api_dir = tmp_path / ".cec" / "workflow_api" / "nested"
    api_dir.mkdir(parents=True)
    kept = api_dir / "kept.json"
    orphan = api_dir / "orphan.json"
    kept.write_text("{}", encoding="utf-8")
    orphan.write_text("{}", encoding="utf-8")

    pyproject.manifest.snapshot_workflows = {
        "kept": SimpleNamespace(
            execution_contract=SimpleNamespace(
                api_prompt_file="workflow_api\\nested\\kept.json"
            )
        )
    }

    removed = service.cleanup_orphaned_workflow_api_prompts()

    assert removed == 1
    assert kept.exists()
    assert not orphan.exists()
