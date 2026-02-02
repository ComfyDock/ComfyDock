"""Resolution testing utility for dependency conflict detection.

This module provides utilities for testing if dependency resolution will succeed
without actually modifying the environment. Used for pre-flight checks.
"""

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..integrations.uv_command import UVCommand
from ..logging.logging_config import get_logger
from ..managers.pyproject_manager import PyprojectManager
from ..models.exceptions import CDPyprojectError, UVCommandError
from ..utils.conflict_parser import parse_uv_conflicts, parse_uv_resolution

logger = get_logger(__name__)


@dataclass
class ResolutionResult:
    """Result of dependency resolution attempt."""

    success: bool
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    resolved_packages: dict[str, str] = field(default_factory=dict)  # name -> version
    stderr: str = ""  # Raw UV stderr for verbose mode and enhanced error messages


class ResolutionTester:
    """Test dependency resolution without making actual changes."""

    def __init__(self, workspace_path: Path):
        """Initialize the resolution tester.

        Args:
            workspace_path: Path to ComfyDock workspace
        """
        self.workspace_path = workspace_path
        self.uv_cache_path = workspace_path / "uv_cache"
        self.uv_python_path = workspace_path / "uv" / "python"
        self.logger = logger

    def test_resolution(
        self, pyproject_path: Path, python_version: str | None = None
    ) -> ResolutionResult:
        """Test if a pyproject.toml will resolve successfully.

        Args:
            pyproject_path: Path to pyproject.toml to test
            python_version: Optional Python version to test with

        Returns:
            ResolutionResult with success status and any conflicts
        """
        result = ResolutionResult(success=False)

        if not pyproject_path.exists():
            result.warnings.append(f"pyproject.toml not found: {pyproject_path}")
            return result

        self.logger.debug(f"Testing resolution for pyproject at {pyproject_path}")

        try:
            # Create a temporary directory for resolution testing
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # Copy pyproject.toml to temp location
                temp_pyproject = temp_path / "pyproject.toml"
                shutil.copy2(pyproject_path, temp_pyproject)

                # Create UV command for temp directory
                uv = UVCommand(
                    project_env=temp_path / ".venv",
                    cache_dir=self.uv_cache_path,
                    python_install_dir=self.uv_python_path,
                    cwd=temp_path,
                )

                # Try to resolve dependencies (quiet for background testing)
                try:
                    resolution_result = uv.sync(all_groups=True, dry_run=True)
                    resolution_output = resolution_result.stdout
                except UVCommandError as e:
                    # Log full UV error details for debugging
                    self.logger.error("UV resolution test failed")
                    if e.stderr:
                        self.logger.error(f"UV stderr:\n{e.stderr}")
                    if e.stdout:
                        self.logger.debug(f"UV stdout:\n{e.stdout}")

                    # Store raw stderr for verbose mode
                    error_text = e.stderr or str(e)
                    result.stderr = error_text

                    # Try to extract structured conflicts from stderr
                    conflicts = parse_uv_conflicts(error_text)
                    if conflicts:
                        result.conflicts.extend(conflicts)
                    else:
                        # Fallback: Add concise error from stderr
                        if e.stderr:
                            # Extract key error lines from stderr
                            stderr_lines = [l.strip() for l in e.stderr.strip().split('\n') if l.strip()]
                            # Find the main error message (usually has × or ERROR:)
                            error_line = next((l for l in stderr_lines if '×' in l or 'ERROR:' in l.upper()), None)
                            if error_line:
                                result.warnings.append(error_line[:300])
                            else:
                                # Use last non-empty line as fallback
                                result.warnings.append(stderr_lines[-1][:300] if stderr_lines else str(e))
                        else:
                            result.warnings.append(f"Resolution failed: {str(e)}")

                    return result
                except Exception as e:
                    # Non-UV errors
                    self.logger.error(f"Unexpected error during resolution test: {e}")
                    result.warnings.append(f"Resolution test error: {str(e)[:300]}")
                    return result

                logger.debug(f"Resolution output: {resolution_output}")

                result.success = True
                if resolution_output:
                    # Parse resolution output to get package versions
                    result.resolved_packages = parse_uv_resolution(resolution_output)
                    self.logger.debug(
                        f"Resolution successful, {len(result.resolved_packages)} packages"
                    )

        except Exception as e:
            self.logger.error(f"Error during resolution test: {e}")
            result.warnings.append(f"Could not test resolution: {str(e)}")

        return result

    def test_with_additions(
        self,
        base_pyproject: Path,
        additional_deps: list[str],
        group_name: str | None = None,
    ) -> ResolutionResult:
        """Test resolution with additional dependencies added.

        Useful for testing if adding new packages will cause conflicts
        before actually adding them.

        Args:
            base_pyproject: Base pyproject.toml path
            additional_deps: List of additional dependencies to test
            group_name: Optional dependency group to add to

        Returns:
            ResolutionResult with success status and any conflicts
        """
        result = ResolutionResult(success=False)

        if not base_pyproject.exists():
            result.warnings.append(f"Base pyproject.toml not found: {base_pyproject}")
            return result

        # Log what we're testing
        deps_preview = ', '.join(additional_deps[:3])
        if len(additional_deps) > 3:
            deps_preview += f'... (+{len(additional_deps) - 3} more)'
        self.logger.debug(f"Testing additions: {deps_preview} to group '{group_name or 'main'}'")

        try:
            # Create temporary directory for testing
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                temp_pyproject = temp_path / "pyproject.toml"

                # Copy base pyproject
                shutil.copy2(base_pyproject, temp_pyproject)

                # Add the additional dependencies
                manager = PyprojectManager(temp_pyproject)

                if group_name:
                    # Add to dependency group
                    try:
                        manager.dependencies.add_to_group(group_name, additional_deps)
                    except CDPyprojectError as e:
                        result.warnings.append(f"Failed to add to group: {e}")
                        return result
                else:
                    # Add to main dependencies
                    config = manager.load()
                    if "project" not in config:
                        config["project"] = {}
                    if "dependencies" not in config["project"]:
                        config["project"]["dependencies"] = []

                    config["project"]["dependencies"].extend(additional_deps)
                    manager.save(config)

                # Test the modified pyproject
                return self.test_resolution(temp_pyproject)

        except Exception as e:
            self.logger.error(f"Error testing with additions: {e}")
            result.warnings.append(f"Could not test additions: {str(e)}")
            return result

    def test_node_addition(
        self, env_path: Path, node_name: str, requirements: list[str]
    ) -> ResolutionResult:
        """Test if adding a node with requirements will cause conflicts.

        Args:
            env_path: Environment path
            node_name: Name of the node being added
            requirements: List of requirements from the node

        Returns:
            ResolutionResult with success status and any conflicts
        """
        # Check both main and staged pyproject
        staged_pyproject = env_path / ".cec" / "pyproject.toml"
        main_pyproject = env_path / "pyproject.toml"

        # Use staged if exists, otherwise main
        base_pyproject = (
            staged_pyproject if staged_pyproject.exists() else main_pyproject
        )

        if not base_pyproject.exists():
            # No pyproject yet, test with just the requirements
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                temp_pyproject = temp_path / "pyproject.toml"

                # Create minimal pyproject
                manager = PyprojectManager(temp_pyproject)
                config = {
                    "project": {
                        "name": "test-env",
                        "version": "0.1.0",
                        "dependencies": requirements,
                    }
                }
                manager.save(config)

                return self.test_resolution(temp_pyproject)

        # Test with additions to existing pyproject
        group_name = node_name.lower().replace("-", "_").replace(" ", "_")
        return self.test_with_additions(base_pyproject, requirements, group_name)


    def format_conflicts(self, result: ResolutionResult, verbose: bool = False) -> str:
        """Format resolution conflicts for display.

        Args:
            result: ResolutionResult to format
            verbose: Whether to show all conflicts or just top 3

        Returns:
            Formatted string for display
        """
        if result.success:
            return "✓ No dependency conflicts detected"

        lines = []

        # Show conflicts
        if result.conflicts:
            lines.append("⚠️  Dependency conflicts detected:")

            # Filter out the main error line if it's in conflicts
            display_conflicts = [
                c for c in result.conflicts if not c.startswith("Resolution failed")
            ]

            limit = (
                len(display_conflicts) if verbose else min(3, len(display_conflicts))
            )
            for conflict in display_conflicts[:limit]:
                lines.append(f"  • {conflict}")

            if not verbose and len(display_conflicts) > 3:
                lines.append(f"  ... and {len(display_conflicts) - 3} more conflicts")

        # Show warnings
        if result.warnings:
            if lines:
                lines.append("")
            lines.append("⚠️ Warnings:")
            for warning in result.warnings:
                lines.append(f"  • {warning}")

        return "\n".join(lines)
