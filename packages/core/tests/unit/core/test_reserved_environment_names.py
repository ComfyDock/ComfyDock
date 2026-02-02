"""Unit tests for reserved environment name validation."""

import pytest
from comfygit_core.models.exceptions import CDEnvironmentError


def test_reserved_name_workspace():
    """Environment name 'workspace' should be rejected as reserved."""
    # Test the validation helper directly without creating workspace
    from comfygit_core.core.workspace import _validate_environment_name

    with pytest.raises(CDEnvironmentError, match="reserved"):
        _validate_environment_name("workspace")


def test_reserved_name_logs():
    """Environment name 'logs' should be rejected as reserved."""
    from comfygit_core.core.workspace import _validate_environment_name

    with pytest.raises(CDEnvironmentError, match="reserved"):
        _validate_environment_name("logs")


def test_reserved_name_models():
    """Environment name 'models' should be rejected as reserved."""
    from comfygit_core.core.workspace import _validate_environment_name

    with pytest.raises(CDEnvironmentError, match="reserved"):
        _validate_environment_name("models")


def test_reserved_name_dotcomfydock():
    """Environment name '.comfygit' should be rejected as reserved."""
    from comfygit_core.core.workspace import _validate_environment_name

    with pytest.raises(CDEnvironmentError, match="reserved"):
        _validate_environment_name(".comfygit")


def test_reserved_name_case_insensitive():
    """Reserved names should be case-insensitive."""
    from comfygit_core.core.workspace import _validate_environment_name

    with pytest.raises(CDEnvironmentError, match="reserved"):
        _validate_environment_name("WORKSPACE")

    with pytest.raises(CDEnvironmentError, match="reserved"):
        _validate_environment_name("Logs")


def test_hidden_directory_rejected():
    """Names starting with '.' should be rejected."""
    from comfygit_core.core.workspace import _validate_environment_name

    with pytest.raises(CDEnvironmentError, match="cannot start with"):
        _validate_environment_name(".hidden")


def test_path_separator_rejected():
    """Names with path separators should be rejected."""
    from comfygit_core.core.workspace import _validate_environment_name

    with pytest.raises(CDEnvironmentError, match="path separators"):
        _validate_environment_name("foo/bar")

    with pytest.raises(CDEnvironmentError, match="path separators"):
        _validate_environment_name("foo\\bar")


def test_path_traversal_rejected():
    """Names with '..' should be rejected."""
    from comfygit_core.core.workspace import _validate_environment_name

    with pytest.raises(CDEnvironmentError, match="path separators"):
        _validate_environment_name("foo..bar")

    with pytest.raises(CDEnvironmentError, match="path separators"):
        _validate_environment_name("..")


def test_empty_name_rejected():
    """Empty names should be rejected."""
    from comfygit_core.core.workspace import _validate_environment_name

    with pytest.raises(CDEnvironmentError, match="cannot be empty"):
        _validate_environment_name("")

    with pytest.raises(CDEnvironmentError, match="cannot be empty"):
        _validate_environment_name("   ")


def test_valid_name_allowed():
    """Valid environment names should be accepted."""
    from comfygit_core.core.workspace import _validate_environment_name

    # These should NOT raise
    _validate_environment_name("my-env")
    _validate_environment_name("test123")
    _validate_environment_name("prod_environment")
