"""Tests for WorkflowAnalysisService."""

from __future__ import annotations

from comfygit_core.services.model_source_lookup import ModelSourceCandidate
from comfygit_core.services.workflow_analysis_service import WorkflowAnalysisService


def test_analyze_json_detects_api_wrapped_format() -> None:
    service = WorkflowAnalysisService(
        node_mappings_repository=None,
        model_repository=None,
        builtin_versions_repository=None,
    )
    data = {
        "prompt": {
            "1": {"class_type": "KSampler", "inputs": {}},
        }
    }

    report = service.analyze_json(data, name="wf-api")

    assert report.input_format == "api_wrapped"
    assert report.workflow_name == "wf-api"
    assert report.total_nodes == 1
    assert report.total_model_refs == 0


def test_analyze_json_uses_embedded_model_urls_without_model_repo() -> None:
    service = WorkflowAnalysisService(
        node_mappings_repository=None,
        model_repository=None,
        builtin_versions_repository=None,
    )
    data = {
        "nodes": [
            {
                "id": 1,
                "type": "CLIPLoader",
                "inputs": [],
                "outputs": [],
                "widgets_values": ["clip_model.safetensors"],
                "properties": {
                    "models": [
                        {
                            "name": "clip_model.safetensors",
                            "url": "https://example.com/clip_model.safetensors",
                            "directory": "text_encoders",
                        }
                    ]
                },
            }
        ],
        "links": [],
    }

    report = service.analyze_json(data, name="wf-ui")

    assert report.input_format == "ui_list"
    assert report.total_model_refs == 1
    assert report.models_with_embedded_urls == 1
    assert report.models_without_sources == 0
    assert len(report.resolution.models_resolved) == 1
    assert report.model_resolution_rate == 100.0


def test_analyze_json_reports_registry_unavailable() -> None:
    service = WorkflowAnalysisService(
        node_mappings_repository=None,
        model_repository=None,
        builtin_versions_repository=None,
        registry_available=False,
        registry_error="offline",
    )
    data = {
        "nodes": [
            {
                "id": 1,
                "type": "MyUnknownCustomNode",
                "inputs": [],
                "outputs": [],
                "widgets_values": [],
                "properties": {},
            }
        ],
        "links": [],
    }

    report = service.analyze_json(data, name="wf-offline")

    unresolved_types = {item["type"] for item in report.unresolved_items}
    assert "registry" in unresolved_types
    assert "node_unresolved" in unresolved_types
    assert report.overall_confidence == "incomplete"


class _FakeLookup:
    def lookup_sources(self, filename: str, model_hash: str | None = None, max_results: int = 5):
        _ = (filename, model_hash, max_results)
        return [
            ModelSourceCandidate(
                provider="civitai",
                url="https://civitai.com/high-confidence",
                confidence="high",
                reason="hash_match",
            )
        ]


def test_analyze_json_online_enrichment_promotes_unresolved_model() -> None:
    service = WorkflowAnalysisService(
        node_mappings_repository=None,
        model_repository=None,
        builtin_versions_repository=None,
        model_source_lookup=_FakeLookup(),
    )
    data = {
        "nodes": [
            {
                "id": 1,
                "type": "CLIPLoader",
                "inputs": [],
                "outputs": [],
                "widgets_values": ["clip_missing_source.safetensors"],
                "properties": {},
            }
        ],
        "links": [],
    }

    report = service.analyze_json(data, name="wf-online", online=True)

    assert len(report.resolution.models_unresolved) == 0
    assert len(report.resolution.models_resolved) == 1
    assert report.resolution.models_resolved[0].model_source == "https://civitai.com/high-confidence"
