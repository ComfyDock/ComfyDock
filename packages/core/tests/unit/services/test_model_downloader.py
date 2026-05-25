"""Unit tests for ModelDownloader service."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from comfygit_core.services.model_downloader import (
    DownloadRequest,
    DownloadResult,
    ModelDownloader,
)


class TestModelDownloader:
    """Test ModelDownloader service."""

    def test_download_request_creation(self):
        """Test creating a DownloadRequest."""
        request = DownloadRequest(
            url="https://example.com/model.safetensors",
            target_path=Path("/models/checkpoints/model.safetensors"),
            workflow_name="test_workflow"
        )

        assert request.url == "https://example.com/model.safetensors"
        assert request.target_path == Path("/models/checkpoints/model.safetensors")
        assert request.workflow_name == "test_workflow"

    def test_download_result_success(self):
        """Test successful DownloadResult."""
        result = DownloadResult(
            success=True,
            model=None,
            error=None
        )

        assert result.success is True
        assert result.model is None
        assert result.error is None

    def test_download_result_failure(self):
        """Test failed DownloadResult."""
        result = DownloadResult(
            success=False,
            model=None,
            error="Connection timeout"
        )

        assert result.success is False
        assert result.error == "Connection timeout"

    def test_detect_url_type_civitai(self, tmp_path):
        """Test detecting CivitAI URLs."""
        repo = Mock()
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        downloader = ModelDownloader(repo, workspace_config)

        assert downloader.detect_url_type("https://civitai.com/api/download/models/123") == "civitai"
        assert downloader.detect_url_type("https://civitai.com/models/456") == "civitai"

    def test_detect_url_type_huggingface(self, tmp_path):
        """Test detecting HuggingFace URLs."""
        repo = Mock()
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        downloader = ModelDownloader(repo, workspace_config)

        assert downloader.detect_url_type("https://huggingface.co/user/model/blob/main/file.safetensors") == "huggingface"
        assert downloader.detect_url_type("https://hf.co/model/file") == "huggingface"

    def test_detect_url_type_custom(self, tmp_path):
        """Test detecting custom/direct URLs."""
        repo = Mock()
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        downloader = ModelDownloader(repo, workspace_config)

        assert downloader.detect_url_type("https://example.com/model.safetensors") == "custom"
        assert downloader.detect_url_type("https://cdn.example.org/files/model.ckpt") == "custom"
        assert downloader.detect_url_type("https://example.com/model.safetensors?next=civitai.com") == "custom"

    def test_suggest_path_with_known_node(self, tmp_path):
        """Test path suggestion for known loader nodes."""
        repo = Mock()
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        downloader = ModelDownloader(repo, workspace_config)

        # CheckpointLoader should suggest checkpoints/
        path = downloader.suggest_path(
            url="https://example.com/sd15.safetensors",
            node_type="CheckpointLoaderSimple",
            filename_hint="sd15.safetensors"
        )

        assert path == Path("checkpoints/sd15.safetensors")

    def test_suggest_path_with_lora_loader(self, tmp_path):
        """Test path suggestion for LoraLoader."""
        repo = Mock()
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        downloader = ModelDownloader(repo, workspace_config)

        path = downloader.suggest_path(
            url="https://example.com/style.safetensors",
            node_type="LoraLoader",
            filename_hint="style.safetensors"
        )

        assert path == Path("loras/style.safetensors")

    def test_suggest_path_extracts_filename_from_url(self, tmp_path):
        """Test extracting filename from URL path."""
        repo = Mock()
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        downloader = ModelDownloader(repo, workspace_config)

        path = downloader.suggest_path(
            url="https://example.com/downloads/model.safetensors",
            node_type="CheckpointLoaderSimple",
            filename_hint=None
        )

        # Should extract "model.safetensors" from URL
        assert path.name == "model.safetensors"
        assert path.parts[0] == "checkpoints"

    def test_download_checks_existing_url(self, tmp_path):
        """Test that download checks for existing models by URL before downloading."""
        from comfygit_core.models.shared import ModelWithLocation

        repo = Mock()
        existing_model = ModelWithLocation(
            hash="abc123",
            file_size=1024000,
            blake3_hash="abc123def456",
            sha256_hash=None,
            relative_path="checkpoints/existing.safetensors",
            filename="existing.safetensors",
            mtime=1234567890.0,
            last_seen=1234567890,
            metadata={}
        )
        repo.find_by_source_url.return_value = existing_model

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        downloader = ModelDownloader(repo, workspace_config)
        request = DownloadRequest(
            url="https://example.com/model.safetensors",
            target_path=tmp_path / "checkpoints/model.safetensors"
        )

        # Download should check for existing URL and return it
        result = downloader.download(request)

        repo.find_by_source_url.assert_called_once_with("https://example.com/model.safetensors")
        assert result.success is True
        assert result.model == existing_model

    @patch('requests.get')
    def test_download_new_model_success(self, mock_get, tmp_path):
        """Test downloading a new model successfully."""
        # Setup mock HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-length': '1024'}
        mock_response.iter_content = Mock(return_value=[b"test" * 256])
        mock_get.return_value = mock_response

        # Setup repository mock
        repo = Mock()
        repo.find_by_source_url.return_value = None  # No existing model

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        downloader = ModelDownloader(repo, workspace_config)
        target_path = tmp_path / "checkpoints/new_model.safetensors"
        request = DownloadRequest(
            url="https://example.com/new_model.safetensors",
            target_path=target_path
        )

        result = downloader.download(request)

        # Verify HTTP request was made with proper timeout
        # (30s connection timeout, no read timeout for large downloads)
        mock_get.assert_called_once_with(
            "https://example.com/new_model.safetensors",
            stream=True,
            timeout=(30, None),
            headers={}
        )

        # Verify file was created
        assert target_path.exists()

        # Verify model was indexed
        assert repo.ensure_model.called
        assert repo.add_location.called
        assert repo.add_source.called

        assert result.success is True
        assert result.model is not None
        assert result.error is None

    @patch('requests.get')
    def test_download_handles_http_errors(self, mock_get, tmp_path):
        """Test download handles HTTP errors gracefully."""
        # Setup mock to raise exception
        mock_get.side_effect = Exception("Connection timeout")

        repo = Mock()
        repo.find_by_source_url.return_value = None

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        downloader = ModelDownloader(repo, workspace_config)
        request = DownloadRequest(
            url="https://example.com/model.safetensors",
            target_path=tmp_path / "checkpoints/model.safetensors"
        )

        result = downloader.download(request)

        assert result.success is False
        assert "Connection timeout" in result.error
        assert result.model is None

    @patch('requests.get')
    def test_download_computes_hash_during_download(self, mock_get, tmp_path):
        """Test that hash is computed during download (streaming)."""
        # Setup mock with known content
        test_content = b"test_model_content" * 1000
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-length': str(len(test_content))}

        # Split into chunks for streaming
        chunk_size = 8192
        chunks = [test_content[i:i+chunk_size] for i in range(0, len(test_content), chunk_size)]
        mock_response.iter_content = Mock(return_value=chunks)
        mock_get.return_value = mock_response

        repo = Mock()
        repo.find_by_source_url.return_value = None
        repo.calculate_short_hash.return_value = "abc123def456"  # Mock short hash

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        downloader = ModelDownloader(repo, workspace_config)
        target_path = tmp_path / "checkpoints/test.safetensors"
        request = DownloadRequest(
            url="https://example.com/test.safetensors",
            target_path=target_path
        )

        result = downloader.download(request)

        assert result.success is True

        # Verify ensure_model was called with hash
        assert repo.ensure_model.called
        call_kwargs = repo.ensure_model.call_args[1]
        assert 'hash' in call_kwargs  # Hash should be provided
        assert call_kwargs['hash'] == "abc123def456"

    def test_download_uses_temp_file_then_atomic_move(self, tmp_path):
        """Test that download uses temp file and atomic move for safety."""
        # This test will be implemented when we add the actual download logic
        # For now, just verify the pattern is intended
        pass

    def test_suggest_path_without_node_type_uses_hint(self, tmp_path):
        """Test path suggestion falls back to filename hint when node type unknown."""
        repo = Mock()
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        downloader = ModelDownloader(repo, workspace_config)

        # Unknown node type - should use filename hint directly
        path = downloader.suggest_path(
            url="https://example.com/file.safetensors",
            node_type=None,
            filename_hint="models/custom/file.safetensors"
        )

        # Should use the hint path
        assert "file.safetensors" in str(path)

    @patch('requests.get')
    def test_download_calls_progress_callback(self, mock_get, tmp_path):
        """Test that download calls progress callback with current and total bytes."""
        # Setup mock with known content
        test_content = b"x" * 10000
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-length': '10000'}

        # Split into chunks for streaming
        chunk_size = 8192
        chunks = [test_content[i:i+chunk_size] for i in range(0, len(test_content), chunk_size)]
        mock_response.iter_content = Mock(return_value=chunks)
        mock_get.return_value = mock_response

        repo = Mock()
        repo.find_by_source_url.return_value = None
        repo.calculate_short_hash.return_value = "test123"

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        downloader = ModelDownloader(repo, workspace_config)
        request = DownloadRequest(
            url="https://example.com/test.safetensors",
            target_path=tmp_path / "checkpoints/test.safetensors"
        )

        # Track progress callback calls
        progress_calls = []
        def track_progress(downloaded, total):
            progress_calls.append((downloaded, total))

        result = downloader.download(request, progress_callback=track_progress)

        # Verify callback was called with proper arguments
        assert result.success is True
        assert len(progress_calls) > 0

        # All calls should have total=10000
        for downloaded, total in progress_calls:
            assert total == 10000
            assert downloaded > 0

        # Final call should have all bytes
        assert progress_calls[-1][0] == 10000

    def test_accepts_workspace_config_parameter(self, tmp_path):
        """Test that ModelDownloader accepts workspace_config parameter."""
        repo = Mock()
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path

        # Should not raise exception
        downloader = ModelDownloader(repo, workspace_config)

        assert downloader.workspace_config == workspace_config

    def test_models_dir_override(self, tmp_path):
        """Test that models_dir can be overridden."""
        repo = Mock()
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path / "default"

        override_dir = tmp_path / "override"
        downloader = ModelDownloader(repo, workspace_config, models_dir=override_dir)

        # Should use override, not config value
        assert downloader.models_dir == override_dir

    def test_models_dir_from_workspace_config(self, tmp_path):
        """Test that models_dir comes from workspace_config when not overridden."""
        repo = Mock()
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path

        downloader = ModelDownloader(repo, workspace_config)

        assert downloader.models_dir == tmp_path

    def test_raises_error_if_no_models_dir_available(self):
        """Test that ModelDownloader raises error if models_dir is None."""
        repo = Mock()
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = None

        with pytest.raises(ValueError, match="No models directory available"):
            ModelDownloader(repo, workspace_config)

    @patch('requests.get')
    def test_civitai_url_gets_auth_header_with_api_key(self, mock_get, tmp_path):
        """Test that Civitai URLs get Authorization header when API key is configured."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-length': '1024'}
        mock_response.iter_content = Mock(return_value=[b"test" * 256])
        mock_get.return_value = mock_response

        # Setup workspace config with API key
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        workspace_config.get_civitai_token.return_value = "test_api_key_12345"

        repo = Mock()
        repo.find_by_source_url.return_value = None
        repo.calculate_short_hash.return_value = "abc123"

        downloader = ModelDownloader(repo, workspace_config)
        request = DownloadRequest(
            url="https://civitai.com/api/download/models/123456",
            target_path=tmp_path / "loras/model.safetensors"
        )

        result = downloader.download(request)

        # Verify Authorization header was added
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert 'headers' in call_kwargs
        assert call_kwargs['headers'] == {'Authorization': 'Bearer test_api_key_12345'}
        assert result.success is True

    @patch('requests.get')
    def test_civitai_url_no_auth_header_without_api_key(self, mock_get, tmp_path):
        """Test that Civitai URLs work without auth header when API key returns None."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-length': '1024'}
        mock_response.iter_content = Mock(return_value=[b"test" * 256])
        mock_get.return_value = mock_response

        # Workspace config with no API key
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        workspace_config.get_civitai_token.return_value = None

        repo = Mock()
        repo.find_by_source_url.return_value = None
        repo.calculate_short_hash.return_value = "abc123"

        downloader = ModelDownloader(repo, workspace_config)
        request = DownloadRequest(
            url="https://civitai.com/api/download/models/123456",
            target_path=tmp_path / "loras/model.safetensors"
        )

        result = downloader.download(request)

        # Verify no Authorization header (empty headers dict)
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert 'headers' in call_kwargs
        assert call_kwargs['headers'] == {}
        assert result.success is True

    @patch('requests.get')
    def test_civitai_url_no_auth_header_when_api_key_is_none(self, mock_get, tmp_path):
        """Test that Civitai URLs work when workspace_config returns None for API key."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-length': '1024'}
        mock_response.iter_content = Mock(return_value=[b"test" * 256])
        mock_get.return_value = mock_response

        # Workspace config exists but returns None for API key
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        workspace_config.get_civitai_token.return_value = None

        repo = Mock()
        repo.find_by_source_url.return_value = None
        repo.calculate_short_hash.return_value = "abc123"

        downloader = ModelDownloader(repo, workspace_config)
        request = DownloadRequest(
            url="https://civitai.com/api/download/models/123456",
            target_path=tmp_path / "loras/model.safetensors"
        )

        result = downloader.download(request)

        # Verify no Authorization header (empty headers dict)
        workspace_config.get_civitai_token.assert_called_once()
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert 'headers' in call_kwargs
        assert call_kwargs['headers'] == {}
        assert result.success is True

    @patch('requests.get')
    def test_custom_url_no_auth_header_even_with_civitai_api_key(self, mock_get, tmp_path):
        """Test that custom URLs don't get Civitai auth header even when API key is configured."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-length': '1024'}
        mock_response.iter_content = Mock(return_value=[b"test" * 256])
        mock_get.return_value = mock_response

        # Workspace config with Civitai API key
        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        workspace_config.get_civitai_token.return_value = "test_api_key_12345"

        repo = Mock()
        repo.find_by_source_url.return_value = None
        repo.calculate_short_hash.return_value = "abc123"

        downloader = ModelDownloader(repo, workspace_config)
        request = DownloadRequest(
            url="https://example.com/models/file.safetensors",
            target_path=tmp_path / "checkpoints/model.safetensors"
        )

        result = downloader.download(request)

        # Verify no Authorization header for custom URL (not Civitai)
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert 'headers' in call_kwargs
        assert call_kwargs['headers'] == {}  # Empty, no auth header
        assert result.success is True

    @patch('requests.get')
    def test_custom_url_query_mentioning_civitai_gets_no_auth_header(self, mock_get, tmp_path):
        """CivitAI auth should be based on URL host, not full-string containment."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-length': '1024'}
        mock_response.iter_content = Mock(return_value=[b"test" * 256])
        mock_get.return_value = mock_response

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        workspace_config.get_civitai_token.return_value = "test_api_key_12345"

        repo = Mock()
        repo.find_by_source_url.return_value = None
        repo.calculate_short_hash.return_value = "abc123"

        downloader = ModelDownloader(repo, workspace_config)
        request = DownloadRequest(
            url="https://example.com/models/file.safetensors?redirect=https://civitai.com/api/download/models/1",
            target_path=tmp_path / "checkpoints/model.safetensors"
        )

        result = downloader.download(request)

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert 'headers' in call_kwargs
        assert call_kwargs['headers'] == {}
        workspace_config.get_civitai_token.assert_not_called()
        assert result.success is True

    @patch('requests.get')
    def test_civitai_url_case_insensitive(self, mock_get, tmp_path):
        """Test that Civitai URL detection is case-insensitive."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-length': '1024'}
        mock_response.iter_content = Mock(return_value=[b"test" * 256])
        mock_get.return_value = mock_response

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        workspace_config.get_civitai_token.return_value = "test_key"

        repo = Mock()
        repo.find_by_source_url.return_value = None
        repo.calculate_short_hash.return_value = "abc123"

        downloader = ModelDownloader(repo, workspace_config)

        # Test with different case variations
        for url in [
            "https://CIVITAI.COM/api/download/models/123",
            "https://CivitAI.com/api/download/models/123",
            "https://civitai.COM/api/download/models/123"
        ]:
            mock_get.reset_mock()
            request = DownloadRequest(
                url=url,
                target_path=tmp_path / "loras/test.safetensors"
            )

            result = downloader.download(request)

            # All should get auth header
            call_kwargs = mock_get.call_args[1]
            assert call_kwargs['headers'] == {'Authorization': 'Bearer test_key'}
            assert result.success is True


class TestModelDownloaderHuggingFaceFallback:
    """Tests for HuggingFace tqdm_class graceful degradation."""

    @patch('comfygit_core.services.model_downloader.hf_hub_download')
    @patch('comfygit_core.services.model_downloader.parse_huggingface_url')
    def test_hf_download_uses_local_dir_mode(self, mock_parse, mock_hf_download, tmp_path):
        """HF downloads should use local_dir mode to avoid blob cache duplication."""
        from comfygit_core.services.huggingface_url import ParsedHuggingFaceUrl

        mock_parse.return_value = ParsedHuggingFaceUrl(
            kind="file",
            repo_id="user/model",
            path_in_repo="model.safetensors",
            revision="main",
        )

        def side_effect(**kwargs):
            local_file = Path(kwargs["local_dir"]) / kwargs["filename"]
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_bytes(b"model_data")
            return str(local_file)

        mock_hf_download.side_effect = side_effect

        repo = Mock()
        repo.find_by_source_url.return_value = None
        repo.calculate_short_hash.return_value = "abc123"

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        workspace_config.get_huggingface_token.return_value = None

        downloader = ModelDownloader(repo, workspace_config)
        target_path = tmp_path / "checkpoints" / "model.safetensors"

        request = DownloadRequest(
            url="https://huggingface.co/user/model/resolve/main/model.safetensors",
            target_path=target_path
        )

        result = downloader.download(request)

        assert result.success is True
        call_kwargs = mock_hf_download.call_args.kwargs
        assert call_kwargs["local_dir"] == str(tmp_path / "checkpoints")
        assert "cache_dir" not in call_kwargs
        assert target_path.exists()

    @patch('comfygit_core.services.model_downloader.hf_hub_download')
    @patch('comfygit_core.services.model_downloader.parse_huggingface_url')
    def test_hf_download_indexes_symlinked_models_mount(self, mock_parse, mock_hf_download, tmp_path):
        """HF downloads should index files when a mount resolves to a backing path."""
        from comfygit_core.services.huggingface_url import ParsedHuggingFaceUrl

        backing_models = tmp_path / "__modal" / "volumes" / "vo-test" / "models"
        mount_models = tmp_path / "volume" / "models"
        backing_models.mkdir(parents=True)
        mount_models.parent.mkdir(parents=True)
        mount_models.symlink_to(backing_models, target_is_directory=True)

        mock_parse.return_value = ParsedHuggingFaceUrl(
            kind="file",
            repo_id="user/model",
            path_in_repo="model.safetensors",
            revision="main",
        )

        def side_effect(**kwargs):
            local_file = Path(kwargs["local_dir"]) / kwargs["filename"]
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_bytes(b"model_data")
            return str(local_file.resolve())

        mock_hf_download.side_effect = side_effect

        repo = Mock()
        repo.find_by_source_url.return_value = None
        repo.calculate_short_hash.return_value = "abc123"

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = mount_models
        workspace_config.get_huggingface_token.return_value = None

        downloader = ModelDownloader(repo, workspace_config)
        target_path = mount_models / "checkpoints" / "model.safetensors"

        request = DownloadRequest(
            url="https://huggingface.co/user/model/resolve/main/model.safetensors",
            target_path=target_path
        )

        result = downloader.download(request)

        assert result.success is True
        assert result.model.relative_path == "checkpoints/model.safetensors"
        assert target_path.exists()
        assert target_path.resolve().is_file()
        repo.add_location.assert_called_once()
        assert repo.add_location.call_args.kwargs["base_directory"] == mount_models
        assert repo.add_location.call_args.kwargs["relative_path"] == "checkpoints/model.safetensors"

    @patch('comfygit_core.services.model_downloader.hf_hub_download')
    @patch('comfygit_core.services.model_downloader.parse_huggingface_url')
    def test_hf_download_handles_repo_path_target_path_mismatch(self, mock_parse, mock_hf_download, tmp_path):
        """HF downloads should still materialize at target_path when repo path differs."""
        from comfygit_core.services.huggingface_url import ParsedHuggingFaceUrl

        mock_parse.return_value = ParsedHuggingFaceUrl(
            kind="file",
            repo_id="user/model",
            path_in_repo="subdir/model.safetensors",
            revision="main",
        )

        def side_effect(**kwargs):
            local_file = Path(kwargs["local_dir"]) / kwargs["filename"]
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_bytes(b"model_data")
            return str(local_file)

        mock_hf_download.side_effect = side_effect

        repo = Mock()
        repo.find_by_source_url.return_value = None
        repo.calculate_short_hash.return_value = "abc123"

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        workspace_config.get_huggingface_token.return_value = None

        downloader = ModelDownloader(repo, workspace_config)
        target_path = tmp_path / "clip" / "model.safetensors"

        request = DownloadRequest(
            url="https://huggingface.co/user/model/resolve/main/subdir/model.safetensors",
            target_path=target_path
        )

        result = downloader.download(request)

        assert result.success is True
        assert target_path.exists()
        assert target_path.read_bytes() == b"model_data"

    @patch('comfygit_core.services.model_downloader.hf_hub_download')
    @patch('comfygit_core.services.model_downloader.parse_huggingface_url')
    def test_hf_download_retries_without_tqdm_class_on_type_error(self, mock_parse, mock_hf_download, tmp_path):
        """Test that HF download falls back to no progress bar if tqdm_class causes TypeError."""
        from comfygit_core.services.huggingface_url import ParsedHuggingFaceUrl

        mock_parse.return_value = ParsedHuggingFaceUrl(
            kind="file", repo_id="user/model", path_in_repo="model.safetensors", revision="main"
        )

        # First call with tqdm_class raises TypeError, second without succeeds
        cache_file = tmp_path / "cached_model.safetensors"
        cache_file.write_bytes(b"model_data")

        def side_effect(**kwargs):
            if "tqdm_class" in kwargs:
                raise TypeError("unexpected keyword argument 'tqdm_class'")
            return str(cache_file)

        mock_hf_download.side_effect = side_effect

        repo = Mock()
        repo.find_by_source_url.return_value = None
        repo.calculate_short_hash.return_value = "abc123"

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path
        workspace_config.get_huggingface_token.return_value = None

        downloader = ModelDownloader(repo, workspace_config)
        target_path = tmp_path / "checkpoints" / "model.safetensors"
        target_path.parent.mkdir(parents=True, exist_ok=True)

        request = DownloadRequest(
            url="https://huggingface.co/user/model/resolve/main/model.safetensors",
            target_path=target_path
        )

        result = downloader.download(request, progress_callback=lambda cur, total: None)

        assert result.success is True
        assert mock_hf_download.call_count == 2
        # First call had tqdm_class
        assert "tqdm_class" in mock_hf_download.call_args_list[0].kwargs
        # Second call did not
        assert "tqdm_class" not in mock_hf_download.call_args_list[1].kwargs


class TestModelDownloaderPathValidation:
    """Tests for target path validation in ModelDownloader."""

    def test_rejects_directory_as_target_path(self, tmp_path):
        """Test that download rejects target path if it's a directory."""
        repo = Mock()
        repo.find_by_source_url.return_value = None

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path

        downloader = ModelDownloader(repo, workspace_config)

        # Create a directory at the target path
        target_dir = tmp_path / "checkpoints"
        target_dir.mkdir(parents=True, exist_ok=True)

        request = DownloadRequest(
            url="https://example.com/model.safetensors",
            target_path=target_dir  # This is a directory, not a file
        )

        result = downloader.download(request)

        assert result.success is False
        assert "directory" in result.error.lower()

    def test_rejects_target_path_without_extension(self, tmp_path):
        """Test that download rejects target path without file extension."""
        repo = Mock()
        repo.find_by_source_url.return_value = None

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path

        downloader = ModelDownloader(repo, workspace_config)

        request = DownloadRequest(
            url="https://example.com/model.safetensors",
            target_path=tmp_path / "checkpoints" / "model_without_extension"
        )

        result = downloader.download(request)

        assert result.success is False
        assert "file path" in result.error.lower() or "filename" in result.error.lower()


class TestModelDownloaderHuggingFaceValidation:
    """Tests for HuggingFace URL validation in ModelDownloader."""

    def test_rejects_hf_repo_url_with_helpful_error(self, tmp_path):
        """Test that HF repo browser URLs (/tree/main) are rejected with guidance."""
        repo = Mock()
        repo.find_by_source_url.return_value = None

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path

        downloader = ModelDownloader(repo, workspace_config)

        request = DownloadRequest(
            url="https://huggingface.co/microsoft/VibeVoice-1.5B/tree/main",
            target_path=tmp_path / "checkpoints" / "model.safetensors"
        )

        result = downloader.download(request)

        assert result.success is False
        assert "repository" in result.error.lower() or "repo" in result.error.lower()
        # Should mention using file browser or /resolve/ URL
        assert "/resolve/" in result.error or "file" in result.error.lower()

    def test_rejects_hf_base_repo_url(self, tmp_path):
        """Test that HF base repo URLs (no /tree/) are rejected."""
        repo = Mock()
        repo.find_by_source_url.return_value = None

        workspace_config = Mock()
        workspace_config.get_models_directory.return_value = tmp_path

        downloader = ModelDownloader(repo, workspace_config)

        request = DownloadRequest(
            url="https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0",
            target_path=tmp_path / "checkpoints" / "model.safetensors"
        )

        result = downloader.download(request)

        assert result.success is False
        assert "repository" in result.error.lower() or "repo" in result.error.lower()
