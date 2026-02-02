"""Analyzer for comparing two git refs to produce a unified diff.

Used by preview_pull() and preview_merge() to show users what will change
before applying git operations.
"""

import hashlib
from pathlib import Path

import tomlkit

from ..logging.logging_config import get_logger
from ..models.ref_diff import (
    DependencyChanges,
    ModelChange,
    NodeChange,
    NodeConflict,
    RefDiff,
    WorkflowChange,
    WorkflowConflict,
)
from ..utils.common import run_command
from ..utils.dependency_parser import compare_dependency_sets, extract_all_dependencies
from ..utils.git import git_show
from .config_comparison import extract_models_section, extract_nodes_section, flatten_nodes

logger = get_logger(__name__)


class RefDiffAnalyzer:
    """Analyze differences between two git refs."""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    def analyze(
        self,
        base_ref: str = "HEAD",
        target_ref: str = "origin/main",
        detect_conflicts: bool = True,
    ) -> RefDiff:
        """Compare two refs and return all changes.

        Args:
            base_ref: Reference point (usually HEAD)
            target_ref: Target to compare against
            detect_conflicts: If True, perform three-way merge analysis

        Returns:
            RefDiff with all changes and conflicts
        """
        # Get configs at both refs
        base_config = self._get_config_at_ref(base_ref)
        target_config = self._get_config_at_ref(target_ref)

        # Find merge base for conflict detection
        merge_base = None
        ancestor_config = None
        if detect_conflicts:
            merge_base = self._get_merge_base(base_ref, target_ref)
            if merge_base and merge_base != base_ref:
                ancestor_config = self._get_config_at_ref(merge_base)

        # Diff each category
        node_changes = self._diff_nodes(base_config, target_config, ancestor_config)
        model_changes = self._diff_models(base_config, target_config)
        workflow_changes = self._diff_workflows(base_ref, target_ref, merge_base)
        dependency_changes = self._diff_dependencies(
            base_config, target_config, ancestor_config
        )

        return RefDiff(
            base_ref=base_ref,
            target_ref=target_ref,
            merge_base=merge_base,
            node_changes=node_changes,
            model_changes=model_changes,
            workflow_changes=workflow_changes,
            dependency_changes=dependency_changes,
        )

    def _get_config_at_ref(self, ref: str) -> dict:
        """Load pyproject.toml from a git ref."""
        content = git_show(self.repo_path, ref, Path("pyproject.toml"), is_text=True)
        return tomlkit.loads(content) if content else {}

    def _get_merge_base(self, ref1: str, ref2: str) -> str | None:
        """Find common ancestor of two refs."""
        result = run_command(
            ["git", "merge-base", ref1, ref2],
            cwd=self.repo_path,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def _diff_nodes(
        self,
        base_config: dict,
        target_config: dict,
        ancestor_config: dict | None,
    ) -> list[NodeChange]:
        """Compare node sections between configs."""
        base_nodes = flatten_nodes(extract_nodes_section(base_config))
        target_nodes = flatten_nodes(extract_nodes_section(target_config))
        ancestor_nodes = (
            flatten_nodes(extract_nodes_section(ancestor_config))
            if ancestor_config
            else {}
        )

        changes = []
        all_keys = set(base_nodes.keys()) | set(target_nodes.keys())

        for key in all_keys:
            in_base = key in base_nodes
            in_target = key in target_nodes
            in_ancestor = key in ancestor_nodes

            if in_target and not in_base:
                # Added in target
                changes.append(
                    NodeChange(
                        identifier=key,
                        name=target_nodes[key].get("name", key),
                        change_type="added",
                        target_version=target_nodes[key].get("version"),
                        is_development=target_nodes[key].get("version") == "dev",
                    )
                )
            elif in_base and not in_target:
                # Removed in target
                conflict = None
                if ancestor_config and in_ancestor:
                    # Check if base modified it (delete-modify conflict)
                    if base_nodes[key] != ancestor_nodes[key]:
                        conflict = NodeConflict(
                            identifier=key,
                            conflict_type="delete_modify",
                            base_version=base_nodes[key].get("version"),
                            target_deleted=True,
                        )
                changes.append(
                    NodeChange(
                        identifier=key,
                        name=base_nodes[key].get("name", key),
                        change_type="removed",
                        base_version=base_nodes[key].get("version"),
                        is_development=base_nodes[key].get("version") == "dev",
                        conflict=conflict,
                    )
                )
            elif in_base and in_target:
                # Both have it - check for version changes
                base_ver = base_nodes[key].get("version")
                target_ver = target_nodes[key].get("version")
                if base_ver != target_ver:
                    conflict = None
                    if ancestor_config and in_ancestor:
                        ancestor_ver = ancestor_nodes[key].get("version")
                        # Conflict if both changed from ancestor
                        if base_ver != ancestor_ver and target_ver != ancestor_ver:
                            conflict = NodeConflict(
                                identifier=key,
                                conflict_type="both_modified",
                                base_version=base_ver,
                                target_version=target_ver,
                            )
                    changes.append(
                        NodeChange(
                            identifier=key,
                            name=base_nodes[key].get("name", key),
                            change_type="version_changed",
                            base_version=base_ver,
                            target_version=target_ver,
                            conflict=conflict,
                        )
                    )

        return changes

    def _diff_models(
        self, base_config: dict, target_config: dict
    ) -> list[ModelChange]:
        """Compare global model manifests."""
        base_models = extract_models_section(base_config)
        target_models = extract_models_section(target_config)

        changes = []

        # Models added in target
        for hash_key in set(target_models.keys()) - set(base_models.keys()):
            data = target_models[hash_key]
            changes.append(
                ModelChange(
                    hash=hash_key,
                    filename=data.get("filename", "unknown"),
                    category=data.get("category", "unknown"),
                    change_type="added",
                    size=data.get("size", 0),
                    sources=data.get("sources", []),
                )
            )

        # Models removed in target
        for hash_key in set(base_models.keys()) - set(target_models.keys()):
            data = base_models[hash_key]
            changes.append(
                ModelChange(
                    hash=hash_key,
                    filename=data.get("filename", "unknown"),
                    category=data.get("category", "unknown"),
                    change_type="removed",
                    size=data.get("size", 0),
                )
            )

        return changes

    def _diff_workflows(
        self,
        base_ref: str,
        target_ref: str,
        merge_base: str | None,
    ) -> list[WorkflowChange]:
        """Compare workflow files between refs using git."""
        result = run_command(
            [
                "git",
                "diff-tree",
                "-r",
                "-M",
                "--name-status",
                base_ref,
                target_ref,
                "--",
                "workflows/",
            ],
            cwd=self.repo_path,
            check=False,
        )

        if result.returncode != 0 or not result.stdout.strip():
            return []

        changes = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            status = parts[0]

            # Renames: R100\told_path\tnew_path → delete old + add new
            if status.startswith("R"):
                old_path, new_path = parts[1], parts[2]
                if old_path.endswith(".json"):
                    changes.append(
                        WorkflowChange(name=Path(old_path).stem, change_type="deleted")
                    )
                if new_path.endswith(".json"):
                    changes.append(
                        WorkflowChange(name=Path(new_path).stem, change_type="added")
                    )
                continue

            filepath = parts[-1]
            if not filepath.endswith(".json"):
                continue

            name = Path(filepath).stem

            if status == "A":
                change_type = "added"
            elif status == "D":
                change_type = "deleted"
            elif status.startswith("M"):
                change_type = "modified"
            else:
                continue

            # Check for conflicts
            conflict = None
            if change_type == "modified" and merge_base:
                conflict = self._check_workflow_conflict(
                    filepath, base_ref, target_ref, merge_base
                )
            elif change_type == "deleted" and merge_base:
                conflict = self._check_delete_modify_conflict(
                    filepath, base_ref, merge_base
                )

            changes.append(
                WorkflowChange(
                    name=name,
                    change_type=change_type,
                    conflict=conflict,
                )
            )

        return changes

    def _check_workflow_conflict(
        self,
        filepath: str,
        base_ref: str,
        target_ref: str,
        merge_base: str,
    ) -> WorkflowConflict | None:
        """Check if workflow has conflict (modified in both branches)."""
        try:
            ancestor_content = git_show(
                self.repo_path, merge_base, Path(filepath), is_text=True
            )
        except (ValueError, OSError):
            # No ancestor — both branches added the file independently (add/add)
            try:
                base_content = git_show(
                    self.repo_path, base_ref, Path(filepath), is_text=True
                )
                target_content = git_show(
                    self.repo_path, target_ref, Path(filepath), is_text=True
                )
            except (ValueError, OSError):
                return None
            if base_content != target_content:
                return WorkflowConflict(
                    identifier=Path(filepath).stem,
                    conflict_type="both_modified",
                    base_hash=hashlib.sha256(base_content.encode()).hexdigest()[:12],
                    target_hash=hashlib.sha256(target_content.encode()).hexdigest()[:12],
                )
            return None

        try:
            base_content = git_show(self.repo_path, base_ref, Path(filepath), is_text=True)
            target_content = git_show(
                self.repo_path, target_ref, Path(filepath), is_text=True
            )
        except (ValueError, OSError):
            return None

        # If both differ from ancestor and from each other, it's a conflict
        if (
            base_content != ancestor_content
            and target_content != ancestor_content
            and base_content != target_content
        ):
            return WorkflowConflict(
                identifier=Path(filepath).stem,
                conflict_type="both_modified",
                base_hash=hashlib.sha256(base_content.encode()).hexdigest()[:12],
                target_hash=hashlib.sha256(target_content.encode()).hexdigest()[:12],
            )

        return None

    def _check_delete_modify_conflict(
        self,
        filepath: str,
        base_ref: str,
        merge_base: str,
    ) -> WorkflowConflict | None:
        """Check if deleted workflow was modified in base (delete/modify conflict).

        Called when target deleted a file. If base modified it since the
        ancestor, that's a conflict.
        """
        try:
            ancestor_content = git_show(
                self.repo_path, merge_base, Path(filepath), is_text=True
            )
            base_content = git_show(
                self.repo_path, base_ref, Path(filepath), is_text=True
            )
        except (ValueError, OSError):
            return None

        if base_content != ancestor_content:
            return WorkflowConflict(
                identifier=Path(filepath).stem,
                conflict_type="delete_modify",
                base_hash=hashlib.sha256(base_content.encode()).hexdigest()[:12],
                target_hash=None,
            )

        return None

    def _diff_dependencies(
        self,
        base_config: dict,
        target_config: dict,
        ancestor_config: dict | None,
    ) -> DependencyChanges:
        """Compare Python dependencies."""
        base_deps = extract_all_dependencies(base_config)
        target_deps = extract_all_dependencies(target_config)

        changes = compare_dependency_sets(base_deps, target_deps)

        # Extract constraints
        base_constraints = set(
            base_config.get("tool", {}).get("uv", {}).get("constraint-dependencies", [])
        )
        target_constraints = set(
            target_config.get("tool", {}).get("uv", {}).get("constraint-dependencies", [])
        )

        return DependencyChanges(
            added=changes.get("added", []),
            removed=changes.get("removed", []),
            updated=changes.get("updated", []),
            constraints_added=list(target_constraints - base_constraints),
            constraints_removed=list(base_constraints - target_constraints),
        )
