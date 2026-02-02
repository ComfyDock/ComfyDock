"""Integration tests for model download flow."""

import http.server
import socketserver
import threading
from pathlib import Path

import pytest
from comfygit_core.repositories.model_repository import ModelRepository
from comfygit_core.services.model_downloader import DownloadRequest, ModelDownloader


@pytest.fixture
def mock_http_server():
    """Create a mock HTTP server for download testing."""
    # Create test file content
    test_content = b"FAKE_MODEL_DATA" * 1000  # ~15KB

    class MockHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/model.safetensors":
                self.send_response(200)
                self.send_header("Content-type", "application/octet-stream")
                self.send_header("Content-length", str(len(test_content)))
                self.end_headers()
                self.wfile.write(test_content)
            else:
                self.send_error(404)

        def log_message(self, format, *args):
            pass  # Suppress request logging

    # Start server on random available port
    with socketserver.TCPServer(("127.0.0.1", 0), MockHandler) as httpd:
        port = httpd.server_address[1]
        url = f"http://127.0.0.1:{port}/model.safetensors"

        # Run server in background thread
        server_thread = threading.Thread(target=httpd.serve_forever)
        server_thread.daemon = True
        server_thread.start()

        yield url, len(test_content)

        httpd.shutdown()


def test_download_model_integration(tmp_path, mock_http_server):
    """Test downloading a model from URL and indexing it."""
    url, expected_size = mock_http_server

    # Setup
    db_path = tmp_path / "models.db"
    models_dir = tmp_path / "models"
    models_dir.mkdir()

    repository = ModelRepository(db_path)
    downloader = ModelDownloader(repository, workspace_config=None, models_dir=models_dir)

    # Download request
    target_path = models_dir / "checkpoints" / "test_model.safetensors"
    request = DownloadRequest(
        url=url,
        target_path=target_path,
        workflow_name="test_workflow"
    )

    # Execute download
    result = downloader.download(request)

    # Verify success
    assert result.success is True
    assert result.error is None
    assert result.model is not None

    # Verify file was downloaded
    assert target_path.exists()
    assert target_path.stat().st_size == expected_size

    # Verify model was indexed
    assert result.model.filename == "test_model.safetensors"
    assert result.model.relative_path == "checkpoints/test_model.safetensors"
    assert result.model.file_size == expected_size
    assert result.model.hash is not None
    assert result.model.blake3_hash is not None

    # Verify source was recorded
    sources = repository.get_sources(result.model.hash)
    assert len(sources) == 1
    assert sources[0]['url'] == url
    assert sources[0]['type'] == 'custom'

    # Verify can find by source URL
    found_model = repository.find_by_source_url(url)
    assert found_model is not None
    assert found_model.hash == result.model.hash


def test_download_duplicate_url_returns_existing(tmp_path, mock_http_server):
    """Test that downloading same URL twice returns existing model."""
    url, expected_size = mock_http_server

    # Setup
    db_path = tmp_path / "models.db"
    models_dir = tmp_path / "models"
    models_dir.mkdir()

    repository = ModelRepository(db_path)
    downloader = ModelDownloader(repository, workspace_config=None, models_dir=models_dir)

    # First download
    target_path1 = models_dir / "checkpoints" / "model1.safetensors"
    request1 = DownloadRequest(url=url, target_path=target_path1)
    result1 = downloader.download(request1)

    assert result1.success is True
    assert target_path1.exists()

    # Second download with same URL but different target path
    target_path2 = models_dir / "checkpoints" / "model2.safetensors"
    request2 = DownloadRequest(url=url, target_path=target_path2)
    result2 = downloader.download(request2)

    # Should return existing model without downloading again
    assert result2.success is True
    assert result2.model.hash == result1.model.hash
    assert not target_path2.exists()  # Second file not created


def test_download_path_suggestion(tmp_path):
    """Test path suggestion based on node type."""
    db_path = tmp_path / "models.db"
    models_dir = tmp_path / "models"
    models_dir.mkdir()

    repository = ModelRepository(db_path)
    downloader = ModelDownloader(repository, workspace_config=None, models_dir=models_dir)

    # Test CheckpointLoader
    path = downloader.suggest_path(
        url="https://example.com/sd15.safetensors",
        node_type="CheckpointLoaderSimple",
        filename_hint="sd15.safetensors"
    )
    assert path == Path("checkpoints/sd15.safetensors")

    # Test LoraLoader
    path = downloader.suggest_path(
        url="https://example.com/lora.safetensors",
        node_type="LoraLoader",
        filename_hint="lora.safetensors"
    )
    assert path == Path("loras/lora.safetensors")

    # Test unknown node type
    path = downloader.suggest_path(
        url="https://example.com/custom.safetensors",
        node_type=None,
        filename_hint="custom/model.safetensors"
    )
    # Should extract category from hint and use filename from hint
    assert "custom.safetensors" in str(path)  # Uses filename from URL
    assert path.name == "custom.safetensors"


def test_download_invalid_url_returns_error(tmp_path):
    """Test that invalid URLs return error result."""
    db_path = tmp_path / "models.db"
    models_dir = tmp_path / "models"
    models_dir.mkdir()

    repository = ModelRepository(db_path)
    downloader = ModelDownloader(repository, workspace_config=None, models_dir=models_dir)

    target_path = models_dir / "checkpoints" / "model.safetensors"
    request = DownloadRequest(
        url="http://invalid-domain-that-does-not-exist.com/model.safetensors",
        target_path=target_path
    )

    result = downloader.download(request)

    assert result.success is False
    assert result.error is not None
    assert result.model is None
    assert not target_path.exists()
