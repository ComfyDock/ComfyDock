"""ModelDownloadManager - Handle model downloads from various sources."""

import shutil
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from ..logging.logging_config import get_logger
from ..models.exceptions import ComfyDockError

if TYPE_CHECKING:
    from ..models.shared import ModelWithLocation
    from ..repositories.model_repository import ModelRepository


logger = get_logger(__name__)


class ModelDownloadManager:
    """Handle model downloads from various sources."""

    def __init__(self, model_repository: ModelRepository, cache_dir: Path):
        """Initialize ModelDownloadManager.

        Args:
            model_manager: ModelManager instance for indexing
            cache_dir: Directory to store downloaded models (defaults to workspace/models)
        """
        self.model_repository = model_repository
        self.cache_dir = cache_dir / "models"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def download_from_url(self, url: str, filename: str | None = None) -> ModelWithLocation:
        """Download model from URL and add to index.

        Args:
            url: Source URL to download from
            filename: Override filename (extracted from URL if not provided)

        Returns:
            ModelWithLocation entry for the downloaded model

        Raises:
            ComfyDockError: If download or indexing fails
        """
        # Check if we already have this URL
        existing = self.model_repository.find_by_source_url(url)
        if existing:
            logger.info(f"Model already indexed from {url}")
            return existing

        # Parse URL for metadata
        source_type, metadata = self._parse_source_url(url)

        # Determine filename
        if not filename:
            filename = self._extract_filename_from_url(url)

        target_path = self.cache_dir / filename

        # Download if not exists
        if not target_path.exists():
            logger.info(f"Downloading model from {url}")
            self._download_file(url, target_path)
        else:
            logger.info(f"Model file already exists: {target_path}")

        # Create model info and add to index
        model_info = self.model_repository._create_model_info(target_path)

        # Add to index with source tracking
        self.model_repository.add_model(model_info, target_path, "downloads")
        self.model_repository.add_source(
            model_info.short_hash, source_type, url, metadata
        )

        # Return the indexed model
        indexed_models = self.model_repository.find_model_by_hash(model_info.short_hash)
        if not indexed_models:
            raise ComfyDockError(f"Failed to index downloaded model: {filename}")

        logger.info(f"Successfully downloaded and indexed: {filename}")
        return indexed_models[0]

    def _download_file(self, url: str, target_path: Path) -> None:
        """Download file from URL to target path.

        Args:
            url: URL to download
            target_path: Path to save file

        Raises:
            ComfyDockError: If download fails
        """
        temp_path = None
        try:
            from ..utils.download import download_file

            # Download to temporary file
            temp_path = download_file(url)

            # Move to target location
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(temp_path, target_path)

        except Exception as e:
            # Clean up temp file if it exists
            if temp_path and temp_path.exists():
                temp_path.unlink()
            raise ComfyDockError(f"Failed to download {url}: {e}") from e

    def _parse_source_url(self, url: str) -> tuple[str, dict]:
        """Parse URL to determine source type and extract metadata.

        Args:
            url: Source URL

        Returns:
            Tuple of (source_type, metadata_dict)
        """
        parsed = urlparse(url.lower())
        metadata = {'original_url': url}

        if 'civitai.com' in parsed.netloc:
            source_type = 'civitai'
            # Extract model ID from URL if possible
            if '/models/' in url:
                parts = url.split('/models/')
                if len(parts) > 1:
                    model_id = parts[1].split('/')[0]
                    metadata['model_id'] = model_id
        elif 'huggingface.co' in parsed.netloc:
            source_type = 'huggingface'
            # Extract repository path
            path_parts = parsed.path.strip('/').split('/')
            if len(path_parts) >= 2:
                metadata['repository'] = f"{path_parts[0]}/{path_parts[1]}"
        else:
            source_type = 'url'
            metadata['domain'] = parsed.netloc

        return source_type, metadata

    def _extract_filename_from_url(self, url: str) -> str:
        """Extract filename from URL.

        Args:
            url: Source URL

        Returns:
            Extracted filename
        """
        parsed = urlparse(url)

        # Try to get filename from path
        path = parsed.path
        if path:
            filename = Path(path).name
            if filename and '.' in filename:
                return filename

        # Try to get from query parameters (common for download APIs)
        if parsed.query:
            for param in parsed.query.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    if key.lower() in ['filename', 'name', 'file']:
                        return value

        # Fall back to generic name with extension guessing
        if 'civitai' in url.lower():
            return "civitai_model.safetensors"
        elif 'huggingface' in url.lower():
            return "huggingface_model.safetensors"
        else:
            return "downloaded_model.safetensors"

    def get_download_info(self, url: str) -> dict:
        """Get information about what would be downloaded without downloading.

        Args:
            url: Source URL

        Returns:
            Dictionary with download information
        """
        source_type, metadata = self._parse_source_url(url)
        filename = self._extract_filename_from_url(url)
        target_path = self.cache_dir / filename

        # Check if already exists
        existing = self.model_repository.find_by_source_url(url)

        return {
            'url': url,
            'source_type': source_type,
            'filename': filename,
            'target_path': str(target_path),
            'already_downloaded': target_path.exists(),
            'already_indexed': existing is not None,
            'existing_model': existing,
            'metadata': metadata
        }

    def bulk_download(self, urls: list[str]) -> dict[str, ModelWithLocation | Exception]:
        """Download multiple models from URLs.

        Args:
            urls: List of URLs to download

        Returns:
            Dictionary mapping URLs to ModelIndex or Exception
        """
        results = {}

        for url in urls:
            try:
                model = self.download_from_url(url)
                results[url] = model
                logger.info(f"✓ Downloaded: {url}")
            except Exception as e:
                results[url] = e
                logger.error(f"✗ Failed to download {url}: {e}")

        return results

    def redownload_from_sources(self, model_hash: str) -> ModelWithLocation | None:
        """Attempt to redownload a model from its known sources.

        Args:
            model_hash: Hash of model to redownload

        Returns:
            ModelIndex if successful, None if no sources or download failed
        """
        sources = self.model_repository.get_sources(model_hash)

        if not sources:
            logger.warning(f"No sources found for model {model_hash[:8]}...")
            return None

        for source in sources:
            try:
                logger.info(f"Attempting redownload from {source['type']}: {source['url']}")
                return self.download_from_url(source['url'])
            except Exception as e:
                logger.warning(f"Failed to redownload from {source['url']}: {e}")
                continue

        logger.error(f"All redownload attempts failed for {model_hash[:8]}...")
        return None
