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
