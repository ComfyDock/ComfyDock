"""Tests for ref_diff.py data models - RefDiff, NodeChange, ModelChange, etc.

These tests verify the dataclasses and their computed properties for representing
differences between two git refs.
"""


from comfygit_core.models.ref_diff import (
    DependencyChanges,
    DependencyConflict,
    ModelChange,
    NodeChange,
    NodeConflict,
    RefDiff,
    WorkflowChange,
    WorkflowConflict,
)


class TestNodeChange:
    """Test NodeChange dataclass."""

    def test_added_node(self):
        """Node added in target ref."""
        change = NodeChange(
            identifier="comfyui-manager",
            name="ComfyUI-Manager",
            change_type="added",
            target_version="1.0.0",
        )
        assert change.change_type == "added"
        assert change.base_version is None
        assert change.target_version == "1.0.0"
        assert change.conflict is None

    def test_removed_node(self):
        """Node removed in target ref."""
        change = NodeChange(
            identifier="old-node",
            name="Old Node",
            change_type="removed",
            base_version="0.5.0",
        )
        assert change.change_type == "removed"
        assert change.base_version == "0.5.0"
        assert change.target_version is None

    def test_version_changed_node(self):
        """Node version differs between refs."""
        change = NodeChange(
            identifier="comfyui-manager",
            name="ComfyUI-Manager",
            change_type="version_changed",
            base_version="1.0.0",
            target_version="2.0.0",
        )
        assert change.change_type == "version_changed"
        assert change.base_version == "1.0.0"
        assert change.target_version == "2.0.0"

    def test_development_node_flag(self):
        """Development nodes flagged correctly."""
        change = NodeChange(
            identifier="my-dev-node",
            name="My Dev Node",
            change_type="added",
            target_version="dev",
            is_development=True,
        )
        assert change.is_development is True


class TestModelChange:
    """Test ModelChange dataclass."""

    def test_model_added(self):
        """Model added in target ref."""
        change = ModelChange(
            hash="abc123def456",
            filename="sd15.safetensors",
            category="checkpoints",
            change_type="added",
            size=4_000_000_000,  # 4GB
            sources=["https://civitai.com/models/123"],
        )
        assert change.change_type == "added"
        assert change.size == 4_000_000_000
        assert len(change.sources) == 1

    def test_model_removed(self):
        """Model removed in target ref."""
        change = ModelChange(
            hash="abc123def456",
            filename="old_model.safetensors",
            category="loras",
            change_type="removed",
            size=100_000_000,  # 100MB
        )
        assert change.change_type == "removed"
        assert change.sources == []  # Default empty


class TestWorkflowChange:
    """Test WorkflowChange dataclass."""

    def test_workflow_added(self):
        """Workflow file added in target ref."""
        change = WorkflowChange(
            name="my_workflow",
            change_type="added",
        )
        assert change.change_type == "added"
        assert change.conflict is None

    def test_workflow_modified(self):
        """Workflow file modified in target ref."""
        change = WorkflowChange(
            name="my_workflow",
            change_type="modified",
        )
        assert change.change_type == "modified"

    def test_workflow_with_conflict(self):
        """Workflow with merge conflict attached."""
        conflict = WorkflowConflict(
            identifier="my_workflow",
            conflict_type="both_modified",
            base_hash="abc123",
            target_hash="def456",
        )
        change = WorkflowChange(
            name="my_workflow",
            change_type="modified",
            conflict=conflict,
        )
        assert change.conflict is not None
        assert change.conflict.resolution == "unresolved"


class TestDependencyChanges:
    """Test DependencyChanges dataclass."""

    def test_has_changes_true(self):
        """has_changes is True when any changes exist."""
        changes = DependencyChanges(
            added=[{"name": "numpy", "spec": ">=1.20"}],
        )
        assert changes.has_changes is True

    def test_has_changes_false(self):
        """has_changes is False when no changes."""
        changes = DependencyChanges()
        assert changes.has_changes is False

    def test_with_updated_deps(self):
        """Tracks updated dependencies."""
        changes = DependencyChanges(
            updated=[{"name": "torch", "old": ">=2.0", "new": ">=2.1"}],
        )
        assert changes.has_changes is True
        assert len(changes.updated) == 1


class TestConflicts:
    """Test conflict dataclasses."""

    def test_node_conflict_both_modified(self):
        """Node version conflict where both branches changed."""
        conflict = NodeConflict(
            identifier="comfyui-manager",
            conflict_type="both_modified",
            base_version="1.0.0",
            target_version="2.0.0",
        )
        assert conflict.category == "node"
        assert conflict.conflict_type == "both_modified"
        assert conflict.resolution == "unresolved"

    def test_node_conflict_delete_modify(self):
        """Node deleted in one branch, modified in other."""
        conflict = NodeConflict(
            identifier="old-node",
            conflict_type="delete_modify",
            base_version="1.0.0",
            target_deleted=True,
        )
        assert conflict.target_deleted is True
        assert conflict.base_deleted is False

    def test_workflow_conflict(self):
        """Workflow file conflict with content hashes."""
        conflict = WorkflowConflict(
            identifier="my_workflow",
            conflict_type="both_modified",
            base_hash="abc123456789",
            target_hash="def456789012",
        )
        assert conflict.category == "workflow"
        assert conflict.base_hash == "abc123456789"

    def test_dependency_conflict(self):
        """Dependency version conflict."""
        conflict = DependencyConflict(
            identifier="torch",
            conflict_type="both_modified",
            base_spec=">=2.0,<2.1",
            target_spec=">=2.1,<2.2",
        )
        assert conflict.category == "dependency"

    def test_conflict_resolution(self):
        """Conflict resolution can be set."""
        conflict = NodeConflict(
            identifier="test",
            conflict_type="both_modified",
            resolution="take_target",
        )
        assert conflict.resolution == "take_target"


class TestRefDiff:
    """Test RefDiff main dataclass."""

    def test_empty_diff(self):
        """Empty diff has no changes."""
        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base=None,
            node_changes=[],
            model_changes=[],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )
        assert diff.has_changes is False
        assert diff.has_conflicts is False

    def test_has_changes_with_nodes(self):
        """has_changes True when nodes changed."""
        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base=None,
            node_changes=[
                NodeChange(
                    identifier="test",
                    name="Test",
                    change_type="added",
                )
            ],
            model_changes=[],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )
        assert diff.has_changes is True

    def test_has_conflicts_with_unresolved(self):
        """has_conflicts True when unresolved conflicts exist."""
        conflict = NodeConflict(
            identifier="test",
            conflict_type="both_modified",
            resolution="unresolved",
        )
        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            node_changes=[
                NodeChange(
                    identifier="test",
                    name="Test",
                    change_type="version_changed",
                    conflict=conflict,
                )
            ],
            model_changes=[],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )
        assert diff.has_conflicts is True

    def test_has_conflicts_false_when_resolved(self):
        """has_conflicts False when all conflicts resolved."""
        conflict = NodeConflict(
            identifier="test",
            conflict_type="both_modified",
            resolution="take_target",  # Resolved
        )
        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            node_changes=[
                NodeChange(
                    identifier="test",
                    name="Test",
                    change_type="version_changed",
                    conflict=conflict,
                )
            ],
            model_changes=[],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )
        assert diff.has_conflicts is False

    def test_is_fast_forward(self):
        """is_fast_forward True when merge_base equals base_ref."""
        diff = RefDiff(
            base_ref="abc123",
            target_ref="origin/main",
            merge_base="abc123",  # Same as base_ref
            node_changes=[],
            model_changes=[],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )
        assert diff.is_fast_forward is True

    def test_not_fast_forward(self):
        """is_fast_forward False when branches have diverged."""
        diff = RefDiff(
            base_ref="abc123",
            target_ref="origin/main",
            merge_base="xyz789",  # Different - common ancestor
            node_changes=[],
            model_changes=[],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )
        assert diff.is_fast_forward is False

    def test_summary_counts(self):
        """summary() returns correct counts."""
        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base=None,
            node_changes=[
                NodeChange(identifier="a", name="A", change_type="added"),
                NodeChange(identifier="b", name="B", change_type="added"),
                NodeChange(identifier="c", name="C", change_type="removed"),
            ],
            model_changes=[
                ModelChange(
                    hash="abc",
                    filename="m1.safetensors",
                    category="checkpoints",
                    change_type="added",
                    size=4_000_000_000,
                ),
                ModelChange(
                    hash="def",
                    filename="m2.safetensors",
                    category="loras",
                    change_type="added",
                    size=100_000_000,
                ),
            ],
            workflow_changes=[
                WorkflowChange(name="wf1", change_type="added"),
                WorkflowChange(name="wf2", change_type="modified"),
            ],
            dependency_changes=DependencyChanges(),
        )
        summary = diff.summary()
        assert summary["nodes_added"] == 2
        assert summary["nodes_removed"] == 1
        assert summary["models_added"] == 2
        assert summary["models_added_size"] == 4_100_000_000
        assert summary["workflows_added"] == 1
        assert summary["workflows_modified"] == 1
        assert summary["conflicts"] == 0

    def test_all_conflicts_property(self):
        """all_conflicts collects conflicts from all sources."""
        node_conflict = NodeConflict(
            identifier="n1",
            conflict_type="both_modified",
        )
        workflow_conflict = WorkflowConflict(
            identifier="wf1",
            conflict_type="both_modified",
        )
        dep_conflict = DependencyConflict(
            identifier="torch",
            conflict_type="both_modified",
        )
        diff = RefDiff(
            base_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            node_changes=[
                NodeChange(
                    identifier="n1",
                    name="N1",
                    change_type="version_changed",
                    conflict=node_conflict,
                )
            ],
            model_changes=[],
            workflow_changes=[
                WorkflowChange(
                    name="wf1",
                    change_type="modified",
                    conflict=workflow_conflict,
                )
            ],
            dependency_changes=DependencyChanges(conflicts=[dep_conflict]),
        )
        all_conflicts = diff.all_conflicts
        assert len(all_conflicts) == 3
        assert node_conflict in all_conflicts
        assert workflow_conflict in all_conflicts
        assert dep_conflict in all_conflicts
