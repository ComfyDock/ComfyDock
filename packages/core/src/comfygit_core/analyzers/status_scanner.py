# core/status_scanner.py
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.version import InvalidVersion, Version

from comfygit_core.constants import CUSTOM_NODES_BLACKLIST

from ..logging.logging_config import get_logger
from ..models.environment import (
    EnvironmentComparison,
    EnvironmentState,
    NodeState,
    PackageSyncStatus,
)
from ..models.exceptions import UVCommandError
from .node_git_analyzer import get_node_git_info

if TYPE_CHECKING:
    from ..managers.pyproject_manager import PyprojectManager
    from ..managers.pytorch_backend_manager import PyTorchBackendManager
    from ..managers.uv_project_manager import UVProjectManager

logger = get_logger(__name__)


def _versions_match(actual: str | None, expected: str | None) -> bool:
    """Compare node versions using package-version semantics when possible."""
    if actual == expected:
        return True

    if not actual or not expected:
        return False

    try:
        return Version(actual) == Version(expected)
    except InvalidVersion:
        return False


class StatusScanner:
    """Scans environment to get current state."""

    def __init__(
        self,
        uv: UVProjectManager,
        pyproject: PyprojectManager,
        venv_path: Path,
        comfyui_path: Path,
        pytorch_manager: PyTorchBackendManager | None = None,
    ):
        self._uv = uv
        self._pyproject = pyproject
        self._venv_path = venv_path
        self._comfyui_path = comfyui_path
        self._pytorch_manager = pytorch_manager

    def get_full_comparison(self) -> EnvironmentComparison:
        """Get complete environment comparison with all details.

        Args:
            comfyui_path: Path to ComfyUI directory
            venv_path: Path to virtual environment
            uv: UV interface for package operations
            pyproject: PyprojectManager instance

        Returns:
            Complete environment comparison
        """
        # Scan current and expected states
        current = self.scan_environment()
        expected = self.scan_manifest()

        # Get basic comparison
        comparison = self.compare_states(current, expected)

        # Skip package sync check for performance (100-500ms saved)
        # Rationale:
        #   - Users rarely manually modify .venv/
        #   - Operations like 'run', 'repair', 'node add' auto-sync before executing
        #   - Status is high-frequency with workflow caching - needs to be fast
        #   - Package drift self-corrects on next sync operation
        # If thorough check needed, use 'cg repair --dry-run' (future)
        # TODO: Add package sync status
        # package_status = self.check_packages_sync()
        comparison.packages_in_sync = True #package_status.in_sync
        comparison.package_sync_message = "" #package_status.message

        return comparison

    def scan_environment(self) -> EnvironmentState:
        """Scan the environment for its current state.

        Args:
            comfyui_path: Path to ComfyUI directory
            venv_path: Path to virtual environment
            uv: UV interface for package operations

        Returns:
            Current environment state
        """
        # Scan custom nodes
        custom_nodes = self._scan_custom_nodes()

        # Get installed packages
        # packages = self._scan_packages()

        # Get Python version
        # python_version = self._get_python_version()

        return EnvironmentState(
            custom_nodes=custom_nodes,
            packages=None,#packages,
            python_version=None,#python_version
        )

    def _scan_custom_nodes(self) -> dict[str, NodeState]:
        """Scan the custom_nodes directory."""
        nodes = {}
        custom_nodes_path = self._comfyui_path / "custom_nodes"

        if not custom_nodes_path.exists():
            logger.debug("custom_nodes directory not found")
            return nodes

        # Skip these directories (blacklisted paths only - manager is now per-environment)
        skip_dirs = CUSTOM_NODES_BLACKLIST

        # TODO: Support .comfygit_ignore
        for node_dir in custom_nodes_path.iterdir():
            if not node_dir.is_dir() or node_dir.name in skip_dirs:
                continue

            # Skip hidden directories
            if node_dir.name.startswith("."):
                continue

            # Skip timestamped backup disabled nodes (e.g., MyNode.1700000000.disabled)
            # These are internal implementation details
            if node_dir.name.endswith(".disabled"):
                parts = node_dir.name[:-9].split(".")  # Remove .disabled suffix
                if len(parts) > 1 and parts[-1].isdigit():
                    continue  # Skip timestamped backups

            # Determine if disabled and extract base name
            is_disabled = node_dir.name.endswith(".disabled")
            base_name = node_dir.name[:-9] if is_disabled else node_dir.name

            # Skip if we already have an enabled version (enabled takes precedence)
            if base_name in nodes and not nodes[base_name].disabled:
                continue

            try:
                node_state = self._scan_single_node(node_dir)
                node_state.name = base_name  # Use normalized name
                node_state.disabled = is_disabled
                nodes[base_name] = node_state
            except Exception as e:
                logger.debug(f"Error scanning node {node_dir.name}: {e}")
                # Still record it as present but with minimal info
                nodes[base_name] = NodeState(
                    name=base_name,
                    path=node_dir,
                    disabled=is_disabled,
                )

        return nodes

    def _scan_single_node(self, node_dir: Path) -> NodeState:
        """Scan a single custom node directory."""
        state = NodeState(name=node_dir.name, path=node_dir)

        # Check if is disabled (has .disabled appended to dir name)
        if node_dir.name.endswith(".disabled"):
            state.disabled = True

        # Check for git info
        if (node_dir / ".git").exists():
            git_info = get_node_git_info(node_dir)
            if git_info:
                state.git_commit = git_info.commit
                state.git_branch = git_info.branch
                state.version = git_info.tag  # Use git tag as version
                state.is_dirty = git_info.is_dirty

        # If no version from git, check pyproject.toml
        if not state.version:
            pyproject_path = node_dir / "pyproject.toml"
            if pyproject_path.exists():
                try:
                    import tomlkit

                    with open(pyproject_path, encoding='utf-8') as f:
                        data = tomlkit.load(f)

                    # Try different locations for version
                    project_section = data.get("project")
                    if project_section and isinstance(project_section, dict):
                        version = project_section.get("version")
                        if isinstance(version, str):
                            state.version = version

                    if not state.version:
                        tool_section = data.get("tool")
                        if tool_section and isinstance(tool_section, dict):
                            poetry_section = tool_section.get("poetry")
                            if poetry_section and isinstance(poetry_section, dict):
                                version = poetry_section.get("version")
                                if isinstance(version, str):
                                    state.version = version
                except Exception:
                    pass  # Ignore parse errors

        return state

    def _scan_packages(self) -> dict[str, str]:
        """Get installed packages using UV."""
        packages = {}

        python_path = self._uv.python_executable

        if not python_path.exists():
            logger.warning(f"Python not found in venv: {self._venv_path}")
            return packages

        # TODO: Make this more robust
        try:
            output = self._uv.freeze_packages(python=python_path)
            if output:
                for line in output.strip().split("\n"):
                    if line and "==" in line and not line.startswith("#"):
                        if line.startswith("-e "):
                            # Skip editable installs for now
                            continue
                        name, version = line.split("==", 1)
                        packages[name.strip().lower()] = version.strip()
        except Exception as e:
            logger.warning(f"Failed to get packages: {e}")

        return packages

    def _get_python_version(self) -> str:
        """Get Python version from venv."""
        python_path = self._uv.python_executable

        if not python_path.exists():
            return "unknown"

        try:
            result = subprocess.run(
                [str(python_path), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Parse "Python 3.11.5" -> "3.11.5"
                return result.stdout.strip().split()[-1]
        except Exception as e:
            logger.debug(f"Failed to get Python version: {e}")

        return "unknown"

    def scan_manifest(self) -> EnvironmentState:
        """Scan expected state from pyproject.toml.

        Args:
            pyproject: PyprojectManager instance

        Returns:
            Expected environment state from configuration
        """
        self._pyproject.load()

        # Get expected custom nodes from pyproject
        node_infos = self._pyproject.nodes.get_existing()

        expected_nodes = {}
        for _, node_info in node_infos.items():
            expected_nodes[node_info.name] = NodeState(
                name=node_info.name,
                path=Path("custom_nodes") / node_info.name,
                version=node_info.version,
                source=node_info.source,
            )

        # # Get expected packages from dependency groups
        # expected_packages = {}
        # dependencies = config.get("dependency-groups", {})

        # for _, deps in dependencies.items():
        #     for dep in deps:
        #         if isinstance(dep, str):
        #             # Parse package spec like "torch>=2.0.0"
        #             if "==" in dep:
        #                 name, version = dep.split("==", 1)
        #                 expected_packages[name.strip().lower()] = version.strip()
        #             elif ">=" in dep or "<=" in dep or ">" in dep or "<" in dep:
        #                 # For now, just record that the package should be present
        #                 name = dep.split(">")[0].split("<")[0].split("=")[0]
        #                 expected_packages[name.strip().lower()] = "*"
        #             else:
        #                 expected_packages[dep.strip().lower()] = "*"

        # # Get Python version from project settings
        # python_version = (
        #     config.get("project", {}).get("requires-python", "").strip(">=")
        # )
        # if not python_version:
        #     python_version = "3.11"  # Default

        return EnvironmentState(
            custom_nodes=expected_nodes,
            packages=None,#expected_packages,
            python_version=None,#python_version,
        )

    def compare_states(
        self, current: EnvironmentState, expected: EnvironmentState
    ) -> EnvironmentComparison:
        """Compare current and expected environment states.

        Dev nodes are reported separately (informational only, not sync errors).

        Args:
            current: Current environment state
            expected: Expected environment state

        Returns:
            Comparison results
        """
        comparison = EnvironmentComparison()

        # Compare custom nodes
        current_nodes = set(current.custom_nodes.keys())
        expected_nodes = set(expected.custom_nodes.keys())

        # Identify disabled nodes (in both current and expected, but disabled on disk)
        disabled_nodes = []
        for name in current_nodes & expected_nodes:
            if current.custom_nodes[name].disabled:
                disabled_nodes.append(name)
        comparison.disabled_nodes = disabled_nodes

        # Compute basic missing/extra first
        raw_missing_nodes = list(expected_nodes - current_nodes)
        raw_extra_nodes = list(current_nodes - expected_nodes)

        # Separate dev nodes from regular nodes for proper reporting
        # Missing dev nodes go to dev_nodes_missing, not missing_nodes
        for name in raw_missing_nodes[:]:  # Iterate copy to allow removal
            if name in expected.custom_nodes and expected.custom_nodes[name].source == 'development':
                comparison.dev_nodes_missing.append(name)
                raw_missing_nodes.remove(name)

        # Extra nodes with git repos go to dev_nodes_untracked, not extra_nodes
        for name in raw_extra_nodes[:]:  # Iterate copy to allow removal
            node_path = self._comfyui_path / 'custom_nodes' / name
            if (node_path / '.git').exists():
                comparison.dev_nodes_untracked.append(name)
                raw_extra_nodes.remove(name)

        comparison.missing_nodes = raw_missing_nodes
        comparison.extra_nodes = raw_extra_nodes

        # Check version mismatches (skip development nodes)
        for name in current_nodes & expected_nodes:
            current_node = current.custom_nodes[name]
            expected_node = expected.custom_nodes[name]

            # Skip version comparison for development nodes - they're user-managed
            if expected_node.source == 'development':
                continue

            actual_version = current_node.version
            if expected_node.source == "git" and current_node.git_commit:
                actual_version = current_node.git_commit

            if expected_node.version and not _versions_match(actual_version, expected_node.version):
                comparison.version_mismatches.append(
                    {
                        "name": name,
                        "expected": expected_node.version,
                        "actual": actual_version,
                    }
                )

        # Detect potential dev node renames (simple heuristic)
        # Note: Now we check dev_nodes_missing instead of missing_nodes for dev nodes
        if (comparison.missing_nodes or comparison.dev_nodes_missing) and (comparison.extra_nodes or comparison.dev_nodes_untracked):
            missing_dev = bool(comparison.dev_nodes_missing)
            extra_git = bool(comparison.dev_nodes_untracked)
            comparison.potential_dev_rename = missing_dev and extra_git

        # Package comparison is handled separately since it requires UV
        # This will be set by check_packages_sync

        return comparison

    def check_packages_sync(self) -> PackageSyncStatus:
        """Check if packages are in sync with pyproject.toml.

        Returns:
            Package sync status
        """
        try:
            # Use UV's dry-run to check if sync would change anything
            # Disposable PyTorch overlay materialization ensures the check uses the correct backend.
            extras, all_extras = self._pyproject.resolve_sync_extras(None, False)
            self._uv.sync_project(
                dry_run=True,
                all_groups=True,
                pytorch_manager=self._pytorch_manager,
                extras=extras,
                all_extras=all_extras,
            )
            return PackageSyncStatus(
                in_sync=True, message="Packages match pyproject.toml"
            )
        except UVCommandError as e:
            return PackageSyncStatus(
                in_sync=False,
                message="Packages out of sync (run 'env sync' to update)",
                details=str(e),
            )
