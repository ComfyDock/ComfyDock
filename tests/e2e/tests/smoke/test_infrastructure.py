"""
E2E Infrastructure Smoke Tests
==============================
Validates that the E2E test infrastructure is working correctly.
These tests verify fixtures and helpers before testing actual CLI functionality.
"""
import subprocess


class TestFixtureInfrastructure:
    """Verify E2E test fixtures work correctly."""

    def test_basic_fixture_exists(self, basic_fixture):
        """
        Verify basic fixture was created by setup-fixtures.sh.

        WHY: All other E2E tests depend on this fixture existing.
        If this fails, run: ./scripts/setup-fixtures.sh
        """
        assert basic_fixture.exists(), f"Fixture not found at {basic_fixture}"
        assert (basic_fixture / ".metadata").is_dir()
        assert (basic_fixture / "environments" / "default").is_dir()

    def test_workspace_has_default_environment(self, workspace):
        """
        Verify workspace fixture has a default environment.

        WHY: Most tests assume a 'default' environment exists.
        """
        env_path = workspace / "environments" / "default"
        assert env_path.exists(), "Default environment not found"
        assert (env_path / "ComfyUI").is_dir(), "ComfyUI not installed"
        assert (env_path / ".venv").is_dir(), "Python venv not created"

    def test_cg_fixture_runs_commands(self, cg):
        """
        Verify cg fixture can execute CLI commands.

        WHY: The cg() helper is used by all other tests.
        """
        result = cg("list")
        assert result.returncode == 0
        assert "default" in result.stdout

    def test_cg_fixture_captures_output(self, cg):
        """
        Verify cg fixture properly captures stdout and stderr.

        WHY: Tests need to assert on command output.
        """
        result = cg("--version")
        assert result.returncode == 0
        assert result.stdout  # Should have version output


class TestCLIBasics:
    """Basic CLI smoke tests."""

    def test_version_command(self):
        """
        cg --version should return version number.

        WHY: Basic sanity check that CLI is installed and working.
        """
        result = subprocess.run(
            ["cg", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        # Should contain a version number like "0.3.12"
        assert any(c.isdigit() for c in result.stdout)

    def test_help_command(self):
        """
        cg --help should show available commands.

        WHY: Verifies CLI arg parsing works correctly.
        """
        result = subprocess.run(
            ["cg", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "init" in result.stdout
        assert "create" in result.stdout
        assert "status" in result.stdout

    def test_status_on_fixture(self, cg):
        """
        cg status should work on the fixture environment.

        WHY: Status is the most common command users run.
        """
        result = cg("-e", "default", "status")
        assert result.returncode == 0
        # Should show clean status for fresh fixture
        assert "default" in result.stdout.lower() or "environment" in result.stdout.lower()
