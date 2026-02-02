"""Tests for CLI preview diff display."""

import io
from contextlib import redirect_stdout

from comfygit_core.models.ref_diff import (
    DependencyChanges,
    ModelChange,
    NodeChange,
    RefDiff,
    WorkflowChange,
    WorkflowConflict,
)


class FakeEnvironmentCommands:
    """Minimal stub to test _display_diff_preview and _format_size."""

    def _format_size(self, size_bytes: int) -> str:
        """Format bytes as human-readable size."""
        for unit in ("B", "KB", "MB", "GB"):
            if abs(size_bytes) < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024  # type: ignore[assignment]
        return f"{size_bytes:.1f} TB"

    def _display_diff_preview(self, diff) -> None:
        """Display a RefDiff to the user."""
        from comfygit_core.models.ref_diff import RefDiff as RefDiffType

        if not isinstance(diff, RefDiffType):
            return

        summary = diff.summary()
        print(f"\nChanges from {diff.target_ref}:")
        print("-" * 40)

        # Nodes
        if diff.node_changes:
            print("\nNodes:")
            for node_change in diff.node_changes:
                symbol = {"added": "+", "removed": "-", "version_changed": "~"}[
                    node_change.change_type
                ]
                conflict_mark = " (CONFLICT)" if node_change.conflict else ""
                version_info = ""
                if node_change.change_type == "version_changed":
                    version_info = f" ({node_change.base_version} -> {node_change.target_version})"
                print(f"  {symbol} {node_change.name}{version_info}{conflict_mark}")

        # Models
        if diff.model_changes:
            print("\nModels:")
            for model_change in diff.model_changes:
                symbol = "+" if model_change.change_type == "added" else "-"
                size_str = self._format_size(model_change.size)
                print(f"  {symbol} {model_change.filename} ({size_str})")

        # Workflows
        if diff.workflow_changes:
            print("\nWorkflows:")
            for wf_change in diff.workflow_changes:
                symbol = {"added": "+", "deleted": "-", "modified": "~"}[
                    wf_change.change_type
                ]
                conflict_mark = " (CONFLICT)" if wf_change.conflict else ""
                print(f"  {symbol} {wf_change.name}.json{conflict_mark}")

        # Dependencies
        deps = diff.dependency_changes
        if deps.has_changes:
            print("\nDependencies:")
            for dep in deps.added:
                print(f"  + {dep.get('name', 'unknown')}")
            for dep in deps.removed:
                print(f"  - {dep.get('name', 'unknown')}")
            for dep in deps.updated:
                print(
                    f"  ~ {dep.get('name', 'unknown')} ({dep.get('old', '?')} -> {dep.get('new', '?')})"
                )

        # Summary
        print()
        summary_parts = []
        if summary["nodes_added"] or summary["nodes_removed"]:
            summary_parts.append(
                f"{summary['nodes_added']} nodes added, {summary['nodes_removed']} removed"
            )
        if summary["models_added"]:
            summary_parts.append(
                f"{summary['models_added']} models to download ({self._format_size(summary['models_added_size'])})"
            )
        if (
            summary["workflows_added"]
            or summary["workflows_modified"]
            or summary["workflows_deleted"]
        ):
            summary_parts.append(
                f"{summary['workflows_added']} workflows added, {summary['workflows_modified']} modified, {summary['workflows_deleted']} deleted"
            )
        if summary["conflicts"]:
            summary_parts.append(f"{summary['conflicts']} conflicts to resolve")

        if summary_parts:
            print("Summary:")
            for part in summary_parts:
                print(f"  {part}")


class TestFormatSize:
    """Tests for _format_size helper."""

    def test_bytes(self):
        cmd = FakeEnvironmentCommands()
        assert cmd._format_size(500) == "500.0 B"

    def test_kilobytes(self):
        cmd = FakeEnvironmentCommands()
        assert cmd._format_size(2048) == "2.0 KB"

    def test_megabytes(self):
        cmd = FakeEnvironmentCommands()
        assert cmd._format_size(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self):
        cmd = FakeEnvironmentCommands()
        assert cmd._format_size(3 * 1024 * 1024 * 1024) == "3.0 GB"


class TestDisplayDiffPreview:
    """Tests for _display_diff_preview."""

    def test_displays_node_additions(self):
        cmd = FakeEnvironmentCommands()
        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            node_changes=[
                NodeChange(
                    identifier="comfyui-manager",
                    name="ComfyUI-Manager",
                    change_type="added",
                    target_version="1.0.0",
                )
            ],
            model_changes=[],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )

        output = io.StringIO()
        with redirect_stdout(output):
            cmd._display_diff_preview(diff)

        result = output.getvalue()
        assert "origin/main" in result
        assert "+ ComfyUI-Manager" in result

    def test_displays_node_version_change(self):
        cmd = FakeEnvironmentCommands()
        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            node_changes=[
                NodeChange(
                    identifier="test-node",
                    name="TestNode",
                    change_type="version_changed",
                    base_version="1.0.0",
                    target_version="2.0.0",
                )
            ],
            model_changes=[],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )

        output = io.StringIO()
        with redirect_stdout(output):
            cmd._display_diff_preview(diff)

        result = output.getvalue()
        assert "~ TestNode (1.0.0 -> 2.0.0)" in result

    def test_displays_model_with_size(self):
        cmd = FakeEnvironmentCommands()
        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            node_changes=[],
            model_changes=[
                ModelChange(
                    hash="abc123",
                    filename="model.safetensors",
                    category="checkpoints",
                    change_type="added",
                    size=5 * 1024 * 1024 * 1024,  # 5 GB
                )
            ],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )

        output = io.StringIO()
        with redirect_stdout(output):
            cmd._display_diff_preview(diff)

        result = output.getvalue()
        assert "+ model.safetensors (5.0 GB)" in result

    def test_displays_workflow_conflict(self):
        cmd = FakeEnvironmentCommands()
        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            node_changes=[],
            model_changes=[],
            workflow_changes=[
                WorkflowChange(
                    name="my_workflow",
                    change_type="modified",
                    conflict=WorkflowConflict(
                        identifier="my_workflow",
                        conflict_type="both_modified",
                    ),
                )
            ],
            dependency_changes=DependencyChanges(),
        )

        output = io.StringIO()
        with redirect_stdout(output):
            cmd._display_diff_preview(diff)

        result = output.getvalue()
        assert "~ my_workflow.json (CONFLICT)" in result

    def test_displays_summary(self):
        cmd = FakeEnvironmentCommands()
        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            node_changes=[
                NodeChange(
                    identifier="node1", name="Node1", change_type="added"
                ),
                NodeChange(
                    identifier="node2", name="Node2", change_type="removed"
                ),
            ],
            model_changes=[
                ModelChange(
                    hash="abc123",
                    filename="model.safetensors",
                    category="checkpoints",
                    change_type="added",
                    size=1024 * 1024 * 100,  # 100 MB
                )
            ],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )

        output = io.StringIO()
        with redirect_stdout(output):
            cmd._display_diff_preview(diff)

        result = output.getvalue()
        assert "Summary:" in result
        assert "1 nodes added, 1 removed" in result
        assert "1 models to download" in result
