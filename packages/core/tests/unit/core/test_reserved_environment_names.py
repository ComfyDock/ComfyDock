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


def test_reserved_name_dotcomfygit():
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


def test_spaces_rejected():
    """Names with spaces should be rejected."""
    from comfygit_core.core.workspace import _validate_environment_name

    with pytest.raises(CDEnvironmentError, match="Invalid environment name"):
        _validate_environment_name("my environment")

    with pytest.raises(CDEnvironmentError, match="Invalid environment name"):
        _validate_environment_name("My Cool Workflow")


def test_special_characters_rejected():
    """Names with special characters should be rejected."""
    from comfygit_core.core.workspace import _validate_environment_name

    for char in ["@", "#", "$", "%", "!", "=", "[", "]", "{", "}", "(", ")", "&", "+", ",", ";", ":", "~", "`", "'", '"']:
        with pytest.raises(CDEnvironmentError):
            _validate_environment_name(f"env{char}name")


def test_must_start_and_end_with_alphanumeric():
    """Names must start and end with a letter or digit."""
    from comfygit_core.core.workspace import _validate_environment_name

    with pytest.raises(CDEnvironmentError, match="Must start and end"):
        _validate_environment_name("-leading-hyphen")

    with pytest.raises(CDEnvironmentError, match="Must start and end"):
        _validate_environment_name("trailing-hyphen-")

    with pytest.raises(CDEnvironmentError, match="Must start and end"):
        _validate_environment_name("_leading-underscore")

    with pytest.raises(CDEnvironmentError, match="Must start and end"):
        _validate_environment_name("trailing-underscore_")


def test_name_too_long():
    """Names exceeding max length should be rejected."""
    from comfygit_core.core.workspace import _validate_environment_name

    with pytest.raises(CDEnvironmentError, match="too long"):
        _validate_environment_name("a" * 129)

    # Exactly at limit should be fine
    _validate_environment_name("a" * 128)


def test_single_character_name():
    """Single character names should be valid if alphanumeric."""
    from comfygit_core.core.workspace import _validate_environment_name

    _validate_environment_name("a")
    _validate_environment_name("Z")
    _validate_environment_name("5")


def test_valid_name_allowed():
    """Valid environment names should be accepted."""
    from comfygit_core.core.workspace import _validate_environment_name

    # These should NOT raise
    _validate_environment_name("my-env")
    _validate_environment_name("test123")
    _validate_environment_name("prod_environment")
    _validate_environment_name("VibeVoice-Workflows")
    _validate_environment_name("cuda-cu118")
    _validate_environment_name("snapshot.backup")
    _validate_environment_name("v2.0-beta")
    _validate_environment_name("My-Workflow-v3")
