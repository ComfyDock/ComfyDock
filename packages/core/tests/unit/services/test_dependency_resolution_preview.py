import pytest
from comfygit_core.managers.node_manager import NodeManager
from comfygit_core.models.dependency_resolution import (
    DependencyResolutionAcceptance,
    DependencyResolutionApplyResult,
    DependencyResolutionPreview,
    PackageVersionChange,
)
from comfygit_core.models.exceptions import CDDependencyPreviewStaleError
from comfygit_core.models.shared import NodeInfo, NodePackage
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


def test_lock_temp_project_injects_overlays_pytorch_backend_and_restores_pyproject(
    tmp_path,
    monkeypatch,
):
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
    (temp_project / ".overlay-config.toml").write_text(
        'active = ["stability"]\n',
        encoding="utf-8",
    )
    overlays_dir = temp_project / "overlays"
    overlays_dir.mkdir()
    (overlays_dir / "stability.toml").write_text(
        """[overlay]
description = "Test active overlay"

[dependencies]
packages = ["example-lib==1.2.3"]

[constraints]
packages = ["click<8.2"]
""",
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
    assert "example-lib==1.2.3" in observed["content"]
    assert "click<8.2" in observed["content"]
    assert pyproject.read_text(encoding="utf-8") == original


def test_copy_project_files_includes_overlay_activation_config(tmp_path):
    cec_path = tmp_path / "source"
    cec_path.mkdir()
    (cec_path / "pyproject.toml").write_text("[project]\nname = \"example\"\n", encoding="utf-8")
    (cec_path / ".overlay-config.toml").write_text('active = ["stability"]\n', encoding="utf-8")

    temp_project = tmp_path / "temp"
    temp_project.mkdir()

    service = DependencyResolutionPreviewService(
        cec_path=cec_path,
        workspace_path=tmp_path / "workspace",
    )

    service._copy_project_files(temp_project)

    assert (temp_project / ".overlay-config.toml").read_text(encoding="utf-8") == (
        'active = ["stability"]\n'
    )


def test_preview_diffs_against_overlay_aware_baseline(tmp_path, monkeypatch):
    cec_path = tmp_path / "source"
    cec_path.mkdir()
    (cec_path / "pyproject.toml").write_text("[project]\nname = \"example\"\n", encoding="utf-8")
    (cec_path / "uv.lock").write_text(
        """[[package]]
name = "comfygit-core"
version = "0.3.22"
source = { registry = "https://pypi.org/simple" }
""",
        encoding="utf-8",
    )

    baseline_lock = """[[package]]
name = "comfygit-core"
version = "0.3.22"
source = { editable = "../core" }
"""
    proposed_lock = baseline_lock + """
[[package]]
name = "depthflow"
version = "0.9.1"
source = { registry = "https://pypi.org/simple" }
"""

    def fake_lock(self, temp_project):
        lock_text = proposed_lock if (temp_project / ".node-applied").exists() else baseline_lock
        (temp_project / "uv.lock").write_text(lock_text, encoding="utf-8")

    def fake_apply(self, temp_project, node_package):
        (temp_project / ".node-applied").write_text(node_package.name, encoding="utf-8")

    monkeypatch.setattr(DependencyResolutionPreviewService, "_lock_temp_project", fake_lock)
    monkeypatch.setattr(DependencyResolutionPreviewService, "_apply_node_package", fake_apply)

    service = DependencyResolutionPreviewService(
        cec_path=cec_path,
        workspace_path=tmp_path / "workspace",
    )
    node_package = NodePackage(
        node_info=NodeInfo(name="ComfyUI-Depthflow-Nodes", registry_id="comfyui-depthflow-nodes"),
        requirements=["depthflow==0.9.1"],
    )

    preview = service.preview_node_package(node_package)

    assert preview.success is True
    assert preview.baseline_fingerprint
    assert preview.diff_fingerprint
    assert preview.proposed_fingerprint
    assert preview.lockfile_changed is True
    assert preview.changes == (
        PackageVersionChange("depthflow", None, "0.9.1", "added"),
    )


def test_read_lock_packages_can_exclude_root_project_package(tmp_path):
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text(
        """[[package]]
name = "comfygit-env-example"
version = "0.1.0"

[[package]]
name = "depthflow"
version = "0.9.1"
""",
        encoding="utf-8",
    )
    service = DependencyResolutionPreviewService.__new__(DependencyResolutionPreviewService)

    packages = service._read_lock_packages(
        lock_path,
        excluded_names={"comfygit-env-example"},
    )

    assert list(packages) == ["depthflow"]


def test_lock_fingerprint_normalizes_relative_editable_sources(tmp_path):
    service = DependencyResolutionPreviewService.__new__(DependencyResolutionPreviewService)
    absolute_source = {
        "editable": str(tmp_path / "packages" / "core"),
    }
    relative_source = {
        "editable": "packages/core",
    }
    lock_dir = tmp_path

    assert service._normalize_lock_source(absolute_source, lock_dir) == (
        service._normalize_lock_source(relative_source, lock_dir)
    )


def test_lock_fingerprint_ignores_distribution_archive_metadata(tmp_path):
    service = DependencyResolutionPreviewService.__new__(DependencyResolutionPreviewService)

    first = {
        "name": "greenlet",
        "version": "3.5.0",
        "source": {"registry": "https://pypi.org/simple"},
        "wheels": [{"url": "one.whl"}],
    }
    second = {
        "name": "greenlet",
        "version": "3.5.0",
        "source": {"registry": "https://pypi.org/simple"},
        "wheels": [{"url": "one.whl"}, {"url": "two.whl"}],
        "sdist": {"url": "source.tar.gz"},
    }

    assert service._lock_package_fingerprint(first, tmp_path) == (
        service._lock_package_fingerprint(second, tmp_path)
    )


def test_apply_reviewed_dependency_changes_requires_fresh_matching_preview():
    manager = NodeManager.__new__(NodeManager)
    preview = DependencyResolutionPreview(
        success=True,
        node_name="ComfyUI-Depthflow-Nodes",
        baseline_fingerprint="baseline",
        diff_fingerprint="diff",
        proposed_fingerprint="proposed",
    )
    acceptance = DependencyResolutionAcceptance(
        identifier="comfyui-depthflow-nodes",
        baseline_fingerprint="baseline",
        diff_fingerprint="diff",
        proposed_fingerprint="proposed",
    )
    installed = {}

    manager.preview_add_node_dependency_changes = lambda identifier: preview

    def fake_add_node(identifier, **kwargs):
        installed["identifier"] = identifier
        installed["kwargs"] = kwargs
        return NodeInfo(name="ComfyUI-Depthflow-Nodes")

    manager.add_node = fake_add_node

    result = manager.apply_reviewed_dependency_changes(
        "comfyui-depthflow-nodes",
        acceptance,
    )

    assert result == DependencyResolutionApplyResult(
        success=True,
        identifier="comfyui-depthflow-nodes",
        node_name="ComfyUI-Depthflow-Nodes",
        installed=True,
        needs_restart=True,
        message="Installed ComfyUI-Depthflow-Nodes",
    )
    assert installed["kwargs"] == {
        "allow_reviewed_dependency_changes": True,
        "skip_optional_overlays": False,
    }


def test_apply_reviewed_dependency_changes_rejects_stale_preview():
    manager = NodeManager.__new__(NodeManager)
    preview = DependencyResolutionPreview(
        success=True,
        node_name="ComfyUI-Depthflow-Nodes",
        baseline_fingerprint="new-baseline",
        diff_fingerprint="diff",
        proposed_fingerprint="proposed",
    )
    acceptance = DependencyResolutionAcceptance(
        identifier="comfyui-depthflow-nodes",
        baseline_fingerprint="old-baseline",
        diff_fingerprint="diff",
        proposed_fingerprint="proposed",
    )
    manager.preview_add_node_dependency_changes = lambda identifier: preview
    manager.add_node = lambda identifier, **kwargs: NodeInfo(name="should-not-install")

    with pytest.raises(CDDependencyPreviewStaleError):
        manager.apply_reviewed_dependency_changes(
            "comfyui-depthflow-nodes",
            acceptance,
        )
