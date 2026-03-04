"""Tests for ModelSourceLookupService."""

from __future__ import annotations

from types import SimpleNamespace

from comfygit_core.models.civitai import CivitAIFile, CivitAIModelVersion, SearchResponse
from comfygit_core.services.model_source_lookup import ModelSourceLookupService


class _FakeCivitai:
    def __init__(self, version: CivitAIModelVersion | None, search_items: list):
        self._version = version
        self._search_items = search_items

    def get_model_by_hash(self, _hash: str):
        return self._version

    def search_models(self, **_kwargs):
        return SearchResponse(
            items=self._search_items,
            total_items=len(self._search_items),
            current_page=1,
            page_size=len(self._search_items),
            total_pages=1,
        )


class _FakeHF:
    def __init__(self, model_ids: list[str]):
        self._model_ids = model_ids

    def list_models(self, **_kwargs):
        return [SimpleNamespace(id=model_id) for model_id in self._model_ids]


class _FakeCivitaiModel:
    def __init__(self, url: str):
        self._url = url

    def get_primary_file(self):
        return SimpleNamespace(download_url=self._url)

    def get_latest_version(self):
        return SimpleNamespace(download_url=self._url)


def test_lookup_prefers_high_confidence_hash_match(tmp_path) -> None:
    version = CivitAIModelVersion(
        id=1,
        model_id=10,
        name="v1",
        files=[CivitAIFile(id=5, name="model.safetensors", size_kb=1.0, primary=True, download_url="https://civitai.com/hash")],
    )
    lookup = ModelSourceLookupService(
        cache_dir=tmp_path,
        civitai_client=_FakeCivitai(version=version, search_items=[]),
        hf_api=_FakeHF([]),
    )

    results = lookup.lookup_sources(filename="model.safetensors", model_hash="abc123")

    assert results
    assert results[0].confidence == "high"
    assert results[0].url == "https://civitai.com/hash"


def test_lookup_falls_back_to_filename_and_hf(tmp_path) -> None:
    lookup = ModelSourceLookupService(
        cache_dir=tmp_path,
        civitai_client=_FakeCivitai(
            version=None,
            search_items=[_FakeCivitaiModel("https://civitai.com/file-search")],
        ),
        hf_api=_FakeHF(["owner/repo-model"]),
    )

    results = lookup.lookup_sources(filename="model.safetensors")

    assert len(results) == 2
    assert results[0].confidence == "medium"
    assert results[0].url == "https://civitai.com/file-search"
    assert results[1].confidence == "low"
    assert results[1].url == "https://huggingface.co/owner/repo-model"
