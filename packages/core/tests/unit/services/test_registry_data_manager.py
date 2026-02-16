"""Tests for registry data manager cache/fetch behavior."""

from __future__ import annotations

import json
from urllib.error import URLError

from comfygit_core.services.registry_data_manager import RegistryDataManager


class _FakeResponse:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_get_mappings_fetches_builtins_also(tmp_path, monkeypatch):
    manager = RegistryDataManager(tmp_path)

    mappings_payload = {"version": "m1", "stats": {}, "mappings": {}, "packages": {}}
    builtins_payload = {
        "version": "b1",
        "generated_at": "1970-01-01T00:00:00Z",
        "comfyui_versions_processed": [],
        "stats": {},
        "builtins": {},
    }

    def fake_urlopen(request, timeout=0):  # noqa: ARG001
        url = request.full_url
        if url.endswith("/data/node_mappings.json"):
            return _FakeResponse(mappings_payload)
        if url.endswith("/data/comfyui_builtins_by_version.json"):
            return _FakeResponse(builtins_payload)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("comfygit_core.services.registry_data_manager.urlopen", fake_urlopen)

    mappings_path = manager.get_mappings_path()
    builtins_path = manager.get_builtin_versions_path()

    assert mappings_path.exists()
    assert builtins_path.exists()

    info = manager.get_cache_info()
    assert info["exists"] is True
    assert info["builtins_exists"] is True
    assert info["version"] == "m1"
    assert info["builtins_version"] == "b1"


def test_builtin_fetch_failure_is_non_fatal_for_mappings(tmp_path, monkeypatch):
    manager = RegistryDataManager(tmp_path)

    mappings_payload = {"version": "m1", "stats": {}, "mappings": {}, "packages": {}}

    def fake_urlopen(request, timeout=0):  # noqa: ARG001
        url = request.full_url
        if url.endswith("/data/node_mappings.json"):
            return _FakeResponse(mappings_payload)
        if url.endswith("/data/comfyui_builtins_by_version.json"):
            raise URLError("simulated builtins fetch failure")
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("comfygit_core.services.registry_data_manager.urlopen", fake_urlopen)

    mappings_path = manager.get_mappings_path()

    assert mappings_path.exists()
    assert manager.builtin_versions_file.exists() is False
