"""Provider-backed model source lookup for online enrichment."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from huggingface_hub import HfApi

from ..caching.api_cache import APICacheManager
from ..clients.civitai_client import CivitAIClient
from ..logging.logging_config import get_logger

if TYPE_CHECKING:
    from ..models.civitai import CivitAIModelVersion
    from ..repositories.workspace_config_repository import WorkspaceConfigRepository

logger = get_logger(__name__)


@dataclass
class ModelSourceCandidate:
    """A candidate source URL discovered online."""

    provider: str  # "civitai" | "huggingface"
    url: str
    confidence: str  # "high" | "medium" | "low"
    reason: str


class ModelSourceLookupService:
    """Lookup model sources from online providers using confidence-ordered chain."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        workspace_config: WorkspaceConfigRepository | None = None,
        civitai_client: CivitAIClient | None = None,
        hf_api: HfApi | None = None,
    ) -> None:
        cache_root = cache_dir or Path(tempfile.mkdtemp(prefix="comfygit-source-lookup-"))

        if civitai_client is not None:
            self.civitai = civitai_client
        else:
            cache_manager = APICacheManager(cache_base_path=cache_root)
            self.civitai = CivitAIClient(
                cache_manager=cache_manager,
                workspace_config=workspace_config,
            )

        if hf_api is not None:
            self.hf_api = hf_api
        else:
            hf_token = workspace_config.get_huggingface_token() if workspace_config else None
            self.hf_api = HfApi(token=hf_token)

    def lookup_sources(
        self,
        filename: str,
        model_hash: str | None = None,
        max_results: int = 5,
    ) -> list[ModelSourceCandidate]:
        """Lookup possible model sources (high → medium → low confidence)."""
        candidates: list[ModelSourceCandidate] = []

        # 1) CivitAI hash lookup (highest confidence)
        if model_hash:
            try:
                version = self.civitai.get_model_by_hash(model_hash)
                candidate = self._candidate_from_civitai_version(version)
                if candidate:
                    candidates.append(
                        ModelSourceCandidate(
                            provider="civitai",
                            url=candidate,
                            confidence="high",
                            reason="hash_match",
                        )
                    )
            except Exception as e:
                logger.debug("CivitAI hash lookup failed for %s: %s", model_hash, e)

        # 2) CivitAI search by filename (medium confidence)
        try:
            response = self.civitai.search_models(query=filename, limit=max_results)
            for model in response.items:
                model_url = None
                primary_file = model.get_primary_file()
                if primary_file and primary_file.download_url:
                    model_url = primary_file.download_url
                else:
                    latest = model.get_latest_version()
                    if latest and latest.download_url:
                        model_url = latest.download_url
                if model_url:
                    candidates.append(
                        ModelSourceCandidate(
                            provider="civitai",
                            url=model_url,
                            confidence="medium",
                            reason="filename_search",
                        )
                    )
        except Exception as e:
            logger.debug("CivitAI filename search failed for %s: %s", filename, e)

        # 3) HuggingFace search (lower confidence)
        try:
            for model in self.hf_api.list_models(search=filename, limit=max_results):
                model_id = getattr(model, "id", None)
                if not model_id:
                    continue
                candidates.append(
                    ModelSourceCandidate(
                        provider="huggingface",
                        url=f"https://huggingface.co/{model_id}",
                        confidence="low",
                        reason="repo_search",
                    )
                )
        except Exception as e:
            logger.debug("HuggingFace search failed for %s: %s", filename, e)

        return self._dedupe_and_rank(candidates)[:max_results]

    @staticmethod
    def _candidate_from_civitai_version(version: CivitAIModelVersion | None) -> str | None:
        if version is None:
            return None

        if version.files:
            for file in version.files:
                if file.primary and file.download_url:
                    return file.download_url
            for file in version.files:
                if file.download_url:
                    return file.download_url

        return version.download_url

    @staticmethod
    def _dedupe_and_rank(
        candidates: list[ModelSourceCandidate],
    ) -> list[ModelSourceCandidate]:
        priority = {"high": 0, "medium": 1, "low": 2}
        deduped: dict[str, ModelSourceCandidate] = {}
        for candidate in candidates:
            existing = deduped.get(candidate.url)
            if existing is None:
                deduped[candidate.url] = candidate
                continue
            if priority[candidate.confidence] < priority[existing.confidence]:
                deduped[candidate.url] = candidate

        return sorted(deduped.values(), key=lambda c: priority[c.confidence])
