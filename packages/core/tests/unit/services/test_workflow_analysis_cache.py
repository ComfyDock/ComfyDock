"""Tests for cached workflow analysis coordination."""

import json
from pathlib import Path
from unittest.mock import Mock

from comfygit_core.caching.workflow_cache import CachedWorkflowAnalysis
from comfygit_core.models.workflow import ResolutionResult, WorkflowDependencies
from comfygit_core.services.workflow_analysis_cache import WorkflowAnalysisCache
from comfygit_core.services.workflow_file_store import WorkflowFileStore


def _write_workflow(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"nodes": []}), encoding="utf-8")


def _service(tmp_path, cache):
    file_store = WorkflowFileStore(
        tmp_path / "ComfyUI",
        tmp_path / ".cec",
        environment_name="test-env",
        workflow_cache=Mock(),
    )
    _write_workflow(file_store.comfyui_workflows / "workflow.json")
    return WorkflowAnalysisCache(
        workflow_file_store=file_store,
        workflow_cache=cache,
        environment_name="test-env",
        cec_path=tmp_path / ".cec",
        pyproject_path=tmp_path / "pyproject.toml",
        builtin_versions_repository=None,
    )


def test_analyze_and_resolve_uses_cached_dependencies_and_resolution(tmp_path):
    deps = WorkflowDependencies(workflow_name="workflow")
    resolution = ResolutionResult(workflow_name="workflow")
    cache = Mock()
    cache.get.return_value = CachedWorkflowAnalysis(
        dependencies=deps,
        resolution=resolution,
    )
    service = _service(tmp_path, cache)
    resolver = Mock()

    assert service.analyze_and_resolve_workflow("workflow", resolver) == (
        deps,
        resolution,
    )
    resolver.assert_not_called()
    cache.set.assert_not_called()


def test_analyze_and_resolve_parses_resolves_and_caches_on_miss(tmp_path, monkeypatch):
    deps = WorkflowDependencies(workflow_name="workflow")
    resolution = ResolutionResult(workflow_name="workflow")
    cache = Mock()
    cache.get.return_value = None

    class FakeParser:
        def __init__(self, workflow_path, *, cec_path, builtin_versions_repository):
            self.workflow_path = workflow_path
            self.cec_path = cec_path
            self.builtin_versions_repository = builtin_versions_repository

        def analyze_dependencies(self):
            return deps

    monkeypatch.setattr(
        "comfygit_core.services.workflow_analysis_cache.WorkflowDependencyParser",
        FakeParser,
    )
    service = _service(tmp_path, cache)
    resolver = Mock(return_value=resolution)

    assert service.analyze_and_resolve_workflow("workflow", resolver) == (
        deps,
        resolution,
    )
    resolver.assert_called_once_with(deps)
    cache.set.assert_called_once()
    assert cache.set.call_args.kwargs["dependencies"] is deps
    assert cache.set.call_args.kwargs["resolution"] is resolution


def test_analyze_and_resolve_reresolves_cached_dependencies_without_resolution(tmp_path):
    deps = WorkflowDependencies(workflow_name="workflow")
    resolution = ResolutionResult(workflow_name="workflow")
    cache = Mock()
    cache.get.return_value = CachedWorkflowAnalysis(dependencies=deps)
    service = _service(tmp_path, cache)
    resolver = Mock(return_value=resolution)

    assert service.analyze_and_resolve_workflow("workflow", resolver) == (
        deps,
        resolution,
    )
    resolver.assert_called_once_with(deps)
    cache.set.assert_called_once()
    assert cache.set.call_args.kwargs["dependencies"] is deps
    assert cache.set.call_args.kwargs["resolution"] is resolution


def test_analyze_and_resolve_reresolves_partial_cache_hit(tmp_path):
    deps = WorkflowDependencies(workflow_name="workflow")
    resolution = ResolutionResult(workflow_name="workflow")
    cache = Mock()
    cache.get.return_value = CachedWorkflowAnalysis(
        dependencies=deps,
        needs_reresolution=True,
    )
    service = _service(tmp_path, cache)
    resolver = Mock(return_value=resolution)

    assert service.analyze_and_resolve_workflow("workflow", resolver) == (
        deps,
        resolution,
    )
    resolver.assert_called_once_with(deps)
    cache.set.assert_called_once()
    assert cache.set.call_args.kwargs["dependencies"] is deps
    assert cache.set.call_args.kwargs["resolution"] is resolution
