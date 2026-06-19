"""PyTorch version prober via uv dry-run.

Uses uv's --dry-run flag to discover exact PyTorch versions without
actually installing packages. This is fast and leverages uv's built-in
backend detection (CUDA, ROCm, CPU, etc.).
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from functools import lru_cache

from ..logging.logging_config import get_logger
from .common import run_command

logger = get_logger(__name__)

# Timeout for probe operations (seconds)
PROBE_TIMEOUT = 60


class PyTorchProbeError(Exception):
    """Error during PyTorch version probing."""

    pass


def _find_uv_binary() -> str:
    """Find the uv binary, preferring the bundled package version."""
    try:
        from uv import find_uv_bin
        return find_uv_bin()
    except (ImportError, FileNotFoundError):
        pass
    binary = shutil.which("uv")
    if binary:
        return binary
    raise PyTorchProbeError("uv is not installed")


def _uv_command_env() -> dict[str, str]:
    """Return a subprocess env for nested uv commands.

    ComfyGit often runs from `uv run`, especially in development. Nested uv
    commands should not inherit the parent uv-run virtualenv context when they
    are creating or probing a separate environment.
    """
    env = os.environ.copy()
    for key in ("VIRTUAL_ENV", "UV_RUN_RECURSION_DEPTH"):
        env.pop(key, None)
    return env


def _format_failed_command(result) -> str:
    parts = [f"exit code {result.returncode}"]
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        parts.append(f"stdout: {stdout}")
    if stderr:
        parts.append(f"stderr: {stderr}")
    return "; ".join(parts)


def get_exact_python_version(requested_version: str) -> str:
    """Get exact Python version that uv would use.

    Args:
        requested_version: Requested version (e.g., "3.12" or "3.12.11")

    Returns:
        Exact version (e.g., "3.12.11")

    Raises:
        PyTorchProbeError: If version cannot be determined
    """
    uv = _find_uv_binary()
    result = run_command(
        [uv, "python", "find", requested_version],
        env=_uv_command_env(),
    )

    if result.returncode != 0:
        raise PyTorchProbeError(
            f"Could not find Python {requested_version}: {_format_failed_command(result)}"
        )

    # Parse output - looks like: /path/to/cpython-3.12.11-linux.../bin/python3.12
    output = result.stdout.strip()

    # Match cpython-X.Y.Z or python-X.Y.Z in path
    match = re.search(r"(?:cpython|python)-(\d+\.\d+(?:\.\d+)?)", output, re.IGNORECASE)
    if match:
        return match.group(1)

    # Also try pythonX.Y.Z format (some systems)
    match = re.search(r"python(\d+\.\d+(?:\.\d+)?)", output, re.IGNORECASE)
    if match:
        return match.group(1)

    raise PyTorchProbeError(
        f"Could not parse Python version from uv output: {output}"
    )


def probe_pytorch_versions(
    python_version: str,
    backend: str,
) -> tuple[dict[str, str], str]:
    """Probe PyTorch versions using uv dry-run.

    Creates a temporary venv and uses `uv pip install --dry-run` with
    `--torch-backend` to discover exact versions without installing.

    Args:
        python_version: Python version (e.g., "3.12" or "3.12.11")
        backend: PyTorch backend ("auto", "cu128", "cpu", etc.)

    Returns:
        Tuple of (versions_dict, resolved_backend):
        - versions_dict: {"torch": "2.9.1+cu128", "torchvision": "0.24.1+cu128", ...}
        - resolved_backend: "cu128" (extracted from version suffix)

    Raises:
        PyTorchProbeError: If probing fails
    """
    versions, resolved_backend = _probe_pytorch_versions_cached(python_version, backend)
    return dict(versions), resolved_backend


def clear_pytorch_probe_cache() -> None:
    """Clear cached PyTorch probe results.

    This is primarily useful for tests and long-running developer processes
    that intentionally need to re-check newly published wheel versions.
    """
    _probe_pytorch_versions_cached.cache_clear()


@lru_cache(maxsize=32)
def _probe_pytorch_versions_cached(
    python_version: str,
    backend: str,
) -> tuple[dict[str, str], str]:
    # Get exact Python version for consistent probing
    try:
        exact_py = get_exact_python_version(python_version)
    except PyTorchProbeError:
        exact_py = python_version  # Fall back to requested version

    # Create temp probe venv
    temp_dir = tempfile.mkdtemp(prefix=".comfygit-probe-")

    uv = _find_uv_binary()

    try:
        logger.info(f"Probing PyTorch versions for Python {exact_py} + {backend}...")

        # 1. Create minimal venv
        venv_result = run_command(
            [uv, "venv", temp_dir, "--python", exact_py],
            timeout=PROBE_TIMEOUT,
            env=_uv_command_env(),
        )

        if venv_result.returncode != 0:
            raise PyTorchProbeError(
                f"Failed to create probe venv: {_format_failed_command(venv_result)}"
            )

        # 2. Run dry-run install with --torch-backend
        dry_run_result = _run_torch_dry_run(
            uv=uv,
            temp_dir=temp_dir,
            backend=backend,
        )

        if dry_run_result.returncode != 0:
            original_stderr = dry_run_result.stderr
            if backend == "auto":
                logger.warning(
                    "Auto PyTorch backend probe failed; falling back to CPU backend. "
                    f"Original error: {original_stderr}"
                )
                dry_run_result = _run_torch_dry_run(
                    uv=uv,
                    temp_dir=temp_dir,
                    backend="cpu",
                )
                if dry_run_result.returncode != 0:
                    raise PyTorchProbeError(
                        "Dry-run probe failed for auto backend and CPU fallback. "
                        f"Auto stderr: {original_stderr}\n"
                        f"CPU stderr: {dry_run_result.stderr}"
                    )
            else:
                raise PyTorchProbeError(
                    f"Dry-run probe failed: {dry_run_result.stderr}"
                )

        # 3. Parse output for package versions
        # uv writes dry-run output to stderr, so check both
        output = dry_run_result.stdout or dry_run_result.stderr
        versions, resolved_backend = _parse_dry_run_output(output)

        if not versions:
            raise PyTorchProbeError(
                f"Could not parse PyTorch versions from dry-run output:\n{output}"
            )

        logger.info(f"Probed PyTorch: torch={versions.get('torch')}, backend={resolved_backend}")

        return versions, resolved_backend

    finally:
        # Clean up temp directory
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.warning(f"Failed to clean up probe dir {temp_dir}: {e}")


def _run_torch_dry_run(
    *,
    uv: str,
    temp_dir: str,
    backend: str,
):
    return run_command(
        [
            uv, "pip", "install",
            "--dry-run",
            "--reinstall-package", "torch",
            "--reinstall-package", "torchvision",
            "--reinstall-package", "torchaudio",
            f"--torch-backend={backend}",
            "--python", temp_dir,
            "torch", "torchvision", "torchaudio",
        ],
        timeout=PROBE_TIMEOUT,
        env=_uv_command_env(),
    )


def _parse_dry_run_output(output: str) -> tuple[dict[str, str], str]:
    """Parse uv pip install --dry-run output.

    Looks for lines like:
        + torch==2.9.1+cu128
        + torchvision==0.24.1+cu128
        + torchaudio==2.9.1+cu128

    Args:
        output: stdout from uv pip install --dry-run

    Returns:
        Tuple of (versions_dict, resolved_backend)
    """
    versions: dict[str, str] = {}
    resolved_backend = "cpu"  # Default if no suffix found

    # Pattern: " + package==version" or " + package==version+backend"
    pattern = re.compile(r"^\s*\+\s+(torch(?:vision|audio)?)==(\S+)", re.MULTILINE)

    for match in pattern.finditer(output):
        package = match.group(1).lower()
        version = match.group(2)
        versions[package] = version

        # Extract backend from first package with suffix
        if "+" in version and resolved_backend == "cpu":
            resolved_backend = version.split("+")[1]

    return versions, resolved_backend
