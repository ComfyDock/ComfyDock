"""Pure UV command wrapper with no business logic."""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..logging.logging_config import get_logger
from ..models.exceptions import UVCommandError, UVNotInstalledError
from ..utils.common import run_command

logger = get_logger(__name__)


@dataclass
class CommandResult:
    """Result of a UV command execution."""
    stdout: str
    stderr: str
    returncode: int
    success: bool

    @classmethod
    def from_completed_process(cls, result) -> "CommandResult":
        return cls(
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            success=result.returncode == 0
        )


class UVCommand:
    """Pure wrapper around UV CLI commands. No business logic or pyproject.toml manipulation."""

    DEFAULT_TIMEOUT = None  # no timeout

    def __init__(
        self,
        binary_path: Path | None = None,
        project_env: Path | None = None,
        cache_dir: Path | None = None,
        python_install_dir: Path | None = None,
        link_mode: str | None = "hardlink",
        cwd: Path | None = None,
        torch_backend: str | None = None,
    ):
        self._binary = self._check_uv_installed(binary_path)
        self.timeout = self.DEFAULT_TIMEOUT
        self._project_env = project_env
        self._cache_dir = cache_dir
        self._python_install_dir = python_install_dir
        self._link_mode = link_mode
        self._cwd = cwd
        self._torch_backend = torch_backend
        self._base_env = self._setup_base_environment()

    def _check_uv_installed(self, binary_path: Path | None) -> str:
        # Explicit path takes priority
        if binary_path and binary_path.is_file():
            return str(binary_path)

        # Try UV from Python package (installed with comfydock)
        try:
            from uv import find_uv_bin
            binary = find_uv_bin()
            logger.debug(f"Using UV from package: {binary}")
            return binary
        except ImportError:
            logger.debug("UV package not found in current environment")
        except FileNotFoundError as e:
            logger.warning(f"UV package found but binary missing: {e}")

        # Fallback to system UV
        binary = shutil.which("uv")
        if binary is None:
            raise UVNotInstalledError(
                "uv is not installed. Install comfydock with: pip install comfygit"
            )

        logger.warning(
            f"Using system UV from PATH: {binary}. "
            f"This may cause version compatibility issues. "
            f"Recommended: pip install --force-reinstall comfydock-cli"
        )
        return binary

    def _setup_base_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update({
            "UV_NO_PROGRESS": "1",
            "NO_COLOR": "1",
            "VIRTUAL_ENV": "",
        })

        if self._project_env:
            env["UV_PROJECT_ENVIRONMENT"] = str(self._project_env)
        if self._cache_dir:
            env["UV_CACHE_DIR"] = str(self._cache_dir)
        if self._python_install_dir:
            env["UV_PYTHON_INSTALL_DIR"] = str(self._python_install_dir)
        if self._link_mode:
            env["UV_LINK_MODE"] = self._link_mode
        if self._torch_backend:
            env["UV_TORCH_BACKEND"] = self._torch_backend

        return env

    def _build_command(self, base: list[str], **options) -> list[str]:
        cmd = [self._binary] + base

        flag_map = {
            'python': '--python',
            'index_url': '--index-url',
            'frozen': '--frozen',
            'dry_run': '--dry-run',
            'no_sync': '--no-sync',
            'name': '--name',
            'no_workspace': '--no-workspace',
            'bare': '--bare',
            'raw': '--raw',
            'dev': '--dev',
            'group': '--group',
            'optional': '--optional',
            'extra': '--extra',
            'all_extras': '--all-extras',
            'editable': '--editable',
            'bounds': '--bounds',
            'prerelease': '--prerelease',
            'all_groups': '--all-groups',
            'no_default_groups': '--no-default-groups',
            'seed': '--seed',
            'upgrade': '--upgrade',
            'upgrade_package': '--upgrade-package',
            'no_install_project': '--no-install-project',
            'no_deps': '--no-deps',
            'compile_bytecode': '--compile-bytecode',
            'quiet': '--quiet',
            'reinstall_package': '--reinstall-package',
        }

        for key, value in options.items():
            if value is None or value is False:
                continue

            flag = flag_map.get(key)
            if flag:
                if isinstance(value, bool):
                    cmd.append(flag)
                elif isinstance(value, list):
                    # Handle list values that need multiple flags (e.g., --group x --group y)
                    for item in value:
                        cmd.extend([flag, str(item)])
                else:
                    cmd.extend([flag, str(value)])

        return cmd

    def _execute(self, cmd: list[str], expect_failure: bool = False, verbose: bool = False) -> CommandResult:
        try:
            env = self._base_env.copy()
            if verbose:
                # Show full output with progress and summary
                env.pop("UV_NO_PROGRESS", None)
                env.pop("NO_COLOR", None)
                result = run_command(cmd, cwd=self._cwd, timeout=self.timeout, env=env, capture_output=False)
            else:
                # Default: quiet mode (capture output, only show on error)
                result = run_command(cmd, cwd=self._cwd, timeout=self.timeout, env=self._base_env, capture_output=True)

            if result.returncode == 0 or expect_failure:
                return CommandResult.from_completed_process(result)
            else:
                raise UVCommandError(
                    f"UV command failed with code {result.returncode}",
                    command=cmd,
                    stderr=result.stderr,
                    stdout=result.stdout,
                    returncode=result.returncode
                )
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"UV command timed out after {self.timeout}s: {' '.join(cmd)}")
        except UVCommandError:
            raise
        except Exception as e:
            raise UVCommandError(f"Failed to execute UV command: {e}", command=cmd) from e

    # ===== Project Management Commands =====

    def init(self, name: str | None = None, python: str | None = None, **flags) -> CommandResult:
        cmd = self._build_command(["init"], name=name, python=python, **flags)
        return self._execute(cmd)

    def add(self, packages: list[str] | None = None, requirements_file: Path | None = None, **flags) -> CommandResult:
        if requirements_file:
            cmd = self._build_command(["add", "-r", str(requirements_file)], **flags)
        else:
            cmd = self._build_command(["add"] + (packages or []), **flags)
        return self._execute(cmd)

    def remove(self, packages: list[str], **flags) -> CommandResult:
        cmd = self._build_command(["remove"] + packages, **flags)
        return self._execute(cmd)

    def sync(self, verbose: bool = False, **flags) -> CommandResult:
        cmd = self._build_command(["sync"], **flags)
        return self._execute(cmd, verbose=verbose)

    def lock(self, **flags) -> CommandResult:
        cmd = self._build_command(["lock"], **flags)
        return self._execute(cmd, expect_failure=flags.get('dry_run', False))

    def run(self, command: list[str], **flags) -> CommandResult:
        cmd = self._build_command(["run"] + command, **flags)
        return self._execute(cmd)

    # ===== Virtual Environment Management =====

    def venv(self, path: Path, **flags) -> CommandResult:
        cmd = self._build_command(["venv", str(path)], **flags)
        return self._execute(cmd)

    # ===== Pip Compatibility =====

    def pip_install(self, packages: list[str] | None = None, requirements_file: Path | None = None,
                   python: Path | None = None, torch_backend: str | None = None,
                   verbose: bool = False, **flags) -> CommandResult:
        cmd = [self._binary, "pip", "install"]

        if python:
            cmd.extend(["--python", str(python)])

        if torch_backend:
            cmd.extend(["--torch-backend", torch_backend])

        for key, value in flags.items():
            if value is None or value is False:
                continue
            flag = f"--{key.replace('_', '-')}"
            if isinstance(value, bool):
                cmd.append(flag)
            else:
                cmd.extend([flag, str(value)])

        if requirements_file:
            cmd.extend(["-r", str(requirements_file)])
        elif packages:
            cmd.extend(packages)

        return self._execute(cmd, verbose=verbose)

    def pip_show(self, package: str, python: Path, **flags) -> CommandResult:
        cmd = [self._binary, "pip", "show", "--python", str(python), package]
        return self._execute(cmd)

    def pip_list(self, python: Path, **flags) -> CommandResult:
        cmd = [self._binary, "pip", "list", "--python", str(python)]
        return self._execute(cmd)

    def pip_freeze(self, python: Path, **flags) -> CommandResult:
        cmd = [self._binary, "pip", "freeze", "--python", str(python)]
        return self._execute(cmd)

    def pip_compile(self, input_file: Path | None = None, output_file: Path | None = None, **flags) -> CommandResult:
        cmd = [self._binary, "pip", "compile"]

        if input_file:
            cmd.append(str(input_file))

        if output_file:
            cmd.extend(["-o", str(output_file)])

        for key, value in flags.items():
            if value is None or value is False:
                continue
            flag = f"--{key.replace('_', '-')}"
            if isinstance(value, bool):
                cmd.append(flag)
            else:
                cmd.extend([flag, str(value)])

        return self._execute(cmd)

    # ===== Tool Management =====

    def tool_run(self, tool: str, args: list[str] | None = None, **flags) -> CommandResult:
        cmd = self._build_command(["tool", "run", tool] + (args or []), **flags)
        return self._execute(cmd)

    def tool_install(self, tool: str, **flags) -> CommandResult:
        cmd = self._build_command(["tool", "install", tool], **flags)
        return self._execute(cmd)

    # ===== Python Management =====

    def python_install(self, version: str, **flags) -> CommandResult:
        cmd = self._build_command(["python", "install", version], **flags)
        return self._execute(cmd)

    def python_list(self, **flags) -> CommandResult:
        cmd = self._build_command(["python", "list"], **flags)
        return self._execute(cmd)

    # ===== Utility =====

    def version(self) -> str:
        result = self._execute([self._binary, "--version"])
        return result.stdout.strip().split()[-1]

    @property
    def binary(self) -> str:
        return self._binary

    @property
    def python_executable(self) -> Path:
        if not self._project_env:
            raise ValueError("No project environment configured")
        # TODO: Make this more robust and cross-platform
        if sys.platform == "win32":
            return self._project_env / "Scripts" / "python.exe"
        return self._project_env / "bin" / "python"
