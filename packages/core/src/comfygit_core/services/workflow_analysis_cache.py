"""Cached workflow dependency analysis coordination."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ..analyzers.workflow_dependency_parser import WorkflowDependencyParser
from ..logging.logging_config import get_logger
from ..models.workflow import ResolutionResult, WorkflowDependencies
from .workflow_file_store import WorkflowFileStore

if TYPE_CHECKING:
    from ..caching.workflow_cache import CachedWorkflowAnalysis
    from ..repositories.comfyui_builtin_versions_repository import (
        ComfyUIBuiltinVersionsRepository,
    )

logger = get_logger(__name__)


class WorkflowAnalysisCacheStore(Protocol):
    """Cache operations required by workflow dependency analysis."""

    def get(
        self,
        env_name: str,
        workflow_name: str,
        workflow_path: Path,
        pyproject_path: Path | None = None,
    ) -> CachedWorkflowAnalysis | None:
        """Return cached workflow analysis if still valid."""

    def set(
        self,
        env_name: str,
        workflow_name: str,
        workflow_path: Path,
        dependencies: WorkflowDependencies,
        resolution: ResolutionResult | None = None,
        pyproject_path: Path | None = None,
    ) -> None:
        """Store workflow analysis and optional resolution."""


class WorkflowAnalysisCache:
    """Coordinates workflow parsing with persistent analysis/resolution cache."""

    def __init__(
        self,
        *,
        workflow_file_store: WorkflowFileStore,
        workflow_cache: WorkflowAnalysisCacheStore,
        environment_name: str,
        cec_path: Path,
        pyproject_path: Path | None,
        builtin_versions_repository: ComfyUIBuiltinVersionsRepository | None,
    ) -> None:
        self.workflow_file_store = workflow_file_store
        self.workflow_cache = workflow_cache
        self.environment_name = environment_name
        self.cec_path = cec_path
        self.pyproject_path = pyproject_path
        self.builtin_versions_repository = builtin_versions_repository

    def analyze_and_resolve_workflow(
        self,
        name: str,
        resolve: Callable[[WorkflowDependencies], ResolutionResult],
    ) -> tuple[WorkflowDependencies, ResolutionResult]:
        """Analyze and resolve a workflow, using cached data when valid."""
        workflow_path = self.workflow_file_store.get_workflow_path(name)
        cached = self.workflow_cache.get(
            env_name=self.environment_name,
            workflow_name=name,
            workflow_path=workflow_path,
            pyproject_path=self.pyproject_path,
        )

        if cached and not cached.needs_reresolution and cached.resolution:
            logger.debug(f"Cache HIT (full) for workflow '{name}'")
            return (cached.dependencies, cached.resolution)

        if cached:
            logger.debug(f"Cache PARTIAL HIT for workflow '{name}' - re-resolving")
            dependencies = cached.dependencies
        else:
            logger.debug(f"Cache MISS for workflow '{name}' - full analysis + resolution")
            dependencies = self._parse_workflow(workflow_path)

        resolution = resolve(dependencies)
        self.workflow_cache.set(
            env_name=self.environment_name,
            workflow_name=name,
            workflow_path=workflow_path,
            dependencies=dependencies,
            resolution=resolution,
            pyproject_path=self.pyproject_path,
        )
        return (dependencies, resolution)

    def _parse_workflow(self, workflow_path: Path) -> WorkflowDependencies:
        parser = WorkflowDependencyParser(
            workflow_path,
            cec_path=self.cec_path,
            builtin_versions_repository=self.builtin_versions_repository,
        )
        return parser.analyze_dependencies()
