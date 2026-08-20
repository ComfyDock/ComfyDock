"""Test provider-specific error handling in ModelDownloader."""

import os
from unittest.mock import Mock

import pytest
from comfygit_core.models.exceptions import DownloadErrorContext
from comfygit_core.services.model_downloader import ModelDownloader
from requests import HTTPError, Response


@pytest.fixture
def mock_workspace_config():
    """Mock workspace config with no API key."""
    config = Mock()
    config.get_civitai_token.return_value = None
    # Mock HF token getter to check env vars (mimics real implementation)
    config.get_huggingface_token.side_effect = lambda: os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    config.get_models_directory.return_value = None
    return config


@pytest.fixture
def mock_workspace_config_with_key():
    """Mock workspace config with CivitAI API key."""
    config = Mock()
    config.get_civitai_token.return_value = "test_api_key_12345"
    # Mock HF token getter to check env vars (mimics real implementation)
    config.get_huggingface_token.side_effect = lambda: os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    config.get_models_directory.return_value = None
    return config


@pytest.fixture
def model_downloader(tmp_path, mock_workspace_config):
    """Create ModelDownloader instance for testing."""
    return ModelDownloader(
        model_repository=Mock(),
        workspace_config=mock_workspace_config,
        models_dir=tmp_path
    )


@pytest.fixture
def model_downloader_with_key(tmp_path, mock_workspace_config_with_key):
    """Create ModelDownloader instance with CivitAI key."""
    return ModelDownloader(
        model_repository=Mock(),
        workspace_config=mock_workspace_config_with_key,
        models_dir=tmp_path
    )


class TestErrorClassification:
    """Test error classification logic."""

    def test_civitai_401_no_key(self, model_downloader):
        """Test CivitAI 401 with no API key configured."""
        # Mock HTTPError with 401
        response = Response()
        response.status_code = 401
        error = HTTPError(response=response)

        context = model_downloader._classify_download_error(
            error=error,
            url="https://civitai.com/api/download/models/12345",
            provider="civitai",
            has_auth=False
        )

        assert context.error_category == "auth_missing"
        assert context.http_status == 401
        assert "API key" in context.get_user_message()
        assert "cg auth set civitai" in context.get_user_message()

    def test_civitai_401_with_key(self, model_downloader):
        """Test CivitAI 401 with API key configured (invalid key)."""
        response = Response()
        response.status_code = 401
        error = HTTPError(response=response)

        context = model_downloader._classify_download_error(
            error=error,
            url="https://civitai.com/api/download/models/12345",
            provider="civitai",
            has_auth=True
        )

        assert context.error_category == "auth_invalid"
        assert "invalid" in context.get_user_message().lower()

    def test_huggingface_403_no_token(self, model_downloader):
        """Test HuggingFace 403 with no token."""
        response = Response()
        response.status_code = 403
        error = HTTPError(response=response)

        context = model_downloader._classify_download_error(
            error=error,
            url="https://huggingface.co/model/file.safetensors",
            provider="huggingface",
            has_auth=False
        )

        assert context.error_category == "auth_missing"
        assert "HF_TOKEN" in context.get_user_message()

    def test_civitai_403_with_key(self, model_downloader):
        """Test CivitAI 403 with key (forbidden/rate limit)."""
        response = Response()
        response.status_code = 403
        error = HTTPError(response=response)

        context = model_downloader._classify_download_error(
            error=error,
            url="https://civitai.com/api/download/models/12345",
            provider="civitai",
            has_auth=True
        )

        assert context.error_category == "forbidden"
        assert "forbidden" in context.get_user_message().lower()

    def test_404_error(self, model_downloader):
        """Test 404 not found error."""
        response = Response()
        response.status_code = 404
        error = HTTPError(response=response)

        context = model_downloader._classify_download_error(
            error=error,
            url="https://civitai.com/api/download/models/99999",
            provider="civitai",
            has_auth=True
        )

        assert context.error_category == "not_found"
        assert "not found" in context.get_user_message().lower()

    def test_500_server_error(self, model_downloader):
        """Test 500 server error."""
        response = Response()
        response.status_code = 500
        error = HTTPError(response=response)

        context = model_downloader._classify_download_error(
            error=error,
            url="https://civitai.com/api/download/models/12345",
            provider="civitai",
            has_auth=True
        )

        assert context.error_category == "server"
        assert "server error" in context.get_user_message().lower()

    def test_network_timeout(self, model_downloader):
        """Test network timeout error."""
        from requests import Timeout
        error = Timeout("Connection timeout")

        context = model_downloader._classify_download_error(
            error=error,
            url="https://example.com/model.safetensors",
            provider="custom",
            has_auth=False
        )

        assert context.error_category == "network"
        assert "network" in context.get_user_message().lower()

    def test_connection_error(self, model_downloader):
        """Test connection error."""
        from requests import ConnectionError
        error = ConnectionError("Failed to establish connection")

        context = model_downloader._classify_download_error(
            error=error,
            url="https://example.com/model.safetensors",
            provider="custom",
            has_auth=False
        )

        assert context.error_category == "network"
        assert "network" in context.get_user_message().lower()


class TestProviderAuthCheck:
    """Test provider authentication detection."""

    def test_civitai_has_key(self, model_downloader_with_key):
        """Test CivitAI auth detection when key is configured."""
        assert model_downloader_with_key._check_provider_auth("civitai") is True

    def test_civitai_no_key(self, model_downloader):
        """Test CivitAI auth detection when no key."""
        assert model_downloader._check_provider_auth("civitai") is False

    def test_civitai_empty_key(self, tmp_path):
        """Test CivitAI auth detection with empty/whitespace key."""
        config = Mock()
        config.get_civitai_token.return_value = "   "  # Whitespace only
        config.get_models_directory.return_value = None

        downloader = ModelDownloader(
            model_repository=Mock(),
            workspace_config=config,
            models_dir=tmp_path
        )

        assert downloader._check_provider_auth("civitai") is False

    def test_huggingface_has_token(self, model_downloader, monkeypatch):
        """Test HuggingFace auth detection when HF_TOKEN is set."""
        monkeypatch.setenv("HF_TOKEN", "hf_test_token")
        assert model_downloader._check_provider_auth("huggingface") is True

    def test_huggingface_alternative_token(self, model_downloader, monkeypatch):
        """Test HuggingFace auth detection with alternative env var."""
        monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "hf_test_token")
        assert model_downloader._check_provider_auth("huggingface") is True

    def test_huggingface_no_token(self, model_downloader, monkeypatch):
        """Test HuggingFace auth detection when no token."""
        # Clear any env vars
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
        assert model_downloader._check_provider_auth("huggingface") is False

    def test_custom_provider_no_auth(self, model_downloader):
        """Test custom provider always returns False."""
        assert model_downloader._check_provider_auth("custom") is False


class TestErrorContextMessages:
    """Test error context message generation."""

    def test_civitai_auth_missing_message(self):
        """Test CivitAI auth missing message."""
        context = DownloadErrorContext(
            provider="civitai",
            error_category="auth_missing",
            http_status=401,
            url="https://civitai.com/api/download/models/12345",
            has_configured_auth=False,
            raw_error="401 Unauthorized"
        )

        message = context.get_user_message()
        assert "CivitAI" in message
        assert "authentication" in message.lower()
        assert "No API key found" in message
        assert "cg auth set civitai" in message
        assert "https://civitai.com/user/account" in message

    def test_civitai_auth_invalid_message(self):
        """Test CivitAI invalid auth message."""
        context = DownloadErrorContext(
            provider="civitai",
            error_category="auth_invalid",
            http_status=401,
            url="https://civitai.com/api/download/models/12345",
            has_configured_auth=True,
            raw_error="401 Unauthorized"
        )

        message = context.get_user_message()
        assert "invalid" in message.lower() or "expired" in message.lower()
        assert "cg auth set civitai" in message

    def test_huggingface_auth_message(self):
        """Test HuggingFace auth message."""
        context = DownloadErrorContext(
            provider="huggingface",
            error_category="auth_missing",
            http_status=403,
            url="https://huggingface.co/model/file.safetensors",
            has_configured_auth=False,
            raw_error="403 Forbidden"
        )

        message = context.get_user_message()
        assert "HuggingFace" in message
        assert "HF_TOKEN" in message
        assert "https://huggingface.co/settings/tokens" in message

    def test_network_error_message(self):
        """Test network error message."""
        context = DownloadErrorContext(
            provider="custom",
            error_category="network",
            http_status=None,
            url="https://example.com/model.safetensors",
            has_configured_auth=False,
            raw_error="Connection timeout"
        )

        message = context.get_user_message()
        assert "network" in message.lower()
        assert "timeout" in message.lower()

    def test_server_error_message(self):
        """Test server error message."""
        context = DownloadErrorContext(
            provider="civitai",
            error_category="server",
            http_status=500,
            url="https://civitai.com/api/download/models/12345",
            has_configured_auth=True,
            raw_error="500 Internal Server Error"
        )

        message = context.get_user_message()
        assert "server error" in message.lower()
        assert "500" in message
        assert "try again later" in message.lower()
