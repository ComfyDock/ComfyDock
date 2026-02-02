"""Tests for UV error parsing utilities."""

from comfygit_core.utils.uv_error_handler import parse_failed_dependency_group


def test_parse_failed_dependency_group_success():
    """Test parsing failed group from UV build error."""
    stderr = """
  × Failed to build `sageattention==2.2.0`
  ├─▶ The build backend returned an error
  ╰─▶ Call to `setuptools.build_meta.build_wheel` failed (exit status: 1)

      [stderr]
      RuntimeError: Cannot find CUDA_HOME. CUDA must be available to build the package.

      hint: This usually indicates a problem with the package or the build environment.
  help: `sageattention` (v2.2.0) was included because
        `comfygit-env-wan-ati-test:optional-sageattn` (v0.1.0) depends on
        `sageattention>=2.2.0`
"""
    result = parse_failed_dependency_group(stderr)
    assert result == "optional-sageattn"


def test_parse_failed_dependency_group_required_group():
    """Test parsing required (non-optional) group."""
    stderr = """
  help: `some-package` (v1.0.0) was included because
        `test-project:comfyui-node-group` (v0.1.0) depends on
        `some-package>=1.0.0`
"""
    result = parse_failed_dependency_group(stderr)
    assert result == "comfyui-node-group"


def test_parse_failed_dependency_group_no_match():
    """Test when no group pattern found in error."""
    stderr = """
  × Failed to build `some-package==1.0.0`
  ├─▶ The build backend returned an error
"""
    result = parse_failed_dependency_group(stderr)
    assert result is None


def test_parse_failed_dependency_group_empty():
    """Test with empty stderr."""
    assert parse_failed_dependency_group("") is None
    assert parse_failed_dependency_group(None) is None
