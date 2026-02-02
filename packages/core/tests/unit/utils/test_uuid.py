"""Unit tests for UUID detection utility."""
from comfygit_core.utils.uuid import is_uuid


class TestIsUuid:
    """Test UUID pattern matching for subgraph references."""

    def test_valid_uuid_lowercase(self):
        """Valid lowercase UUID should be recognized."""
        assert is_uuid("0a58ac1f-cb15-4e01-aab3-26292addb965") is True

    def test_valid_uuid_uppercase(self):
        """Valid uppercase UUID should be recognized."""
        assert is_uuid("0A58AC1F-CB15-4E01-AAB3-26292ADDB965") is True

    def test_valid_uuid_mixed_case(self):
        """Valid mixed-case UUID should be recognized."""
        assert is_uuid("A0ce3421-E264-4b7a-8B6f-E6e20e7fa9aa") is True

    def test_invalid_node_type(self):
        """Node type names should not be recognized as UUIDs."""
        assert is_uuid("CheckpointLoaderSimple") is False
        assert is_uuid("KSampler") is False
        assert is_uuid("SaveImage") is False

    def test_invalid_malformed_uuid(self):
        """Malformed UUIDs should not be recognized."""
        assert is_uuid("not-a-valid-uuid") is False
        assert is_uuid("12345678-1234-1234-1234-12345678901") is False  # too short (11 instead of 12)
        assert is_uuid("g0000000-0000-0000-0000-000000000000") is False  # invalid char 'g'

    def test_empty_and_edge_cases(self):
        """Edge cases should be handled correctly."""
        assert is_uuid("") is False
        assert is_uuid("0a58ac1f-cb15-4e01-aab3") is False  # incomplete
        assert is_uuid("0a58ac1f-cb15-4e01-aab3-26292addb965-extra") is False  # too long
