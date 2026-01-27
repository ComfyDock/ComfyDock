"""Merging module for atomic, semantic merge operations.

This module provides intelligent merge capabilities for ComfyGit environments,
handling the complexity of shared dependencies across workflows.
"""

from .atomic_executor import AtomicMergeExecutor
from .merge_validator import MergeValidator
from .semantic_merger import SemanticMerger

__all__ = ["SemanticMerger", "MergeValidator", "AtomicMergeExecutor"]
