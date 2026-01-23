"""
E2E Tests: Environment Basics
=============================
Spec: specs/environment-lifecycle.yaml#environment-basics

Tests basic environment operations that don't require running ComfyUI.
"""


class TestEnvironmentBasics:
    """
    Spec: environment-basics

    Validates that a pre-built fixture environment has the expected structure
    and that basic CLI commands work against it.
    """

    def test_fixture_structure(self, workspace):
        """
        Spec: environment-basics.fixture-structure

        WHY: The fixture is the foundation for all other E2E tests. If the
        structure is wrong, tests will fail for the wrong reasons (missing
        dirs vs bugs). This catches setup-fixtures.sh regressions early.
        """
        # Check workspace metadata
        assert (workspace / ".metadata").is_dir(), "Missing .metadata directory"

        # Check default environment exists
        env_path = workspace / "environments" / "default"
        assert env_path.is_dir(), "Missing environments/default directory"

        # Check ComfyUI is installed
        assert (env_path / "ComfyUI").is_dir(), "ComfyUI not installed"
        assert (env_path / "ComfyUI" / "main.py").is_file(), "ComfyUI main.py missing"

        # Check venv exists
        assert (env_path / ".venv").is_dir(), "Python venv not created"

    def test_status_basic(self, cg):
        """
        Spec: environment-basics.status-basic

        WHY: Status is the most common command users run. It should work on
        a fresh environment without errors. Verifies workspace discovery
        and env lookup.
        """
        result = cg("-e", "default", "status")
        assert result.returncode == 0
        # Should mention the environment name
        assert "default" in result.stdout.lower()

    def test_status_verbose(self, cg):
        """
        Spec: environment-basics.status-verbose

        WHY: Verbose mode shows additional details. Tests that the verbose
        flag is wired up correctly.
        """
        result = cg("-e", "default", "status", "-v")
        assert result.returncode == 0
        assert "default" in result.stdout.lower()

    def test_list_environments(self, cg):
        """
        Spec: environment-basics.list-environments

        WHY: Users need to see what environments exist. This tests
        workspace-level environment enumeration works correctly.
        """
        result = cg("list")
        assert result.returncode == 0
        assert "default" in result.stdout
