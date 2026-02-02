"""Tests for RefDiffAnalyzer - comparing two git refs for environment changes.

These tests verify the analyzer that produces RefDiff objects by comparing
pyproject.toml configs at different git refs.
"""

from unittest.mock import MagicMock, patch

import pytest
from comfygit_core.analyzers.ref_diff_analyzer import RefDiffAnalyzer
from comfygit_core.models.ref_diff import DependencyChanges, RefDiff


class TestRefDiffAnalyzerBasics:
    """Basic analyzer tests with mocked git operations."""

    @pytest.fixture
    def mock_git_show(self):
        """Mock git_show to return TOML content."""
        with patch("comfygit_core.analyzers.ref_diff_analyzer.git_show") as mock:
            yield mock

    @pytest.fixture
    def mock_run_command(self):
        """Mock run_command for git operations."""
        with patch("comfygit_core.analyzers.ref_diff_analyzer.run_command") as mock:
            yield mock

    def test_analyze_returns_ref_diff(self, mock_git_show, mock_run_command, tmp_path):
        """analyze() returns a RefDiff object."""
        # Setup mocks
        base_toml = """
[tool.comfygit.nodes]
"""
        target_toml = """
[tool.comfygit.nodes]
[tool.comfygit.nodes.comfyui-manager]
name = "ComfyUI-Manager"
version = "1.0.0"
"""
        mock_git_show.side_effect = [base_toml, target_toml]
        mock_run_command.return_value = MagicMock(returncode=1, stdout="")  # No merge base

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(base_ref="HEAD", target_ref="origin/main")

        assert isinstance(result, RefDiff)
        assert result.base_ref == "HEAD"
        assert result.target_ref == "origin/main"

    def test_detects_added_nodes(self, mock_git_show, mock_run_command, tmp_path):
        """Detects nodes added in target ref."""
        base_toml = """
[tool.comfygit.nodes]
"""
        target_toml = """
[tool.comfygit.nodes]
[tool.comfygit.nodes.comfyui-manager]
name = "ComfyUI-Manager"
version = "1.0.0"
"""
        mock_git_show.side_effect = [base_toml, target_toml]
        mock_run_command.return_value = MagicMock(returncode=1, stdout="")

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(base_ref="HEAD", target_ref="origin/main")

        assert len(result.node_changes) == 1
        assert result.node_changes[0].change_type == "added"
        assert result.node_changes[0].identifier == "comfyui-manager"

    def test_detects_removed_nodes(self, mock_git_show, mock_run_command, tmp_path):
        """Detects nodes removed in target ref."""
        base_toml = """
[tool.comfygit.nodes]
[tool.comfygit.nodes.old-node]
name = "Old Node"
version = "1.0.0"
"""
        target_toml = """
[tool.comfygit.nodes]
"""
        mock_git_show.side_effect = [base_toml, target_toml]
        mock_run_command.return_value = MagicMock(returncode=1, stdout="")

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(base_ref="HEAD", target_ref="origin/main")

        assert len(result.node_changes) == 1
        assert result.node_changes[0].change_type == "removed"

    def test_detects_version_changes(self, mock_git_show, mock_run_command, tmp_path):
        """Detects version changes in nodes."""
        base_toml = """
[tool.comfygit.nodes.comfyui-manager]
name = "ComfyUI-Manager"
version = "1.0.0"
"""
        target_toml = """
[tool.comfygit.nodes.comfyui-manager]
name = "ComfyUI-Manager"
version = "2.0.0"
"""
        mock_git_show.side_effect = [base_toml, target_toml]
        mock_run_command.return_value = MagicMock(returncode=1, stdout="")

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(base_ref="HEAD", target_ref="origin/main")

        assert len(result.node_changes) == 1
        assert result.node_changes[0].change_type == "version_changed"
        assert result.node_changes[0].base_version == "1.0.0"
        assert result.node_changes[0].target_version == "2.0.0"


class TestModelDiffing:
    """Test model section comparison."""

    @pytest.fixture
    def mock_git_show(self):
        with patch("comfygit_core.analyzers.ref_diff_analyzer.git_show") as mock:
            yield mock

    @pytest.fixture
    def mock_run_command(self):
        with patch("comfygit_core.analyzers.ref_diff_analyzer.run_command") as mock:
            yield mock

    def test_detects_added_models(self, mock_git_show, mock_run_command, tmp_path):
        """Detects models added in target ref."""
        base_toml = """
[tool.comfygit.models]
"""
        target_toml = """
[tool.comfygit.models]
[tool.comfygit.models.abc123def456]
filename = "sd15.safetensors"
category = "checkpoints"
size = 4000000000
sources = ["https://civitai.com/models/123"]
"""
        mock_git_show.side_effect = [base_toml, target_toml]
        mock_run_command.return_value = MagicMock(returncode=1, stdout="")

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(base_ref="HEAD", target_ref="origin/main")

        assert len(result.model_changes) == 1
        assert result.model_changes[0].change_type == "added"
        assert result.model_changes[0].hash == "abc123def456"
        assert result.model_changes[0].filename == "sd15.safetensors"
        assert result.model_changes[0].size == 4000000000

    def test_detects_removed_models(self, mock_git_show, mock_run_command, tmp_path):
        """Detects models removed in target ref."""
        base_toml = """
[tool.comfygit.models.abc123def456]
filename = "old_model.safetensors"
category = "loras"
size = 100000000
"""
        target_toml = """
[tool.comfygit.models]
"""
        mock_git_show.side_effect = [base_toml, target_toml]
        mock_run_command.return_value = MagicMock(returncode=1, stdout="")

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(base_ref="HEAD", target_ref="origin/main")

        assert len(result.model_changes) == 1
        assert result.model_changes[0].change_type == "removed"


class TestWorkflowDiffing:
    """Test workflow file comparison via git diff-tree."""

    @pytest.fixture
    def mock_git_show(self):
        with patch("comfygit_core.analyzers.ref_diff_analyzer.git_show") as mock:
            yield mock

    @pytest.fixture
    def mock_run_command(self):
        with patch("comfygit_core.analyzers.ref_diff_analyzer.run_command") as mock:
            yield mock

    def test_detects_added_workflows(self, mock_git_show, mock_run_command, tmp_path):
        """Detects workflow files added in target ref."""
        base_toml = "[tool.comfygit]"
        target_toml = "[tool.comfygit]"
        mock_git_show.side_effect = [base_toml, target_toml]

        # First call: merge-base (not found)
        # Second call: diff-tree (shows added workflow)
        mock_run_command.side_effect = [
            MagicMock(returncode=1, stdout=""),  # No merge base
            MagicMock(returncode=0, stdout="A\tworkflows/my_workflow.json\n"),
        ]

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(base_ref="HEAD", target_ref="origin/main")

        assert len(result.workflow_changes) == 1
        assert result.workflow_changes[0].change_type == "added"
        assert result.workflow_changes[0].name == "my_workflow"

    def test_detects_modified_workflows(self, mock_git_show, mock_run_command, tmp_path):
        """Detects workflow files modified in target ref."""
        base_toml = "[tool.comfygit]"
        target_toml = "[tool.comfygit]"
        mock_git_show.side_effect = [base_toml, target_toml]
        mock_run_command.side_effect = [
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=0, stdout="M\tworkflows/existing.json\n"),
        ]

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(base_ref="HEAD", target_ref="origin/main")

        assert len(result.workflow_changes) == 1
        assert result.workflow_changes[0].change_type == "modified"

    def test_detects_deleted_workflows(self, mock_git_show, mock_run_command, tmp_path):
        """Detects workflow files deleted in target ref."""
        base_toml = "[tool.comfygit]"
        target_toml = "[tool.comfygit]"
        mock_git_show.side_effect = [base_toml, target_toml]
        mock_run_command.side_effect = [
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=0, stdout="D\tworkflows/old.json\n"),
        ]

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(base_ref="HEAD", target_ref="origin/main")

        assert len(result.workflow_changes) == 1
        assert result.workflow_changes[0].change_type == "deleted"

    def test_detects_renamed_workflows(self, mock_git_show, mock_run_command, tmp_path):
        """Detects workflow renames (R status) as delete old + add new."""
        base_toml = "[tool.comfygit]"
        target_toml = "[tool.comfygit]"
        mock_git_show.side_effect = [base_toml, target_toml]
        mock_run_command.side_effect = [
            MagicMock(returncode=1, stdout=""),  # No merge base
            MagicMock(
                returncode=0,
                stdout="R100\tworkflows/old_name.json\tworkflows/new_name.json\n",
            ),
        ]

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(base_ref="HEAD", target_ref="origin/main")

        assert len(result.workflow_changes) == 2
        deleted = [c for c in result.workflow_changes if c.change_type == "deleted"]
        added = [c for c in result.workflow_changes if c.change_type == "added"]
        assert len(deleted) == 1
        assert deleted[0].name == "old_name"
        assert len(added) == 1
        assert added[0].name == "new_name"


class TestThreeWayConflictDetection:
    """Test three-way merge conflict detection."""

    @pytest.fixture
    def mock_git_show(self):
        with patch("comfygit_core.analyzers.ref_diff_analyzer.git_show") as mock:
            yield mock

    @pytest.fixture
    def mock_run_command(self):
        with patch("comfygit_core.analyzers.ref_diff_analyzer.run_command") as mock:
            yield mock

    def test_detects_node_conflict_both_modified(
        self, mock_git_show, mock_run_command, tmp_path
    ):
        """Detects conflict when both branches modified same node from ancestor."""
        ancestor_toml = """
[tool.comfygit.nodes.comfyui-manager]
name = "ComfyUI-Manager"
version = "1.0.0"
"""
        base_toml = """
[tool.comfygit.nodes.comfyui-manager]
name = "ComfyUI-Manager"
version = "1.1.0"
"""
        target_toml = """
[tool.comfygit.nodes.comfyui-manager]
name = "ComfyUI-Manager"
version = "1.2.0"
"""
        # git_show calls: base, target, ancestor (for conflict detection)
        mock_git_show.side_effect = [base_toml, target_toml, ancestor_toml]
        mock_run_command.side_effect = [
            MagicMock(returncode=0, stdout="abc123\n"),  # merge-base found
            MagicMock(returncode=0, stdout=""),  # diff-tree (no workflow changes)
        ]

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(
            base_ref="HEAD", target_ref="origin/main", detect_conflicts=True
        )

        assert len(result.node_changes) == 1
        assert result.node_changes[0].change_type == "version_changed"
        assert result.node_changes[0].conflict is not None
        assert result.node_changes[0].conflict.conflict_type == "both_modified"
        assert result.has_conflicts is True

    def test_no_conflict_when_fast_forward(
        self, mock_git_show, mock_run_command, tmp_path
    ):
        """No conflict when target is strictly ahead (fast-forward)."""
        base_toml = """
[tool.comfygit.nodes.comfyui-manager]
name = "ComfyUI-Manager"
version = "1.0.0"
"""
        target_toml = """
[tool.comfygit.nodes.comfyui-manager]
name = "ComfyUI-Manager"
version = "2.0.0"
"""
        mock_git_show.side_effect = [base_toml, target_toml]
        # merge-base returns HEAD (fast-forward case)
        mock_run_command.side_effect = [
            MagicMock(returncode=0, stdout="HEAD\n"),  # merge-base == base_ref
            MagicMock(returncode=0, stdout=""),
        ]

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(
            base_ref="HEAD", target_ref="origin/main", detect_conflicts=True
        )

        # Version changed but no conflict (only target changed from ancestor)
        assert len(result.node_changes) == 1
        # In fast-forward, merge_base == base_ref, so ancestor == base
        # Only target changed, so no conflict
        assert result.node_changes[0].conflict is None
        assert result.is_fast_forward is True

    def test_conflict_detection_disabled(
        self, mock_git_show, mock_run_command, tmp_path
    ):
        """No conflict detection when disabled."""
        base_toml = """
[tool.comfygit.nodes.comfyui-manager]
name = "ComfyUI-Manager"
version = "1.0.0"
"""
        target_toml = """
[tool.comfygit.nodes.comfyui-manager]
name = "ComfyUI-Manager"
version = "2.0.0"
"""
        mock_git_show.side_effect = [base_toml, target_toml]
        mock_run_command.side_effect = [
            MagicMock(returncode=0, stdout=""),  # diff-tree
        ]

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(
            base_ref="HEAD",
            target_ref="origin/main",
            detect_conflicts=False,  # Disable conflict detection
        )

        assert result.merge_base is None
        assert result.node_changes[0].conflict is None

    def test_detects_add_add_workflow_conflict(
        self, mock_git_show, mock_run_command, tmp_path
    ):
        """Detects add/add conflict when both branches independently created same workflow.

        If diff-tree shows "M" (file in both branches) but file doesn't exist
        at the merge_base ancestor, both branches added it independently.
        """
        base_toml = "[tool.comfygit]"
        target_toml = "[tool.comfygit]"
        ancestor_toml = "[tool.comfygit]"
        # git_show calls:
        # 1. base pyproject.toml
        # 2. target pyproject.toml
        # 3. ancestor pyproject.toml (merge_base != base_ref)
        # 4. _check_workflow_conflict: ancestor workflow -> raises (doesn't exist)
        # 5. _check_workflow_conflict: base workflow content
        # 6. _check_workflow_conflict: target workflow content
        mock_git_show.side_effect = [
            base_toml,
            target_toml,
            ancestor_toml,
            ValueError("file not found at ancestor"),  # ancestor doesn't have workflow
            '{"base": "version"}',  # base has it
            '{"target": "version"}',  # target has it (different content)
        ]
        mock_run_command.side_effect = [
            MagicMock(returncode=0, stdout="merge_base_abc\n"),  # merge-base found
            MagicMock(
                returncode=0,
                stdout="M\tworkflows/shared.json\n",
            ),  # diff-tree shows modified
        ]

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(
            base_ref="HEAD", target_ref="origin/main", detect_conflicts=True
        )

        assert len(result.workflow_changes) == 1
        assert result.workflow_changes[0].change_type == "modified"
        assert result.workflow_changes[0].conflict is not None
        assert result.workflow_changes[0].conflict.conflict_type == "both_modified"

    def test_detects_delete_modify_workflow_conflict(
        self, mock_git_show, mock_run_command, tmp_path
    ):
        """Detects conflict when target deletes a workflow that base modified.

        If diff-tree shows "D" (deleted in target) but the file was modified
        in base since the ancestor, that's a delete/modify conflict.
        """
        base_toml = "[tool.comfygit]"
        target_toml = "[tool.comfygit]"
        ancestor_toml = "[tool.comfygit]"
        # git_show calls:
        # 1. base pyproject.toml
        # 2. target pyproject.toml
        # 3. ancestor pyproject.toml (merge_base != base_ref)
        # 4. delete/modify check: ancestor workflow content
        # 5. delete/modify check: base workflow content (modified since ancestor)
        mock_git_show.side_effect = [
            base_toml,
            target_toml,
            ancestor_toml,
            '{"original": "content"}',  # ancestor has it
            '{"modified": "content"}',  # base modified it
        ]
        mock_run_command.side_effect = [
            MagicMock(returncode=0, stdout="merge_base_abc\n"),  # merge-base found
            MagicMock(
                returncode=0,
                stdout="D\tworkflows/deleted_wf.json\n",
            ),  # diff-tree shows deleted in target
        ]

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(
            base_ref="HEAD", target_ref="origin/main", detect_conflicts=True
        )

        assert len(result.workflow_changes) == 1
        assert result.workflow_changes[0].change_type == "deleted"
        assert result.workflow_changes[0].conflict is not None
        assert result.workflow_changes[0].conflict.conflict_type == "delete_modify"


class TestDependencyDiffing:
    """Test Python dependency comparison."""

    @pytest.fixture
    def mock_git_show(self):
        with patch("comfygit_core.analyzers.ref_diff_analyzer.git_show") as mock:
            yield mock

    @pytest.fixture
    def mock_run_command(self):
        with patch("comfygit_core.analyzers.ref_diff_analyzer.run_command") as mock:
            yield mock

    def test_detects_added_dependencies(
        self, mock_git_show, mock_run_command, tmp_path
    ):
        """Detects dependencies added in target ref."""
        base_toml = """
[project]
dependencies = []
"""
        target_toml = """
[project]
dependencies = ["numpy>=1.20", "torch>=2.0"]
"""
        mock_git_show.side_effect = [base_toml, target_toml]
        mock_run_command.return_value = MagicMock(returncode=1, stdout="")

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(base_ref="HEAD", target_ref="origin/main")

        assert result.dependency_changes.has_changes is True
        assert len(result.dependency_changes.added) == 2

    def test_detects_constraint_changes(
        self, mock_git_show, mock_run_command, tmp_path
    ):
        """Detects UV constraint dependency changes."""
        base_toml = """
[tool.uv]
constraint-dependencies = []
"""
        target_toml = """
[tool.uv]
constraint-dependencies = ["numpy<2.0"]
"""
        mock_git_show.side_effect = [base_toml, target_toml]
        mock_run_command.return_value = MagicMock(returncode=1, stdout="")

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(base_ref="HEAD", target_ref="origin/main")

        assert "numpy<2.0" in result.dependency_changes.constraints_added


class TestMergeBaseDetection:
    """Test merge-base detection for three-way comparison."""

    @pytest.fixture
    def mock_git_show(self):
        with patch("comfygit_core.analyzers.ref_diff_analyzer.git_show") as mock:
            yield mock

    @pytest.fixture
    def mock_run_command(self):
        with patch("comfygit_core.analyzers.ref_diff_analyzer.run_command") as mock:
            yield mock

    def test_finds_merge_base(self, mock_git_show, mock_run_command, tmp_path):
        """Finds merge-base between two refs."""
        base_toml = "[tool.comfygit]"
        target_toml = "[tool.comfygit]"
        ancestor_toml = "[tool.comfygit]"
        mock_git_show.side_effect = [base_toml, target_toml, ancestor_toml]
        mock_run_command.side_effect = [
            MagicMock(returncode=0, stdout="abc123def456\n"),  # merge-base
            MagicMock(returncode=0, stdout=""),  # diff-tree
        ]

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(
            base_ref="HEAD", target_ref="origin/main", detect_conflicts=True
        )

        assert result.merge_base == "abc123def456"

    def test_handles_no_merge_base(self, mock_git_show, mock_run_command, tmp_path):
        """Handles case when refs have no common ancestor."""
        base_toml = "[tool.comfygit]"
        target_toml = "[tool.comfygit]"
        mock_git_show.side_effect = [base_toml, target_toml]
        mock_run_command.side_effect = [
            MagicMock(returncode=1, stdout=""),  # No merge-base
            MagicMock(returncode=0, stdout=""),
        ]

        analyzer = RefDiffAnalyzer(tmp_path)
        result = analyzer.analyze(
            base_ref="HEAD", target_ref="origin/main", detect_conflicts=True
        )

        assert result.merge_base is None
        # Should still work, just no conflict detection
        assert result.has_conflicts is False


class TestRefDiffMergeStateProperties:
    """Test RefDiff properties for determining merge state.

    BUG: The CLI incorrectly says "already merged" when has_changes=False,
    but this ignores git commit state. These tests verify the properties
    needed to correctly distinguish merge states.
    """

    def test_is_already_merged_when_target_is_ancestor(self):
        """Target being ancestor of base means it's already merged."""
        # Scenario: main@abc123, feature@def456, merge_base=def456
        # This means feature is an ancestor of main (already merged)
        diff = RefDiff(
            base_ref="abc123",
            target_ref="def456",
            merge_base="def456",  # merge_base == target_ref
            node_changes=[],
            model_changes=[],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )

        assert diff.is_already_merged is True
        assert diff.is_fast_forward is False
        assert diff.has_changes is False

    def test_is_fast_forward_when_base_is_ancestor(self):
        """Base being ancestor of target means fast-forward possible."""
        # Scenario: test@abc123, main@def456, merge_base=abc123
        # This means test is ancestor of main (main has commits to bring in)
        diff = RefDiff(
            base_ref="abc123",
            target_ref="def456",
            merge_base="abc123",  # merge_base == base_ref
            node_changes=[],
            model_changes=[],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )

        assert diff.is_already_merged is False
        assert diff.is_fast_forward is True
        assert diff.has_changes is False

    def test_diverged_with_no_changes(self):
        """Branches diverged but no ComfyGit config changes."""
        # Scenario: both branches have commits since merge_base, but
        # neither touched pyproject.toml/workflows
        diff = RefDiff(
            base_ref="abc123",
            target_ref="def456",
            merge_base="ghi789",  # Neither matches
            node_changes=[],
            model_changes=[],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )

        assert diff.is_already_merged is False
        assert diff.is_fast_forward is False
        assert diff.has_changes is False

    def test_same_commit(self):
        """Both refs point to same commit."""
        diff = RefDiff(
            base_ref="abc123",
            target_ref="abc123",
            merge_base="abc123",
            node_changes=[],
            model_changes=[],
            workflow_changes=[],
            dependency_changes=DependencyChanges(),
        )

        # Same commit is technically "already merged"
        assert diff.is_already_merged is True
        assert diff.has_changes is False
