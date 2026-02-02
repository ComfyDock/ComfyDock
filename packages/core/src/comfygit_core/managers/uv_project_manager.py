"""UV project management with smart orchestration and pyproject.toml coordination."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from ..integrations.uv_command import UVCommand
from ..logging.logging_config import get_logger
from ..models.exceptions import CDPyprojectError, UVCommandError

if TYPE_CHECKING:
    from ..managers.pyproject_manager import PyprojectManager
    from ..managers.pytorch_backend_manager import PyTorchBackendManager

logger = get_logger(__name__)


class UVProjectManager:
    """High-level UV project management with smart workflows and pyproject.toml coordination."""

    # Marker translations for converting requirements.txt to pyproject.toml format
    MARKER_TRANSLATIONS = {
        'platform_system == "Linux"': "sys_platform == 'linux'",
        'platform_system == "Windows"': "sys_platform == 'win32'",
        'platform_system == "Darwin"': "sys_platform == 'darwin'",
        'platform_system': 'sys_platform',
        'platform_machine': 'platform_machine',
        '"Linux"': "'linux'",
        '"Windows"': "'win32'",
        '"Darwin"': "'darwin'",
        '"x86_64"': "'x86_64'",
        'python_version': 'python_version',
        'python_full_version': 'python_full_version',
    }

    def __init__(
        self,
        uv_command: UVCommand,
        pyproject_manager: PyprojectManager,
    ):
        self.uv = uv_command
        self.pyproject = pyproject_manager

    # ===== Properties =====

    @property
    def project_path(self) -> Path:
        return self.pyproject.path.parent

    @property
    def python_executable(self) -> Path:
        return self.uv.python_executable

    @property
    def binary(self) -> str:
        return self.uv.binary

    # ===== Basic Operations =====

    def init_project(self, name: str | None = None, python_version: str | None = None, **flags) -> str:
        result = self.uv.init(name=name, python=python_version, **flags)
        return result.stdout

    def add_dependency(
        self,
        package: str | None = None,
        packages: list[str] | None = None,
        requirements_file: Path | None = None,
        upgrade: bool = False,
        group: str | None = None,
        dev: bool = False,
        editable: bool = False,
        bounds: str | None = None,
        **flags
    ) -> str:
        """Add one or more dependencies to the project.

        Args:
            package: Single package to add (legacy parameter)
            packages: List of packages to add
            requirements_file: Path to requirements file
            upgrade: Whether to upgrade existing packages
            group: Dependency group name (e.g., 'optional-cuda')
            dev: Add to dev dependencies
            editable: Install as editable (for local development)
            bounds: Version specifier style ('lower', 'major', 'minor', 'exact')
            **flags: Additional UV flags

        Returns:
            UV command stdout

        Raises:
            ValueError: If none of package, packages, or requirements_file is provided
        """
        if packages:
            pkg_list = packages
        elif package:
            pkg_list = [package]
        elif requirements_file:
            pkg_list = None
        else:
            raise ValueError("Either 'package', 'packages', or 'requirements_file' must be provided")

        result = self.uv.add(
            packages=pkg_list,
            requirements_file=requirements_file,
            upgrade=upgrade,
            group=group,
            dev=dev,
            editable=editable,
            bounds=bounds,
            **flags
        )
        return result.stdout

    def remove_dependency(self, package: str | None = None, packages: list[str] | None = None, **flags) -> dict:
        """Remove one or more dependencies from the project.

        Filters out packages that don't exist in dependencies before calling uv remove.
        This makes the operation idempotent and safe to call with non-existent packages.

        Args:
            package: Single package to remove (legacy parameter)
            packages: List of packages to remove
            **flags: Additional UV flags

        Returns:
            Dict with 'removed' (list of packages removed) and 'skipped' (list of packages not in deps)
        """
        if packages:
            pkg_list = packages
        elif package:
            pkg_list = [package]
        else:
            raise ValueError("Either 'package' or 'packages' must be provided")

        # Get current dependencies to filter what actually exists
        from ..utils.dependency_parser import parse_dependency_string
        config = self.pyproject.load()
        current_deps = config.get('project', {}).get('dependencies', [])
        current_pkg_names = {parse_dependency_string(dep)[0].lower() for dep in current_deps}

        # Filter to only packages that exist
        existing_packages = [pkg for pkg in pkg_list if pkg.lower() in current_pkg_names]
        missing_packages = [pkg for pkg in pkg_list if pkg.lower() not in current_pkg_names]

        # If nothing to remove, return early
        if not existing_packages:
            return {
                'removed': [],
                'skipped': missing_packages
            }

        # Remove only existing packages
        self.uv.remove(existing_packages, **flags)

        return {
            'removed': existing_packages,
            'skipped': missing_packages
        }

    def sync_project(
        self,
        verbose: bool = False,
        pytorch_manager: PyTorchBackendManager | None = None,
        backend_override: str | None = None,
        **flags
    ) -> str:
        """Sync project dependencies.

        Args:
            verbose: Show uv output in real-time
            pytorch_manager: Optional PyTorch backend manager for temporary injection.
                            If provided, PyTorch config is injected before sync and
                            restored after (regardless of success/failure).
                            Also forces reinstall of PyTorch packages to ensure correct backend.
            backend_override: Override PyTorch backend instead of reading from file (e.g., "cu128")
            **flags: Additional uv sync flags

        Returns:
            UV command stdout
        """
        if pytorch_manager:
            from ..constants import PYTORCH_CORE_PACKAGES

            # Force reinstall of PyTorch packages to ensure correct backend is used
            # Without this, uv may skip reinstall if torch is already installed
            flags['reinstall_package'] = list(PYTORCH_CORE_PACKAGES)

            # When overriding backend, delete uv.lock to force complete re-resolution.
            # The lock file contains platform-specific PyTorch wheel pins that won't
            # work when switching backends (e.g., cu128 -> cpu has different wheels).
            if backend_override:
                lock_file = self.pyproject.path.parent / "uv.lock"
                if lock_file.exists():
                    lock_file.unlink()
                    logger.info(f"Deleted uv.lock for backend override to {backend_override}")

            # Use PyprojectManager's injection context
            with self.pyproject.pytorch_injection_context(
                pytorch_manager, backend_override=backend_override
            ):
                result = self.uv.sync(verbose=verbose, **flags)
                return result.stdout
        else:
            result = self.uv.sync(verbose=verbose, **flags)
            return result.stdout

    def lock_project(self, **flags) -> str:
        result = self.uv.lock(**flags)
        return result.stdout

    def run_command(self, command: list[str], **flags) -> str:
        result = self.uv.run(command, **flags)
        return result.stdout

    def create_venv(self, venv_path: Path, python_version: str | None = None, **flags) -> str:
        result = self.uv.venv(venv_path, python=python_version, **flags)
        return result.stdout

    # ===== Smart Requirements Handling =====

    def add_requirements_with_sources(
        self,
        requirements: Path | list[str],
        group: str | None = None,
        **flags
    ) -> None:
        """Smart requirements.txt handler that coordinates UV and pyproject.toml."""
        logger.info("Adding requirements with sources...")

        categorized = self._categorize_requirements(requirements)

        # Create temp file with everything EXCEPT multi-URL packages
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
                for line in categorized["regular_lines"]:
                    tmp.write(line + "\n")
                for line in categorized["git_urls"]:
                    tmp.write(line + "\n")
                for line in categorized["single_urls"]:
                    tmp.write(line + "\n")
                tmp_path = Path(tmp.name)

            # Let UV handle everything it can
            if tmp_path.stat().st_size > 0:
                self.add_dependency(requirements_file=tmp_path, group=group, **flags)

            # Post-process multi-URL packages via pyproject.toml
            for package, urls_with_markers in categorized["multi_url_packages"].items():
                self._add_url_sources_with_markers(package, urls_with_markers, group)

            logger.info("Successfully added all requirements")
        except UVCommandError:
            raise  # Preserve original error with stderr
        except Exception as e:
            raise UVCommandError(f"Failed to add requirements: {e}") from e
        finally:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()

    def _categorize_requirements(self, requirements: Path | list[str]) -> dict:
        """Categorize requirements into UV-compatible and special handling categories."""
        logger.info("Categorizing requirements...")

        categorized = {
            'regular_lines': [],
            'git_urls': [],
            'single_urls': [],
            'multi_url_packages': {},  # package_name -> [{"url": ..., "marker": ...}, ...]
        }

        url_packages = {}  # Track URL-based packages to detect multiples

        # Handle both Path and list[str] input
        if isinstance(requirements, Path):
            with open(requirements, encoding='utf-8') as f:
                lines = f.readlines()
        else:
            lines = requirements

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Git URLs - UV handles these perfectly
            if line.startswith('git+') or 'git+' in line:
                categorized['git_urls'].append(line)

            # Direct URLs (http/https/file)
            elif any(proto in line for proto in ['http://', 'https://', 'file://']):
                package_name, url, marker = self._parse_url_requirement(line)

                if package_name in url_packages:
                    # Multiple URLs for same package - needs special handling
                    if package_name not in categorized['multi_url_packages']:
                        # Move the first occurrence from single_urls to multi_url
                        categorized['multi_url_packages'][package_name] = [url_packages[package_name]]
                        # Remove from single_urls
                        categorized['single_urls'] = [
                            line for line in categorized['single_urls']
                            if url_packages[package_name]['url'] not in line
                        ]
                    categorized['multi_url_packages'][package_name].append({
                        'url': url,
                        'marker': marker
                    })
                else:
                    # First URL for this package
                    url_packages[package_name] = {'url': url, 'marker': marker}
                    categorized['single_urls'].append(line)

            # Regular package specifications
            else:
                categorized['regular_lines'].append(line)

        return categorized

    def _parse_url_requirement(self, line: str) -> tuple[str, str, str | None]:
        """Parse a URL requirement line. Returns (package_name, url, marker)."""
        marker = None

        # Check for environment marker
        if ';' in line:
            url_part, marker_part = line.split(';', 1)
            marker = self._translate_marker(marker_part.strip())
        else:
            url_part = line

        # Handle "package @ url" format
        if ' @ ' in url_part:
            package_name, url = url_part.split(' @ ', 1)
            package_name = package_name.strip()
            url = url.strip()
        else:
            # Extract from URL
            url = url_part.strip()
            package_name = self._extract_package_from_url(url)

        return package_name, url, marker

    def _extract_package_from_url(self, url: str) -> str:
        """Extract package name from various URL types."""
        # Remove URL parameters
        url = url.split('?')[0].split('#')[0]

        # Get filename
        filename = url.split('/')[-1]

        if filename.endswith('.whl'):
            # Wheel format: {distribution}-{version}[-{build tag}]-{python}-{abi}-{platform}.whl
            parts = filename[:-4].split('-')  # Remove .whl
            package_name = parts[0]
        elif filename.endswith(('.tar.gz', '.zip', '.tar.bz2')):
            # Source dist format: {name}-{version}.tar.gz
            if filename.endswith('.tar.gz'):
                base = filename[:-7]
            elif filename.endswith('.tar.bz2'):
                base = filename[:-8]
            else:
                base = filename[:-4]
            # Split on last hyphen to separate name from version
            parts = base.rsplit('-', 1)
            package_name = parts[0] if parts else base
        else:
            # Fallback: use filename without extension
            package_name = filename.split('.')[0]

        # Normalize: convert underscores to hyphens (PEP 503)
        return package_name.replace('_', '-').lower()

    def _translate_marker(self, marker: str) -> str:
        """Translate requirements.txt markers to pyproject.toml format."""
        result = marker

        # Apply translations from class constant
        for old, new in self.MARKER_TRANSLATIONS.items():
            result = result.replace(old, new)

        # Normalize all remaining double quotes to single quotes
        result = result.replace('"', "'")

        return result

    def _add_url_sources_with_markers(self, package_name: str, urls_with_markers: list[dict],
                                    group: str | None = None) -> None:
        """Update [tool.uv.sources] and optionally add to dependency group."""
        self.pyproject.uv_config.add_url_sources(package_name, urls_with_markers, group)
        logger.info(f"Added {len(urls_with_markers)} URL source(s) for '{package_name}'")

    # ===== Constraint and Index Management =====

    def add_constraint_dependency(self, package: str) -> None:
        """Add a constraint dependency to the project's pyproject.toml."""
        self.pyproject.uv_config.add_constraint(package)
        logger.info(f"Added constraint: {package}")

    def create_index(self, name: str, url: str, explicit: bool = True) -> None:
        """Create a new index in the project's pyproject.toml."""
        self.pyproject.uv_config.add_index(name, url, explicit)
        logger.info(f"Created index '{name}'")

    def add_source_index(self, package_name: str, index: str) -> None:
        """Add a source index mapping for a package in pyproject.toml."""
        # Validate that the index exists
        indexes = self.pyproject.uv_config.get_indexes()
        if not any(idx.get('name') == index for idx in indexes):
            raise CDPyprojectError(f"Index '{index}' does not exist. Please create it first using create_index()")

        self.pyproject.uv_config.add_source(package_name, {'index': index})
        logger.info(f"Added source for '{package_name}': index = '{index}'")

    def remove_dependency_group(self, group_name: str) -> None:
        """Remove a dependency group from pyproject.toml."""
        self.pyproject.dependencies.remove_group(group_name)
        logger.info(f"Removed dependency group: {group_name}")

    # ===== Package Operations =====

    def install_packages(self, packages: list[str] | None = None, requirements_file: Path | None = None,
                        python: Path | None = None, torch_backend: str | None = None,
                        verbose: bool = False, **flags) -> str:
        """Install packages using uv pip install."""
        result = self.uv.pip_install(
            packages=packages,
            requirements_file=requirements_file,
            python=python,
            torch_backend=torch_backend,
            verbose=verbose,
            **flags
        )
        return result.stdout

    def show_package(self, package: str, python: Path) -> str:
        """Show package information."""
        result = self.uv.pip_show(package, python)
        return result.stdout

    def list_packages(self, python: Path) -> str:
        """List installed packages."""
        result = self.uv.pip_list(python)
        return result.stdout

    def uninstall_packages(self, packages: list[str], python: Path) -> str:
        """Uninstall packages."""
        result = self.uv.pip_install(packages=[f"-{pkg}" for pkg in packages], python=python)
        return result.stdout

    def freeze_packages(self, python: Path) -> str:
        """Export installed packages in requirements format."""
        result = self.uv.pip_freeze(python)
        return result.stdout

    def pip_compile(self, in_requirements_file: Path | None = None,
                   out_requirements_file: Path | None = None, **flags) -> str:
        """Compile dependencies to requirements format."""
        # Check if we're compiling a requirements file or a pyproject.toml
        if in_requirements_file and in_requirements_file.exists():
            input_file = in_requirements_file
        else:
            input_file = self.pyproject.path

            # Add dependency groups if compiling pyproject.toml
            if self.pyproject.exists():
                try:
                    dependency_groups = self.pyproject.dependencies.get_groups()
                    for group_name in dependency_groups.keys():
                        flags.setdefault('group', []).append(group_name) if 'group' in flags else None
                except Exception as e:
                    logger.debug(f"Could not get dependency groups: {e}")

        result = self.uv.pip_compile(
            input_file=input_file,
            output_file=out_requirements_file,
            **flags
        )
        return result.stdout

    # ===== Tool Management =====

    def run_tool(self, tool: str, args: list[str] | None = None) -> str:
        """Run a tool in an isolated environment using uvx."""
        result = self.uv.tool_run(tool, args)
        return result.stdout

    def install_tool(self, tool: str) -> str:
        """Install a tool globally."""
        result = self.uv.tool_install(tool)
        return result.stdout

    # ===== Python Management =====

    def install_python(self, version: str) -> str:
        """Install a Python version."""
        result = self.uv.python_install(version)
        return result.stdout

    def list_python_versions(self) -> str:
        """List available Python versions."""
        result = self.uv.python_list()
        return result.stdout

    # ===== Advanced Sync Operations =====

    def sync_dependencies_progressive(
        self,
        dry_run: bool = False,
        callbacks = None,
        verbose: bool = False,
        pytorch_manager: PyTorchBackendManager | None = None,
        backend_override: str | None = None,
    ) -> dict:
        """Install dependencies progressively with graceful optional group handling.

        Installs dependencies in phases:
        1. Base dependencies + all groups together with iterative optional group removal on failure

        If optional groups fail to build, we iteratively:
        - Parse the error to identify the failing group
        - Remove that group from pyproject.toml
        - Delete uv.lock to force re-resolution
        - Retry the sync with all remaining groups
        - Continue until success or max retries

        Args:
            dry_run: If True, don't actually install
            callbacks: Optional callbacks for progress reporting
            verbose: If True, show uv output in real-time
            pytorch_manager: Optional PyTorch backend manager for temporary injection
            backend_override: Override PyTorch backend instead of reading from file (e.g., "cu128")

        Returns:
            Dict with keys:
            - packages_synced: bool
            - dependency_groups_installed: list[str]
            - dependency_groups_failed: list[tuple[str, str]]
        """
        from ..constants import MAX_OPT_GROUP_RETRIES
        from ..utils.uv_error_handler import parse_failed_dependency_group

        result = {
            "packages_synced": False,
            "dependency_groups_installed": [],
            "dependency_groups_failed": []
        }

        attempts = 0

        logger.info("Installing dependencies with all groups...")

        while attempts < MAX_OPT_GROUP_RETRIES:
            try:
                # Get all dependency groups (may have changed after removal)
                dep_groups = self.pyproject.dependencies.get_groups()

                if dep_groups:
                    # Install base + all groups together
                    group_list = list(dep_groups.keys())
                    logger.debug(f"Syncing with groups: {group_list}")
                    self.sync_project(
                        group=group_list,
                        dry_run=dry_run,
                        verbose=verbose,
                        pytorch_manager=pytorch_manager,
                        backend_override=backend_override,
                    )

                    # Track successful installations
                    result["dependency_groups_installed"].extend(group_list)
                else:
                    # No groups - just sync base dependencies
                    logger.debug("No dependency groups, syncing base only")
                    self.sync_project(
                        dry_run=dry_run,
                        no_default_groups=True,
                        verbose=verbose,
                        pytorch_manager=pytorch_manager,
                        backend_override=backend_override,
                    )

                result["packages_synced"] = True
                break  # Success - exit loop

            except UVCommandError as e:
                failed_group = parse_failed_dependency_group(e.stderr or "")

                if failed_group and failed_group.startswith('optional-'):
                    attempts += 1
                    logger.warning(
                        f"Build failed for optional group '{failed_group}' (attempt {attempts}/{MAX_OPT_GROUP_RETRIES}), "
                        "removing and retrying..."
                    )

                    # Remove the problematic group
                    try:
                        self.pyproject.dependencies.remove_group(failed_group)
                    except ValueError:
                        pass  # Group already gone

                    # Delete lockfile to force re-resolution
                    lockfile = self.project_path / "uv.lock"
                    if lockfile.exists():
                        lockfile.unlink()
                        logger.debug("Deleted uv.lock to force re-resolution")

                    result["dependency_groups_failed"].append((failed_group, "Build failed (incompatible platform)"))

                    if callbacks:
                        callbacks.on_dependency_group_complete(failed_group, success=False, error="Build failed - removed")

                    if attempts >= MAX_OPT_GROUP_RETRIES:
                        raise RuntimeError(
                            f"Failed to install dependencies after {MAX_OPT_GROUP_RETRIES} attempts. "
                            f"Removed groups: {[g for g, _ in result['dependency_groups_failed']]}"
                        )

                    # Loop continues for retry
                else:
                    # Not an optional group failure - fail immediately
                    raise

        return result

    # ===== Utility =====

    def version(self) -> str:
        """Get the installed UV version."""
        return self.uv.version()
