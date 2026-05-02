from comfygit_core.models.dependency_resolution import PackageVersionChange
from comfygit_core.services.dependency_resolution_preview import (
    DependencyResolutionPreviewService,
)


def test_diff_packages_classifies_added_removed_and_version_changes():
    service = DependencyResolutionPreviewService.__new__(DependencyResolutionPreviewService)

    before = {
        "click": {"version": "8.3.3", "fingerprint": "click-old"},
        "typer": {"version": "0.25.1", "fingerprint": "typer-old"},
        "old-only": {"version": "1.0.0", "fingerprint": "old"},
        "same-version": {"version": "1.0.0", "fingerprint": "same-old"},
    }
    after = {
        "click": {"version": "8.1.8", "fingerprint": "click-new"},
        "typer": {"version": "0.26.0", "fingerprint": "typer-new"},
        "new-only": {"version": "2.0.0", "fingerprint": "new"},
        "same-version": {"version": "1.0.0", "fingerprint": "same-new"},
    }

    changes = service._diff_packages(before, after)

    assert changes == [
        PackageVersionChange("new-only", None, "2.0.0", "added"),
        PackageVersionChange("old-only", "1.0.0", None, "removed"),
        PackageVersionChange("click", "8.3.3", "8.1.8", "downgraded"),
        PackageVersionChange("same-version", "1.0.0", "1.0.0", "changed"),
        PackageVersionChange("typer", "0.25.1", "0.26.0", "upgraded"),
    ]


def test_package_version_change_properties_group_by_kind():
    from comfygit_core.models.dependency_resolution import DependencyResolutionPreview

    preview = DependencyResolutionPreview(
        success=True,
        node_name="example-node",
        changes=(
            PackageVersionChange("a", None, "1.0.0", "added"),
            PackageVersionChange("b", "1.0.0", None, "removed"),
            PackageVersionChange("c", "2.0.0", "1.0.0", "downgraded"),
            PackageVersionChange("d", "1.0.0", "2.0.0", "upgraded"),
        ),
    )

    assert [change.name for change in preview.added] == ["a"]
    assert [change.name for change in preview.removed] == ["b"]
    assert [change.name for change in preview.downgraded] == ["c"]
    assert [change.name for change in preview.upgraded] == ["d"]


def test_lock_temp_project_injects_pytorch_backend_and_restores_pyproject(tmp_path, monkeypatch):
    from comfygit_core.integrations.uv_command import UVCommand

    temp_project = tmp_path / "project"
    temp_project.mkdir()
    pyproject = temp_project / "pyproject.toml"
    original = """[project]
name = "preview-test"
version = "0.1.0"
requires-python = "==3.11.*"
dependencies = ["torch", "torchaudio", "torchvision"]

[tool.comfygit]
python_version = "3.11"
"""
    pyproject.write_text(original, encoding="utf-8")
    (temp_project / ".pytorch-backend").write_text(
        "cu126\n"
        "torch=2.11.0+cu126\n"
        "torchaudio=2.11.0+cu126\n"
        "torchvision=0.26.0+cu126\n",
        encoding="utf-8",
    )

    observed = {}

    def fake_lock(self, **_flags):
        content = (self._cwd / "pyproject.toml").read_text(encoding="utf-8")
        observed["content"] = content

    monkeypatch.setattr(UVCommand, "lock", fake_lock)

    service = DependencyResolutionPreviewService(
        cec_path=temp_project,
        workspace_path=tmp_path / "workspace",
    )

    service._lock_temp_project(temp_project)

    assert "pytorch-cu126" in observed["content"]
    assert "torch==2.11.0+cu126" in observed["content"]
    assert "torchaudio==2.11.0+cu126" in observed["content"]
    assert "torchvision==0.26.0+cu126" in observed["content"]
    assert pyproject.read_text(encoding="utf-8") == original
