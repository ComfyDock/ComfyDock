"""Model download service for fetching models from URLs."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import uuid4

import requests
from blake3 import blake3
from huggingface_hub import hf_hub_download
from tqdm.auto import tqdm

from ..configs.model_config import ModelConfig
from ..logging.logging_config import get_logger
from ..models.exceptions import DownloadErrorContext
from ..models.shared import ModelWithLocation
from ..utils.model_categories import get_model_category
from .huggingface_url import parse_huggingface_url

if TYPE_CHECKING:
    from ..repositories.model_repository import ModelRepository
    from ..repositories.workspace_config_repository import WorkspaceConfigRepository

logger = get_logger(__name__)


@dataclass
class DownloadRequest:
    """Request to download a model."""
    url: str
    target_path: Path  # Full path in global models directory
    workflow_name: str | None = None


@dataclass
class DownloadResult:
    """Result of a download operation."""
    success: bool
    model: ModelWithLocation | None = None
    error: str | None = None
    error_context: "DownloadErrorContext | None" = None  # Structured error info


class ModelDownloader:
    """Handles model downloads with hashing and indexing.

    Responsibilities:
    - Download files from URLs with progress tracking
    - Compute hashes (short + full blake3)
    - Register in ModelRepository
    - Detect URL type (civitai/HF/direct)
    """

    def __init__(
        self,
        model_repository: ModelRepository,
        workspace_config: WorkspaceConfigRepository,
        models_dir: Path | None = None
    ):
        """Initialize ModelDownloader.

        Args:
            model_repository: Repository for indexing models
            workspace_config: Workspace config for API credentials and models directory
            models_dir: Optional override for models directory (defaults to workspace config)
        """
        self.repository = model_repository
        self.workspace_config = workspace_config

        # Use provided models_dir or get from workspace config
        self.models_dir = models_dir if models_dir is not None else workspace_config.get_models_directory()

        # Since workspace always has models_dir configured, this should never be None
        # Raise clear error if it somehow is
        if self.models_dir is None:
            raise ValueError(
                "No models directory available. Either provide models_dir parameter "
                "or ensure workspace config has a models directory configured."
            )

        self.model_config = ModelConfig.load()

    def detect_url_type(self, url: str) -> str:
        """Detect source type from URL.

        Args:
            url: URL to analyze

        Returns:
            'civitai', 'huggingface', or 'custom'
        """
        url_lower = url.lower()

        if "civitai.com" in url_lower:
            return "civitai"
        elif "huggingface.co" in url_lower or "hf.co" in url_lower:
            return "huggingface"
        else:
            return "custom"

    def suggest_path(
        self,
        url: str,
        node_type: str | None = None,
        filename_hint: str | None = None
    ) -> Path:
        """Suggest download path based on context.

        For known nodes: checkpoints/model.safetensors
        For unknown: Uses filename hint or extracts from URL

        Args:
            url: Download URL
            node_type: Optional node type for category mapping
            filename_hint: Optional filename hint from workflow

        Returns:
            Suggested relative path (including base directory)
        """
        # Extract filename from URL or use hint
        filename = self._extract_filename(url, filename_hint)

        # If node type is known, map to directory
        if node_type and self.model_config.is_model_loader_node(node_type):
            directories = self.model_config.get_directories_for_node(node_type)
            base_dir = directories[0]  # e.g., "checkpoints"
            return Path(base_dir) / filename

        # Fallback: try to extract category from filename hint
        if filename_hint:
            category = get_model_category(filename_hint)
            return Path(category) / filename

        # Last resort: use generic models directory
        return Path("models") / filename

    def _extract_filename(self, url: str, filename_hint: str | None = None) -> str:
        """Extract filename from URL or use hint.

        Args:
            url: Download URL
            filename_hint: Optional filename from workflow

        Returns:
            Filename to use
        """
        # Try to extract from URL path
        parsed = urlparse(url)
        url_filename = Path(parsed.path).name

        # Use URL filename if it looks valid (has extension)
        if url_filename and '.' in url_filename:
            return url_filename

        # Fall back to hint
        if filename_hint:
            # Extract just the filename from hint path
            return Path(filename_hint).name

        # Last resort: generate generic name
        return "downloaded_model.safetensors"

    def _check_provider_auth(self, provider: str) -> bool:
        """Check if authentication is configured for a provider.

        Args:
            provider: Provider type ('civitai', 'huggingface', 'custom')

        Returns:
            True if auth credentials are configured
        """
        if provider == "civitai":
            if not self.workspace_config:
                return False
            api_key = self.workspace_config.get_civitai_token()
            return api_key is not None and api_key.strip() != ""
        elif provider == "huggingface":
            # Check HF_TOKEN environment variable
            token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
            return token is not None and token.strip() != ""
        else:
            return False

    def _classify_download_error(
        self,
        error: Exception,
        url: str,
        provider: str,
        has_auth: bool
    ) -> DownloadErrorContext:
        """Classify download error and create structured context.

        Args:
            error: The exception that occurred
            url: Download URL
            provider: Provider type
            has_auth: Whether auth was configured

        Returns:
            DownloadErrorContext with classification
        """
        from urllib.error import URLError
        from socket import timeout as SocketTimeout

        http_status = None
        error_category = "unknown"
        raw_error = str(error)

        # Classify based on exception type
        if isinstance(error, requests.HTTPError):
            http_status = error.response.status_code

            if http_status == 401:
                # Unauthorized - check if we have auth
                if not has_auth:
                    error_category = "auth_missing"
                else:
                    error_category = "auth_invalid"
            elif http_status == 403:
                # Forbidden - could be rate limit, permissions, or invalid token
                if not has_auth and provider in ("civitai", "huggingface"):
                    error_category = "auth_missing"
                else:
                    error_category = "forbidden"
            elif http_status == 404:
                error_category = "not_found"
            elif http_status >= 500:
                error_category = "server"
            else:
                error_category = "unknown"

        elif isinstance(error, (URLError, SocketTimeout, requests.Timeout, requests.ConnectionError)):
            error_category = "network"

        return DownloadErrorContext(
            provider=provider,
            error_category=error_category,
            http_status=http_status,
            url=url,
            has_configured_auth=has_auth,
            raw_error=raw_error
        )

    def _download_huggingface(
        self,
        request: DownloadRequest,
        target_path: Path,
        progress_callback=None
    ) -> DownloadResult:
        """Download a model from HuggingFace using hf_hub_download.

        Args:
            request: Download request
            target_path: Validated target path
            progress_callback: Optional progress callback

        Returns:
            DownloadResult with model or error
        """
        parsed = parse_huggingface_url(request.url)

        # Reject repo URLs with helpful message
        if parsed.kind == "repo":
            return DownloadResult(
                success=False,
                error=(
                    "This HuggingFace URL points to a repository page (e.g. /tree/main). "
                    "Use the HuggingFace repo browser in the UI to select files, "
                    "or provide a direct /resolve/ URL."
                )
            )

        if parsed.kind != "file" or not parsed.repo_id or not parsed.path_in_repo:
            return DownloadResult(
                success=False,
                error="Invalid HuggingFace file URL."
            )

        # Get HF token from environment
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")

        # Custom tqdm class for progress callback
        def _make_tqdm_class(cb):
            class _CbTqdm(tqdm):
                def __init__(self, *args, **kwargs):
                    kwargs.setdefault("disable", True)  # No console output
                    super().__init__(*args, **kwargs)

                def update(self, n=1):
                    super().update(n)
                    if cb and self.total:
                        cb(int(self.n), int(self.total))

            return _CbTqdm

        try:
            # Download to HF cache (Xet-enabled when available)
            cache_path_str = hf_hub_download(
                repo_id=parsed.repo_id,
                filename=parsed.path_in_repo,
                revision=parsed.revision or "main",
                token=token if token else None,
                tqdm_class=_make_tqdm_class(progress_callback) if progress_callback else None,
            )

            cache_path = Path(cache_path_str).resolve()

            # Stage in same dir for atomic replace
            temp_path = target_path.with_name(f".{target_path.name}.tmp-{uuid4().hex}")
            try:
                # Hardlink if possible (fast, no extra disk usage on same filesystem)
                try:
                    os.link(str(cache_path), str(temp_path))
                    # Hash from temp_path
                    hasher = blake3()
                    file_size = 0
                    with open(temp_path, "rb") as f:
                        for chunk in iter(lambda: f.read(1024 * 1024), b""):
                            hasher.update(chunk)
                            file_size += len(chunk)
                except OSError:
                    # Fall back to copy+hash (different filesystem)
                    hasher = blake3()
                    file_size = 0
                    with open(cache_path, "rb") as src, open(temp_path, "wb") as dst:
                        for chunk in iter(lambda: src.read(1024 * 1024), b""):
                            dst.write(chunk)
                            hasher.update(chunk)
                            file_size += len(chunk)

                temp_path.replace(target_path)
                temp_path = None  # Clear since file moved
            finally:
                if temp_path and temp_path.exists():
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass

            # Register in repository
            short_hash = self.repository.calculate_short_hash(target_path)
            blake3_hash = hasher.hexdigest()
            relative_path = target_path.relative_to(self.models_dir)
            mtime = target_path.stat().st_mtime

            self.repository.ensure_model(
                hash=short_hash,
                file_size=file_size,
                blake3_hash=blake3_hash
            )

            self.repository.add_location(
                model_hash=short_hash,
                base_directory=self.models_dir,
                relative_path=relative_path.as_posix(),
                filename=target_path.name,
                mtime=mtime
            )

            self.repository.add_source(
                model_hash=short_hash,
                source_type="huggingface",
                source_url=request.url
            )

            model = ModelWithLocation(
                hash=short_hash,
                file_size=file_size,
                blake3_hash=blake3_hash,
                sha256_hash=None,
                relative_path=relative_path.as_posix(),
                filename=target_path.name,
                mtime=mtime,
                last_seen=int(mtime),
                metadata={}
            )

            logger.info(f"Successfully downloaded and indexed: {relative_path}")
            return DownloadResult(success=True, model=model)

        except Exception as e:
            has_auth = self._check_provider_auth("huggingface")
            error_context = self._classify_download_error(e, request.url, "huggingface", has_auth)
            user_message = error_context.get_user_message()
            logger.error(f"HuggingFace download failed: {user_message}")

            return DownloadResult(
                success=False,
                error=user_message,
                error_context=error_context
            )

    def download(
        self,
        request: DownloadRequest,
        progress_callback=None
    ) -> DownloadResult:
        """Download and index a model.

        Flow:
        1. Check if URL already downloaded
        2. Validate URL and target path
        3. Download to temp file with progress
        4. Hash during download (streaming)
        5. Move to target location
        6. Register in repository
        7. Add source URL

        Args:
            request: Download request with URL and target path
            progress_callback: Optional callback(bytes_downloaded, total_bytes) for progress updates.
                             total_bytes may be None if server doesn't provide Content-Length.

        Returns:
            DownloadResult with model or error
        """
        temp_path: Path | None = None
        try:
            # Step 1: Check if already downloaded
            existing = self.repository.find_by_source_url(request.url)
            if existing:
                logger.info(f"Model already downloaded from URL: {existing.relative_path}")
                return DownloadResult(success=True, model=existing)

            # Step 2: Validate target path
            target_path = request.target_path

            # Guard: target path must be within models dir
            try:
                models_root = self.models_dir.resolve()
                resolved_target = target_path.resolve()
                if models_root != resolved_target and models_root not in resolved_target.parents:
                    return DownloadResult(
                        success=False,
                        error="Target path must be within the models directory."
                    )
            except FileNotFoundError:
                pass  # resolve() can fail if parent doesn't exist; handled after mkdir

            # Guard: user gave a directory -> error
            if target_path.exists() and target_path.is_dir():
                return DownloadResult(
                    success=False,
                    error=(
                        f"Target path '{target_path}' is a directory. "
                        "Please include a filename (e.g. checkpoints/model.safetensors)."
                    )
                )
            if target_path.suffix == "":
                return DownloadResult(
                    success=False,
                    error=(
                        f"Target path '{target_path}' does not look like a file path. "
                        "Please include a filename (e.g. checkpoints/model.safetensors)."
                    )
                )

            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Step 3-4: Download with streaming hash calculation
            logger.info(f"Downloading from {request.url}")
            url_type = self.detect_url_type(request.url)

            # HuggingFace URL handling
            if url_type == "huggingface":
                return self._download_huggingface(request, target_path, progress_callback)

            # Add Civitai auth header if URL is from Civitai and we have an API key
            headers = {}
            if "civitai.com" in request.url.lower() and self.workspace_config:
                api_key = self.workspace_config.get_civitai_token()
                if api_key:
                    headers['Authorization'] = f'Bearer {api_key}'
                    logger.debug("Using Civitai API key for authentication")

            # Timeout: (connect_timeout, read_timeout)
            # 30s to establish connection, None for read (allow slow downloads)
            response = requests.get(request.url, stream=True, timeout=(30, None), headers=headers)
            response.raise_for_status()

            # Extract total size from headers (may be None)
            total_size = None
            if 'content-length' in response.headers:
                try:
                    total_size = int(response.headers['content-length'])
                except (ValueError, TypeError):
                    pass

            # Use temp file for atomic move
            with tempfile.NamedTemporaryFile(delete=False, dir=request.target_path.parent) as temp_file:
                temp_path = Path(temp_file.name)

                # Stream download with hash calculation
                hasher = blake3()
                file_size = 0

                chunk_size = 8192
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        temp_file.write(chunk)
                        hasher.update(chunk)
                        file_size += len(chunk)

                        if progress_callback:
                            progress_callback(file_size, total_size)

            # Step 5: Calculate short hash for indexing
            short_hash = self.repository.calculate_short_hash(temp_path)
            blake3_hash = hasher.hexdigest()

            # Step 6: Atomic move to final location (replace handles existing files)
            temp_path.replace(request.target_path)
            temp_path = None  # Clear temp_path since file has been moved

            # Step 7: Register in repository
            relative_path = request.target_path.relative_to(self.models_dir)
            mtime = request.target_path.stat().st_mtime

            self.repository.ensure_model(
                hash=short_hash,
                file_size=file_size,
                blake3_hash=blake3_hash
            )

            self.repository.add_location(
                model_hash=short_hash,
                base_directory=self.models_dir,
                relative_path=relative_path.as_posix(),
                filename=request.target_path.name,
                mtime=mtime
            )

            # Step 8: Add source URL
            source_type = self.detect_url_type(request.url)
            self.repository.add_source(
                model_hash=short_hash,
                source_type=source_type,
                source_url=request.url
            )

            # Step 9: Create result model
            model = ModelWithLocation(
                hash=short_hash,
                file_size=file_size,
                blake3_hash=blake3_hash,
                sha256_hash=None,
                relative_path=relative_path.as_posix(),
                filename=request.target_path.name,
                mtime=mtime,
                last_seen=int(mtime),
                metadata={}
            )

            logger.info(f"Successfully downloaded and indexed: {relative_path}")
            return DownloadResult(success=True, model=model)

        except requests.HTTPError as e:
            # HTTP errors with status codes - classify them
            provider = self.detect_url_type(request.url)
            has_auth = self._check_provider_auth(provider)
            error_context = self._classify_download_error(e, request.url, provider, has_auth)

            # Generate user-friendly message
            user_message = error_context.get_user_message()
            logger.error(f"Download failed: {user_message}")

            return DownloadResult(
                success=False,
                error=user_message,
                error_context=error_context
            )

        except (requests.Timeout, requests.ConnectionError) as e:
            # Network errors
            provider = self.detect_url_type(request.url)
            error_context = self._classify_download_error(e, request.url, provider, False)
            user_message = error_context.get_user_message()
            logger.error(f"Download failed: {user_message}")

            return DownloadResult(
                success=False,
                error=user_message,
                error_context=error_context
            )

        except Exception as e:
            # Unexpected errors - still provide some context
            provider = self.detect_url_type(request.url)
            has_auth = self._check_provider_auth(provider)
            error_context = self._classify_download_error(e, request.url, provider, has_auth)
            user_message = error_context.get_user_message()
            logger.error(f"Unexpected download error: {user_message}")

            return DownloadResult(
                success=False,
                error=user_message,
                error_context=error_context
            )

        finally:
            # Always clean up temp file if it still exists (download failed or was interrupted)
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                    logger.debug(f"Cleaned up temporary file: {temp_path}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to clean up temp file {temp_path}: {cleanup_error}")
