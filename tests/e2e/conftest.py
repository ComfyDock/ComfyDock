"""
E2E Test Fixtures for ComfyGit CLI
==================================
Provides fixtures for testing against real ComfyUI installations.

Usage:
    Run setup first: ./scripts/setup-fixtures.sh
    Then run tests:  uv run pytest tests/e2e/tests/smoke/ -v
"""

import os
import subprocess
from pathlib import Path

import pytest

# ============================================================================
# Configuration Loading
# ============================================================================

def load_dotenv():
    """Load .env file if present (simple implementation, no external deps)."""
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return

    with open(env_file) as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue
            # Parse KEY=value
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                # Expand ${PWD} style variables
                value = value.replace("${PWD}", str(Path(__file__).parent))
                os.environ.setdefault(key, value)


load_dotenv()

# ============================================================================
# Path Configuration
# ============================================================================

E2E_ROOT = Path(__file__).parent
FIXTURES_DIR = Path(os.environ.get("E2E_FIXTURES_DIR", E2E_ROOT / "fixtures"))
UV_CACHE_DIR = Path(os.environ.get("E2E_UV_CACHE_DIR", E2E_ROOT / ".cache/uv"))

# ============================================================================
# Session-Scoped Fixtures (shared across all tests)
# ============================================================================

@pytest.fixture(scope="session")
def shared_uv_cache():
    """Session-persistent UV cache directory.

    Returns the path to the shared UV cache that persists across test runs.
    This dramatically speeds up environment creation by reusing downloaded packages.
    """
    UV_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return UV_CACHE_DIR


@pytest.fixture(scope="session")
def basic_fixture():
    """Pre-built workspace fixture with default environment.

    Returns:
        Path to the basic fixture workspace

    Skips:
        If fixtures haven't been created yet
    """
    fixture_path = FIXTURES_DIR / "basic"
    if not fixture_path.exists():
        pytest.skip(
            "Fixture not found. Run: ./tests/e2e/scripts/setup-fixtures.sh"
        )
    return fixture_path


# ============================================================================
# Function-Scoped Fixtures (per-test isolation)
# ============================================================================

@pytest.fixture
def workspace(basic_fixture):
    """Function-scoped workspace access.

    Provides access to the basic fixture workspace. Tests should treat this
    as read-only where possible. For tests that modify state, use fresh_workspace.

    Returns:
        Path to the workspace
    """
    # For smoke tests, we use the fixture directly without copying.
    # Tests should be read-only or use git reset for cleanup.
    return basic_fixture


@pytest.fixture
def cg(workspace, shared_uv_cache):
    """Helper to run cg (comfygit) CLI commands.

    Returns a function that runs cg commands against the test workspace.

    Example:
        result = cg("status")
        result = cg("env", "list")
        result = cg("node", "list", "-e", "default")
    """
    def run_cg(*args, check=True, capture_output=True, **kwargs):
        """Run a cg command against the test workspace.

        Args:
            *args: Command arguments (e.g., "status", "env", "list")
            check: Raise CalledProcessError on non-zero exit (default: True)
            capture_output: Capture stdout/stderr (default: True)
            **kwargs: Additional subprocess.run kwargs

        Returns:
            subprocess.CompletedProcess with stdout/stderr

        Raises:
            subprocess.CalledProcessError: If check=True and command fails
        """
        cmd = ["cg", "-H", str(workspace)] + list(args)

        # Set up environment with shared UV cache
        env = os.environ.copy()
        env["UV_CACHE_DIR"] = str(shared_uv_cache)

        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            env=env,
            **kwargs
        )

        if check and result.returncode != 0:
            error_msg = f"Command failed: {' '.join(cmd)}\n"
            error_msg += f"Exit code: {result.returncode}\n"
            if result.stdout:
                error_msg += f"stdout: {result.stdout}\n"
            if result.stderr:
                error_msg += f"stderr: {result.stderr}"
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )

        return result

    return run_cg


@pytest.fixture
def fresh_workspace(tmp_path):
    """Provides a fresh empty path for workspace initialization tests.

    Use this for tests that need to test `cg init` or require a completely
    clean workspace without any pre-existing state.

    Returns:
        Path to an empty directory that can be used as workspace target
    """
    workspace_path = tmp_path / "workspace"
    # Don't create it - let the test do cg init
    return workspace_path


@pytest.fixture
def cg_init(shared_uv_cache):
    """Helper to run cg commands without a pre-existing workspace.

    Similar to `cg` fixture but doesn't require a workspace to exist.
    Useful for testing workspace initialization.

    Example:
        result = cg_init("init", str(fresh_workspace))
    """
    def run_cg(*args, check=True, capture_output=True, **kwargs):
        cmd = ["cg"] + list(args)

        env = os.environ.copy()
        env["UV_CACHE_DIR"] = str(shared_uv_cache)

        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            env=env,
            **kwargs
        )

        if check and result.returncode != 0:
            error_msg = f"Command failed: {' '.join(cmd)}\n"
            error_msg += f"Exit code: {result.returncode}\n"
            if result.stdout:
                error_msg += f"stdout: {result.stdout}\n"
            if result.stderr:
                error_msg += f"stderr: {result.stderr}"
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )

        return result

    return run_cg
