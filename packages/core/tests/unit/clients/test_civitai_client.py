"""Tests for CivitAI API client."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from comfygit_core.caching.api_cache import APICacheManager
from comfygit_core.clients.civitai_client import CivitAIClient
from comfygit_core.models.civitai import ModelType, SearchParams, SortOrder


@pytest.fixture
def cache_manager():
    """Create a temporary cache manager for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield APICacheManager(cache_base_path=Path(tmpdir))


class TestCivitAIClient:
    """Test CivitAI client functionality."""

    def test_client_initialization_with_api_key(self, cache_manager):
        """Test client initializes with direct API key."""
        client = CivitAIClient(cache_manager=cache_manager, api_key="test-api-key")
        assert client._api_key == "test-api-key"

    @patch.dict("os.environ", {"CIVITAI_API_TOKEN": "env-api-key"})
    def test_client_uses_environment_token(self, cache_manager):
        """Test client uses environment variable when no direct key provided."""
        client = CivitAIClient(cache_manager=cache_manager)
        assert client._api_key == "env-api-key"

    @patch("urllib.request.urlopen")
    def test_search_models_basic(self, mock_urlopen, cache_manager):
        """Test basic model search functionality."""
        # Mock API response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "items": [
                {
                    "id": 123,
                    "name": "Test Model",
                    "type": "LORA",
                    "nsfw": False,
                    "tags": ["anime", "style"],
                    "stats": {
                        "downloadCount": 1000,
                        "rating": 4.5
                    },
                    "creator": {
                        "username": "testuser"
                    },
                    "modelVersions": []
                }
            ],
            "metadata": {
                "totalItems": "1",
                "currentPage": "1",
                "pageSize": "20",
                "totalPages": "1"
            }
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        client = CivitAIClient(cache_manager=cache_manager)
        response = client.search_models(query="anime", limit=10)

        assert len(response.items) == 1
        assert response.items[0].name == "Test Model"
        assert response.items[0].id == 123
        assert response.total_items == 1

    def test_search_params_to_dict(self):
        """Test SearchParams converts to query dict correctly."""
        params = SearchParams(
            query="anime girl",
            types=[ModelType.LORA, ModelType.CHECKPOINT],
            sort=SortOrder.MOST_DOWNLOADED,
            limit=50,
            nsfw=False
        )

        result = params.to_dict()

        assert result["query"] == "anime girl"
        assert result["types"] == "LORA,Checkpoint"
        assert result["sort"] == "Most Downloaded"
        assert result["limit"] == 50
        assert result["nsfw"] == "false"

    def test_hash_algorithm_detection(self, cache_manager):
        """Test automatic hash algorithm detection."""
        client = CivitAIClient(cache_manager=cache_manager)

        assert client._detect_hash_algorithm("12345678") == "CRC32"
        assert client._detect_hash_algorithm("1234567890") == "AutoV1"
        assert client._detect_hash_algorithm("123456789012") == "AutoV2"
        assert client._detect_hash_algorithm("a" * 64) == "SHA256"
        assert client._detect_hash_algorithm("b" * 128) == "Blake3"

    def test_download_url_generation(self, cache_manager):
        """Test download URL generation with parameters."""
        client = CivitAIClient(cache_manager=cache_manager, api_key="test-token")

        url = client.get_download_url(
            version_id=12345,
            file_format="SafeTensor",
            size="pruned",
            fp="fp16"
        )

        assert "12345" in url
        assert "format=SafeTensor" in url
        assert "size=pruned" in url
        assert "fp=fp16" in url
        assert "token=test-token" in url
