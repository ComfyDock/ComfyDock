"""CivitAI API client for model discovery, metadata, and downloads."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

from comfygit_core.caching.api_cache import APICacheManager
from comfygit_core.logging.logging_config import get_logger
from comfygit_core.models.civitai import (
    CivitAIModel,
    CivitAIModelVersion,
    CivitAITag,
    SearchParams,
    SearchResponse,
)
from comfygit_core.models.exceptions import (
    CDRegistryAuthError,
    CDRegistryConnectionError,
    CDRegistryError,
    CDRegistryServerError,
)
from comfygit_core.repositories.workspace_config_repository import (
    WorkspaceConfigRepository,
)
from comfygit_core.utils.retry import (
    RateLimitManager,
    RetryConfig,
    retry_on_rate_limit,
)

logger = get_logger(__name__)

DEFAULT_CIVITAI_URL = "https://civitai.com/api/v1"
DEFAULT_CIVITAI_SEARCH_URL = "https://search-new.civitai.com"
DEFAULT_CIVITAI_SEARCH_INDEX = "models_v9"
DEFAULT_CIVITAI_SEARCH_CLIENT_KEY = (
    "8c46eb2508e21db1e9828a97968d91ab1ca1caa5f70a00e88a2ba1e286603b61"
)


class CivitAIError(CDRegistryError):
    """Base CivitAI exception."""
    pass


class CivitAINotFoundError(CivitAIError):
    """Model or version not found."""
    pass


class CivitAIRateLimitError(CivitAIError):
    """Hit CivitAI rate limits."""
    pass


class CivitAIClient:
    """Client for interacting with CivitAI API.

    Provides model discovery, metadata retrieval, and download URL generation.
    Supports optional authentication for restricted content.
    """

    def __init__(
        self,
        cache_manager: APICacheManager,
        api_key: str | None = None,
        workspace_config: WorkspaceConfigRepository | None = None,
        base_url: str = DEFAULT_CIVITAI_URL,
    ):
        """Initialize CivitAI client.

        Args:
            cache_manager: Required cache manager for API responses
            api_key: Direct API key override
            workspace_config: Workspace config repository for API key lookup
            base_url: CivitAI API base URL
        """
        self.base_url = base_url
        self.cache_manager = cache_manager
        self.workspace_config = workspace_config

        # Resolve API key: direct > environment > config
        self._api_key = api_key
        if not self._api_key:
            self._api_key = os.environ.get("CIVITAI_API_TOKEN")
        if not self._api_key and workspace_config:
            self._api_key = workspace_config.get_civitai_token()

        self.rate_limiter = RateLimitManager(min_interval=0.1)
        self.retry_config = RetryConfig(
            max_retries=3,
            initial_delay=0.5,
            max_delay=30.0,
            exponential_base=2.0,
            jitter=True,
        )

    def search_models(
        self, params: SearchParams | None = None, **kwargs
    ) -> SearchResponse:
        """Search for models with filters.

        Args:
            params: SearchParams object with filters
            **kwargs: Alternative way to pass search parameters

        Returns:
            SearchResponse with models and pagination info
        """
        if params:
            query_params = params.to_dict()
        else:
            # Build from kwargs
            query_params = {}
            for key, value in kwargs.items():
                if value is not None:
                    query_params[key] = value

        url = f"{self.base_url}/models"
        if query_params:
            url += f"?{urllib.parse.urlencode(query_params)}"

        data = self._make_request(url)
        if data:
            return SearchResponse.from_api_data(data)

        return SearchResponse(
            items=[], total_items=0, current_page=1, page_size=0, total_pages=0
        )

    def search_models_ranked(
        self,
        query: str,
        *,
        limit: int = 20,
        types: str | list[str] | None = None,
        username: str | None = None,
    ) -> SearchResponse:
        """Search models using CivitAI's public search index ranking.

        The public v1 ``/models?query=...`` endpoint can return weak textual
        matches for user-facing searches. CivitAI's own site first asks the
        public Meilisearch model index for ranked IDs, then resolves model
        metadata. We mirror that behavior and fall back to the v1 API if the
        search index is unavailable.
        """
        ranked_ids = self.search_model_index_ids(
            query,
            limit=limit,
            types=types,
            username=username,
        )
        if not ranked_ids:
            return self.search_models(
                query=query,
                limit=limit,
                types=types,
                username=username,
            )

        models: list[CivitAIModel] = []
        for model_id in ranked_ids:
            model = self.get_model(model_id)
            if model is not None:
                models.append(model)

        return SearchResponse(
            items=models,
            total_items=len(models),
            current_page=1,
            page_size=len(models),
            total_pages=1,
        )

    def search_model_index_ids(
        self,
        query: str,
        *,
        limit: int = 20,
        types: str | list[str] | None = None,
        username: str | None = None,
    ) -> list[int]:
        """Return ranked model IDs from CivitAI's public search index."""
        query = query.strip()
        if not query:
            return []

        search_url = os.environ.get("CIVITAI_SEARCH_HOST", DEFAULT_CIVITAI_SEARCH_URL).rstrip("/")
        search_key = os.environ.get(
            "CIVITAI_SEARCH_CLIENT_KEY",
            DEFAULT_CIVITAI_SEARCH_CLIENT_KEY,
        )
        search_index = os.environ.get("CIVITAI_SEARCH_INDEX", DEFAULT_CIVITAI_SEARCH_INDEX)

        filters: list[str] = []
        type_values = self._normalize_search_filter_values(types)
        if type_values:
            filters.append(
                "type IN ["
                + ", ".join(json.dumps(value) for value in type_values)
                + "]"
            )
        if username:
            filters.append(f"user.username = {json.dumps(username)}")

        body: dict[str, Any] = {
            "q": query,
            "limit": max(1, min(limit, 50)),
            "attributesToRetrieve": ["id"],
        }
        if filters:
            body["filter"] = filters

        url = f"{search_url}/indexes/{search_index}/search"
        cache_key = f"{url}:{json.dumps(body, sort_keys=True)}"
        cached_data = self.cache_manager.get("civitai-search", cache_key)
        if cached_data is not None:
            return self._ids_from_search_index_response(cached_data)

        self.rate_limiter.wait_if_needed("civitai_search")

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
        )
        req.add_header("User-Agent", "ComfyGit/1.0")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {search_key}")
        req.add_header("Origin", "https://civitai.com")
        req.add_header("Referer", "https://civitai.com/")

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                if response.status == 200:
                    json_data = json.loads(response.read().decode("utf-8"))
                    self.cache_manager.set("civitai-search", cache_key, json_data)
                    return self._ids_from_search_index_response(json_data)
        except Exception as e:
            logger.warning("CivitAI search index request failed: %s", e)

        return []

    def search_models_iter(
        self, params: SearchParams | None = None, **kwargs
    ) -> Iterator[CivitAIModel]:
        """Iterate through all search results with automatic pagination.

        Args:
            params: SearchParams object with filters
            **kwargs: Alternative way to pass search parameters

        Yields:
            CivitAIModel objects
        """
        current_params = params or SearchParams(**kwargs)
        current_params.page = 1

        while True:
            response = self.search_models(current_params)
            if not response.items:
                break

            yield from response.items

            # Check if there's a next page
            if current_params.page >= response.total_pages:
                break

            current_params.page += 1

    def get_model(self, model_id: int) -> CivitAIModel | None:
        """Get model by ID.

        Args:
            model_id: CivitAI model ID

        Returns:
            Model info or None if not found
        """
        url = f"{self.base_url}/models/{model_id}"
        data = self._make_request(url)

        if data:
            logger.info(f"Found CivitAI model {model_id}")
            return CivitAIModel.from_api_data(data)

        return None

    def get_model_version(self, version_id: int) -> CivitAIModelVersion | None:
        """Get specific model version.

        Args:
            version_id: Model version ID

        Returns:
            Version info or None if not found
        """
        url = f"{self.base_url}/model-versions/{version_id}"
        data = self._make_request(url)

        if data:
            logger.info(f"Found CivitAI model version {version_id}")
            return CivitAIModelVersion.from_api_data(data)

        return None

    def get_model_by_hash(
        self, hash_value: str, algorithm: str | None = None
    ) -> CivitAIModelVersion | None:
        """Get model version by file hash.

        Args:
            hash_value: File hash
            algorithm: Hash algorithm (auto-detected if not provided)

        Returns:
            Version info or None if not found

        Supported algorithms: AutoV1, AutoV2, SHA256, CRC32, Blake3
        """
        if not algorithm:
            algorithm = self._detect_hash_algorithm(hash_value)
            logger.debug(f"Auto-detected hash algorithm: {algorithm}")

        url = f"{self.base_url}/model-versions/by-hash/{hash_value}"
        data = self._make_request(url)

        if data:
            logger.info(f"Found model by hash {hash_value[:8]}...")
            return CivitAIModelVersion.from_api_data(data)

        return None

    def get_download_url(
        self,
        version_id: int,
        file_format: str | None = None,
        size: str | None = None,
        fp: str | None = None,
    ) -> str:
        """Generate download URL for a model version.

        Args:
            version_id: Model version ID
            file_format: Desired format (SafeTensor, PickleTensor)
            size: Model size (full, pruned)
            fp: Float precision (fp16, fp32)

        Returns:
            Clean download URL without embedded authentication

        Note: The actual download will redirect to a pre-signed S3 URL
        Note: Authentication must be attached by the downloader at request time.
              Do not persist API keys in source/download URLs.
        """
        params: dict[str, str] = {}
        if file_format:
            params["format"] = file_format
        if size:
            params["size"] = size
        if fp:
            params["fp"] = fp

        base = f"https://civitai.com/api/download/models/{version_id}"
        if params:
            base += f"?{urllib.parse.urlencode(params)}"

        return base

    def get_tags(
        self, query: str | None = None, limit: int = 20
    ) -> list[CivitAITag]:
        """Get tags optionally filtered by query.

        Args:
            query: Optional search term for tags
            limit: Maximum number of tags to return

        Returns:
            List of tags
        """
        params: dict[str, Any] = {"limit": limit}
        if query:
            params["query"] = query

        url = f"{self.base_url}/tags?{urllib.parse.urlencode(params)}"
        data = self._make_request(url)

        if data and "items" in data:
            return [CivitAITag.from_api_data(t) for t in data["items"]]

        return []

    @staticmethod
    def _normalize_search_filter_values(value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_values = value.split(",")
        else:
            raw_values = value
        return [item.strip() for item in raw_values if item and item.strip()]

    @staticmethod
    def _ids_from_search_index_response(data: dict) -> list[int]:
        ids: list[int] = []
        for hit in data.get("hits", []):
            try:
                ids.append(int(hit["id"]))
            except (KeyError, TypeError, ValueError):
                continue
        return ids

    def _detect_hash_algorithm(self, hash_value: str) -> str:
        """Auto-detect hash algorithm by length and pattern.

        Args:
            hash_value: Hash string

        Returns:
            Detected algorithm name
        """
        hash_len = len(hash_value)

        if hash_len == 8:
            return "CRC32"
        elif hash_len == 10:
            return "AutoV1"
        elif hash_len == 12:
            return "AutoV2"
        elif hash_len == 64:
            return "SHA256"
        elif hash_len == 128:
            return "Blake3"
        else:
            # Default to SHA256
            logger.warning(f"Unknown hash length {hash_len}, assuming SHA256")
            return "SHA256"

    @retry_on_rate_limit(RetryConfig(max_retries=3, initial_delay=0.5, max_delay=30.0))
    def _make_request(self, url: str, authenticated: bool = False) -> dict | None:
        """Make a request to CivitAI API with retry logic.

        Args:
            url: Request URL
            authenticated: Force authentication for this request

        Returns:
            Response data or None for 404

        Raises:
            CivitAIRateLimitError: For rate limit errors
            CDRegistryAuthError: For authentication issues
            CDRegistryServerError: For server errors
            CDRegistryConnectionError: For network issues
        """
        # Check cache first
        cache_key = url
        if self._api_key and authenticated:
            # Include auth state in cache key
            cache_key = f"{url}:authed"

        cached_data = self.cache_manager.get("civitai", cache_key)
        if cached_data is not None:
            logger.debug("Using cached data for CivitAI request")
            return cached_data

        # Rate limit ourselves
        self.rate_limiter.wait_if_needed("civitai_api")

        # Build request
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "ComfyGit/1.0")
        req.add_header("Content-Type", "application/json")

        # Add authentication if available
        if (authenticated or self._api_key) and self._api_key:
            req.add_header("Authorization", f"Bearer {self._api_key}")

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status == 200:
                    json_data = json.loads(response.read().decode("utf-8"))
                    # Cache successful responses
                    self.cache_manager.set("civitai", cache_key, json_data)
                    return json_data

        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.debug(f"CivitAI: Not found at '{url}'")
                return None

            elif e.code == 429:
                # Rate limit
                logger.warning("CivitAI rate limit hit")
                raise CivitAIRateLimitError("Rate limit exceeded") from e

            elif e.code in (401, 403):
                # Authentication/authorization errors
                logger.error(f"CivitAI auth error: HTTP {e.code}")

                error_msg = f"CivitAI authentication failed (HTTP {e.code})"
                if e.code == 401 and not self._api_key:
                    error_msg += " - API key may be required for this resource"

                raise CDRegistryAuthError(error_msg) from e

            elif e.code >= 500:
                # Server errors
                logger.error(f"CivitAI server error: HTTP {e.code}")
                raise CDRegistryServerError(
                    f"CivitAI server error (HTTP {e.code})"
                ) from e

            else:
                # Other HTTP errors
                error_detail = ""
                try:
                    error_data = e.read().decode("utf-8")
                    if error_data:
                        error_detail = f" - {error_data}"
                except:
                    pass
                logger.error(f"CivitAI HTTP error: {e.code} {e.reason}{error_detail}")
                logger.debug(f"Failed URL: {url}")
                raise CivitAIError(
                    f"CivitAI request failed: HTTP {e.code} {e.reason}{error_detail}"
                ) from e

        except urllib.error.URLError as e:
            # Network errors
            logger.error(f"CivitAI connection error: {e}")
            raise CDRegistryConnectionError(
                f"Failed to connect to CivitAI: {e.reason}"
            ) from e

        except Exception as e:
            # Unexpected errors
            logger.error(f"Unexpected error accessing CivitAI: {e}")
            raise CivitAIError(f"CivitAI request failed: {e}") from e

        return None
