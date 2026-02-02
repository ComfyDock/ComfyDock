"""Tests for UV error handling and logging."""

import logging

from comfygit_core.models.exceptions import UVCommandError


class TestUVErrorHandling:
    """Test UV error extraction and logging."""

    def test_extract_error_hint_from_stderr_simple(self):
        """Test extracting error hint from simple UV stderr."""
        # Arrange
        stderr = """
Resolved 5 packages in 123ms
error: Package 'foo' conflicts with package 'bar'
        """

        # Act
        from comfygit_core.utils.uv_error_handler import extract_uv_error_hint
        hint = extract_uv_error_hint(stderr)

        # Assert
        assert hint == "error: Package 'foo' conflicts with package 'bar'"

    def test_extract_error_hint_from_stderr_multiline(self):
        """Test extracting error hint from multi-line UV stderr with conflict keyword."""
        # Arrange
        stderr = """
Resolved 10 packages in 456ms
  × No solution found when resolving dependencies:
  ╰─▶ Because torch==2.0.0 depends on numpy>=1.20 and you require torch==2.0.0,
      numpy>=1.20 is required.
      And because opencv-python==4.8.0 depends on numpy<1.20 and you require opencv-python==4.8.0,
      we can conclude that your requirements are unsatisfiable.

  hint: Pre-releases are available for numpy in the requested range
        """

        # Act
        from comfygit_core.utils.uv_error_handler import extract_uv_error_hint
        hint = extract_uv_error_hint(stderr)

        # Assert - Should find the dependency conflict line
        assert "numpy" in hint.lower() or "opencv" in hint.lower() or "unsatisfiable" in hint.lower()

    def test_extract_error_hint_no_keywords(self):
        """Test extracting error hint when no error/conflict keywords found."""
        # Arrange
        stderr = """
Some output line 1
Some output line 2
Final important line
        """

        # Act
        from comfygit_core.utils.uv_error_handler import extract_uv_error_hint
        hint = extract_uv_error_hint(stderr)

        # Assert - Should return last non-empty line
        assert hint == "Final important line"

    def test_extract_error_hint_empty_stderr(self):
        """Test extracting error hint from empty stderr."""
        # Arrange
        stderr = ""

        # Act
        from comfygit_core.utils.uv_error_handler import extract_uv_error_hint
        hint = extract_uv_error_hint(stderr)

        # Assert
        assert hint is None

    def test_log_uv_error_details(self, caplog):
        """Test that UV error details are logged completely."""
        # Arrange
        caplog.set_level(logging.ERROR)

        error = UVCommandError(
            message="UV command failed with code 1",
            command=["uv", "sync", "--all-groups"],
            stderr="error: Package conflict detected\ndetailed error info here",
            stdout="Some stdout output",
            returncode=1
        )

        # Act
        from comfygit_core.utils.uv_error_handler import log_uv_error
        logger = logging.getLogger("test_logger")
        log_uv_error(logger, error, "test-node")

        # Assert - Check that all details are logged
        logged_output = caplog.text
        assert "test-node" in logged_output
        assert "uv sync --all-groups" in logged_output
        assert "Return code: 1" in logged_output
        assert "Package conflict detected" in logged_output
        assert "Some stdout output" in logged_output

    def test_format_uv_error_for_user(self):
        """Test formatting UV error for user display."""
        # Arrange
        error = UVCommandError(
            message="UV command failed with code 1",
            command=["uv", "sync"],
            stderr="error: Package 'foo' conflicts with 'bar'\nAdditional context here",
            stdout="",
            returncode=1
        )

        # Act
        from comfygit_core.utils.uv_error_handler import format_uv_error_for_user
        user_message = format_uv_error_for_user(error)

        # Assert
        assert "UV dependency resolution failed" in user_message or "dependency" in user_message.lower()
        # Should include hint but truncated
        assert "foo" in user_message or "conflict" in user_message.lower()

    def test_handle_uv_error_integration(self, caplog):
        """Test complete UV error handling flow."""
        # Arrange
        caplog.set_level(logging.ERROR)
        logger = logging.getLogger("test_integration")

        error = UVCommandError(
            message="UV command failed with code 1",
            command=["uv", "add", "conflicting-package"],
            stderr="""
Resolved 15 packages in 789ms
error: Because package-a==1.0 depends on dep>=2.0 and package-b==1.0 depends on dep<2.0,
       we can conclude that package-a==1.0 and package-b==1.0 are incompatible.
            """,
            stdout="",
            returncode=1
        )

        # Act
        from comfygit_core.utils.uv_error_handler import handle_uv_error
        user_msg, log_complete = handle_uv_error(error, "test-package", logger)

        # Assert
        # User message should be helpful but concise
        assert isinstance(user_msg, str)
        assert len(user_msg) < 200  # Should be brief
        assert "dependency" in user_msg.lower() or "conflict" in user_msg.lower()

        # Should indicate logs have more info
        assert log_complete is True

        # Logger should have captured full details
        logged = caplog.text
        assert "test-package" in logged
        assert "uv add conflicting-package" in logged
        assert "package-a" in logged or "package-b" in logged


class TestPhase1ErrorHandlingImprovements:
    """Tests for Phase 1 error handling improvements.

    These tests verify:
    1. Longer error messages (300 chars) are not truncated unnecessarily
    2. Fallback warnings appear when conflict parsing fails
    """

    def test_long_error_messages_not_truncated_at_100_chars(self):
        """PHASE 1: Test that error messages up to 300 chars are preserved.

        Current behavior: max_hint_length=100 truncates at 100 chars
        Expected behavior: max_hint_length=300 preserves up to 300 chars

        This test SHOULD FAIL until Phase 1 is implemented.
        """
        # Arrange
        # Create a realistic UV error message that's 215 chars long
        long_error_msg = (
            "error: Because package-a==1.0.0 depends on dependency-x>=2.0 and "
            "package-b==1.0.0 depends on dependency-x<2.0, we can conclude that "
            "package-a==1.0.0 and package-b==1.0.0 are incompatible with the current constraints"
        )
        assert len(long_error_msg) == 215, "Test error message should be 215 chars"

        error = UVCommandError(
            message="UV command failed",
            command=["uv", "sync"],
            stderr=long_error_msg,
            stdout="",
            returncode=1
        )

        # Act
        from comfygit_core.utils.uv_error_handler import format_uv_error_for_user
        user_msg = format_uv_error_for_user(error)

        # Assert
        # After Phase 1 implementation, this should NOT be truncated
        # (message is 233 chars, under 300 limit)
        assert "are incompatible with the current constraints" in user_msg, \
            f"Error message should not be truncated. Got: {user_msg}"
        assert not user_msg.endswith("..."), \
            "Message under 300 chars should not have ellipsis"

    def test_very_long_error_messages_truncated_at_300_chars(self):
        """PHASE 1: Test that extremely long messages are truncated at 300 chars."""
        # Arrange
        # Create an error message that's 400 chars long
        very_long_error = "x" * 400
        assert len(very_long_error) == 400

        error = UVCommandError(
            message="UV command failed",
            command=["uv", "sync"],
            stderr=very_long_error,
            stdout="",
            returncode=1
        )

        # Act
        from comfygit_core.utils.uv_error_handler import format_uv_error_for_user
        user_msg = format_uv_error_for_user(error)

        # Assert
        # Should be truncated at 300 chars + ellipsis
        # "UV dependency resolution failed - " is 35 chars, so hint should be ~300 chars
        assert user_msg.endswith("..."), "Very long message should be truncated with ellipsis"
        # Total should be around: "UV dependency resolution failed - " (35) + 300 hint + "..." (3)
        assert len(user_msg) < 350, f"Message should be truncated. Got length: {len(user_msg)}"

    def test_fallback_warning_when_conflict_parsing_fails(self):
        """PHASE 1: Test fallback warning appears when parse_uv_conflicts returns empty.

        Current behavior: Silent failure (no conflicts, no warnings)
        Expected behavior: Adds raw error to warnings as fallback

        This test SHOULD FAIL until Phase 1 is implemented.
        """
        # Arrange
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from comfygit_core.validation.resolution_tester import ResolutionTester

        # Create a minimal test setup
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            tester = ResolutionTester(workspace_path)

            # Create a mock pyproject.toml that will fail
            test_pyproject = workspace_path / "pyproject.toml"
            test_pyproject.write_text("""
[project]
name = "test"
version = "0.1.0"
dependencies = []
            """)

            # Mock uv.sync to raise an exception with unparseable error
            with patch.object(tester, 'uv_cache_path', workspace_path / "uv_cache"):
                with patch.object(tester, 'uv_python_path', workspace_path / "uv" / "python"):
                    # Create a mock UV command that will fail
                    from unittest.mock import MagicMock
                    mock_uv = MagicMock()

                    # Create an error message that parse_uv_conflicts cannot parse
                    unparseable_error = "Some weird error format that doesn't match any regex patterns"
                    mock_uv.sync.side_effect = Exception(unparseable_error)

                    # Patch UVCommand to return our mock
                    with patch('comfygit_core.validation.resolution_tester.UVCommand', return_value=mock_uv):
                        # Act
                        result = tester.test_resolution(test_pyproject)

                        # Assert
                        # CURRENT BEHAVIOR (should fail): No conflicts, no warnings
                        # EXPECTED BEHAVIOR: Should have warning with raw error
                        assert not result.success, "Resolution should fail"

                        # This assertion SHOULD FAIL with current implementation
                        assert len(result.warnings) > 0, \
                            "Should have fallback warning when conflict parsing fails"
                        assert unparseable_error in result.warnings[0], \
                            f"Warning should contain raw error. Got warnings: {result.warnings}"

    def test_fallback_warning_truncates_very_long_errors(self):
        """PHASE 1: Test that fallback warnings truncate extremely long error messages."""
        # Arrange
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from comfygit_core.validation.resolution_tester import ResolutionTester

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            tester = ResolutionTester(workspace_path)

            test_pyproject = workspace_path / "pyproject.toml"
            test_pyproject.write_text("""
[project]
name = "test"
version = "0.1.0"
dependencies = []
            """)

            with patch.object(tester, 'uv_cache_path', workspace_path / "uv_cache"):
                with patch.object(tester, 'uv_python_path', workspace_path / "uv" / "python"):
                    from unittest.mock import MagicMock
                    mock_uv = MagicMock()

                    # Create a 1000-char error message
                    huge_error = "x" * 1000
                    mock_uv.sync.side_effect = Exception(huge_error)

                    with patch('comfygit_core.validation.resolution_tester.UVCommand', return_value=mock_uv):
                        # Act
                        result = tester.test_resolution(test_pyproject)

                        # Assert
                        assert not result.success
                        assert len(result.warnings) > 0, "Should have fallback warning"

                        # Warning should be truncated at 500 chars (per implementation plan)
                        warning_text = result.warnings[0]
                        # Format is "Resolution failed: {error[:500]}"
                        # So total should be around 520 chars max (prefix + 500)
                        assert len(warning_text) < 550, \
                            f"Warning should be truncated. Got length: {len(warning_text)}"
