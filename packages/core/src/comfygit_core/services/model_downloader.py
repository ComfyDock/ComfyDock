"""Model download service for fetching models from URLs."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

import requests
from blake3 import blake3
from huggingface_hub import hf_hub_download
from tqdm.std import tqdm

from ..configs.model_config import ModelConfig
from ..logging.logging_config import get_logger
from ..models.exceptions import DownloadErrorContext
from ..models.shared import ModelWithLocation
from ..utils.model_categories import get_model_category
from ..utils.provider_urls import is_civitai_url, is_huggingface_url
from ..utils.redaction import redact_url
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
    error_context: DownloadErrorContext | None = None  # Structured error info


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

    def _relative_to_models_dir(self, path: Path) -> Path:
        """Return a path relative to models_dir, allowing symlinked mount roots."""
        try:
            return path.relative_to(self.models_dir)
        except ValueError:
            return path.resolve().relative_to(self.models_dir.resolve())

    def detect_url_type(self, url: str) -> str:
        """Detect source type from URL.

        Args:
            url: URL to analyze

        Returns:
            'civitai', 'huggingface', or 'custom'
        """
        if is_civitai_url(url):
            return "civitai"
        elif is_huggingface_url(url):
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
            # Check via workspace config (handles env var fallback)
            if not self.workspace_config:
                return False
            token = self.workspace_config.get_huggingface_token()
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
        from socket import timeout as SocketTimeout
        from urllib.error import URLError

        http_status = None
        error_category = "unknown"
        raw_error = str(error)

        # Classify based on exception type
        if isinstance(error, requests.HTTPError):
            http_status = error.response.status_code if error.response is not None else None

            if http_status is None:
                error_category = "unknown"
            elif http_status == 401:
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

        elif isinstance(error, URLError | SocketTimeout | requests.Timeout | requests.ConnectionError):
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

        # Get HF token from workspace config (handles env var > config priority)
        token = self.workspace_config.get_huggingface_token() if self.workspace_config else None

        # Custom tqdm class for progress callback
        # HF hub's tqdm_class must handle: (1) 'name' kwarg that vanilla tqdm rejects,
        # (2) disabled progress bar while still tracking progress, (3) thread-safe _lock deletion
        def _make_tqdm_class(cb):
            class _CbTqdm(tqdm):
                def __init__(self, *args, **kwargs):
                    # HF passes 'name' kwarg but vanilla tqdm doesn't accept it
                    kwargs.pop("name", None)
                    kwargs["disable"] = True  # Suppress console output
                    super().__init__(*args, **kwargs)
                    self._progress = 0  # Manual tracking since disabled tqdm doesn't update self.n

                def update(self, n=1):
                    increment = int(n) if n is not None else 0
                    self._progress += increment
                    if cb and self.total:
                        cb(int(self._progress), int(self.total))

                def __delattr__(self, name: str):
                    # Thread safety fix: _lock may already be deleted during cleanup
                    if name == "_lock" and not hasattr(self, "_lock"):
                        return
                    super().__delattr__(name)

            return _CbTqdm

        try:
            # Download directly into models directory (no blob cache duplication)
            # Choose local_dir so local_dir/<path_in_repo> lands on target_path when possible.
            local_dir = self.models_dir
            target_relative = None
            try:
                target_relative = target_path.resolve().relative_to(self.models_dir.resolve())
            except ValueError:
                pass

            path_parts = tuple(parsed.path_in_repo.split("/"))
            if target_relative and len(target_relative.parts) >= len(path_parts):
                suffix_parts = target_relative.parts[-len(path_parts):]
                if suffix_parts == path_parts:
                    prefix_parts = target_relative.parts[:-len(path_parts)]
                    local_dir = self.models_dir / Path(*prefix_parts) if prefix_parts else self.models_dir

            try:
                if progress_callback:
                    tqdm_class = cast(type[Any], _make_tqdm_class(progress_callback))
                    local_path_str = hf_hub_download(
                        repo_id=parsed.repo_id,
                        filename=parsed.path_in_repo,
                        revision=parsed.revision or "main",
                        token=token if token else None,
                        local_dir=str(local_dir),
                        tqdm_class=tqdm_class,
                    )
                else:
                    local_path_str = hf_hub_download(
                        repo_id=parsed.repo_id,
                        filename=parsed.path_in_repo,
                        revision=parsed.revision or "main",
                        token=token if token else None,
                        local_dir=str(local_dir),
                    )
            except TypeError:
                # Older huggingface-hub may not support tqdm_class — download without progress
                local_path_str = hf_hub_download(
                    repo_id=parsed.repo_id,
                    filename=parsed.path_in_repo,
                    revision=parsed.revision or "main",
                    token=token if token else None,
                    local_dir=str(local_dir),
                )

            downloaded_path = Path(local_path_str).resolve()

            # If repo layout differs from requested model path, hardlink/copy into target.
            if downloaded_path != target_path.resolve():
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if target_path.exists():
                    target_path.unlink()

                try:
                    os.link(str(downloaded_path), str(target_path))
                except OSError:
                    shutil.copy2(downloaded_path, target_path)

            # Hash target file for ComfyGit model index integrity verification
            hasher = blake3()
            file_size = 0
            with open(target_path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    hasher.update(chunk)
                    file_size += len(chunk)

            # Register in repository
            short_hash = self.repository.calculate_short_hash(target_path)
            blake3_hash = hasher.hexdigest()
            relative_path = self._relative_to_models_dir(target_path)
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
            logger.info("Downloading from %s", redact_url(request.url))
            url_type = self.detect_url_type(request.url)

            # HuggingFace URL handling
            if url_type == "huggingface":
                return self._download_huggingface(request, target_path, progress_callback)

            # Add Civitai auth header if URL is from Civitai and we have an API key
            headers = {}
            if url_type == "civitai" and self.workspace_config:
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
            relative_path = self._relative_to_models_dir(request.target_path)
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
