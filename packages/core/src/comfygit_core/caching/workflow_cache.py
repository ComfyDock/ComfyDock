"""Persistent cache for workflow analysis AND resolution results.

Provides SQLite-backed caching with session optimization and smart
invalidation based on resolution context changes.
"""
import json
import time
from dataclasses import asdict, fields
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING

from ..infrastructure.sqlite_manager import SQLiteManager
from ..logging.logging_config import get_logger
from ..models.workflow import ResolutionResult, WorkflowDependencies
from ..utils.workflow_hash import compute_workflow_hash


def _get_version() -> str:
    """Get comfygit_core version."""
    try:
        return version('comfygit-core')
    except Exception:
        return "0.0.0"  # Fallback for development

if TYPE_CHECKING:
    from ..managers.pyproject_manager import PyprojectManager
    from ..repositories.model_repository import ModelRepository
    from ..repositories.workspace_config_repository import WorkspaceConfigRepository

logger = get_logger(__name__)

# Bump when DB schema OR resolution format changes
# Breaking changes requiring version bump:
# - Database: Add/remove/rename columns
# - Resolution: Change node ID format (e.g., subgraph scoping), WorkflowNodeWidgetRef structure, etc.
# - Model index: Hash algorithm changes (blake3 -> xxhash)
# Migration: Wipes cache and rebuilds (cache is ephemeral)
SCHEMA_VERSION = 5  # Invalidate after model hash algorithm change (blake3 -> xxhash)


class CachedWorkflowAnalysis:
    """Container for cached workflow data."""
    def __init__(
        self,
        dependencies: WorkflowDependencies,
        resolution: ResolutionResult | None = None,
        needs_reresolution: bool = False
    ):
        self.dependencies = dependencies
        self.resolution = resolution
        self.needs_reresolution = needs_reresolution


class WorkflowCacheRepository:
    """Workflow analysis and resolution cache with smart invalidation.

    Lookup phases:
    1. Session cache (in-memory, same CLI invocation)
    2. Workflow mtime + size fast path (~1µs)
    3. Pyproject mtime fast-reject path (~1µs)
    4. Resolution context hash check (~7ms)
    5. Content hash fallback (~20ms)
    """

    def __init__(
        self,
        db_path: Path,
        pyproject_manager: "PyprojectManager | None" = None,
        model_repository: "ModelRepository | None" = None,
        workspace_config_manager: "WorkspaceConfigRepository | None" = None
    ):
        """Initialize workflow cache repository.

        Args:
            db_path: Path to SQLite database file
            pyproject_manager: Manager for pyproject.toml access (for context hashing)
            model_repository: Model repository (for context hashing)
            workspace_config_manager: Workspace config for model sync timestamp (for context hashing)
        """
        self.db_path = db_path
        self.sqlite = SQLiteManager(db_path)
        self.pyproject_manager = pyproject_manager
        self.model_repository = model_repository
        self.workspace_config_manager = workspace_config_manager
        self._session_cache: dict[str, CachedWorkflowAnalysis] = {}

        # Ensure schema exists
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create database schema if needed."""
        # Create schema info table
        self.sqlite.create_table("""
            CREATE TABLE IF NOT EXISTS schema_info (
                version INTEGER PRIMARY KEY
            )
        """)

        # Check version and migrate if needed
        current_version = self._get_schema_version()
        if current_version != SCHEMA_VERSION:
            self._migrate_schema(current_version, SCHEMA_VERSION)
        else:
            # Create v2 schema if not exists
            self._create_v2_schema()

    def _get_schema_version(self) -> int:
        """Get current schema version.

        Returns:
            Schema version (0 if not initialized)
        """
        results = self.sqlite.execute_query("SELECT version FROM schema_info")
        if not results:
            return 0
        return results[0]['version']

    def _create_v2_schema(self) -> None:
        """Create v2 schema tables and indices."""
        self.sqlite.create_table("""
            CREATE TABLE IF NOT EXISTS workflow_cache (
                workflow_name TEXT NOT NULL,
                environment_name TEXT NOT NULL,
                workflow_hash TEXT NOT NULL,
                workflow_mtime REAL NOT NULL,
                workflow_size INTEGER NOT NULL,
                resolution_context_hash TEXT NOT NULL,
                pyproject_mtime REAL NOT NULL,
                models_sync_time TEXT,
                comfygit_version TEXT NOT NULL,
                dependencies_json TEXT NOT NULL,
                resolution_json TEXT,
                cached_at INTEGER NOT NULL,
                PRIMARY KEY (environment_name, workflow_name)
            )
        """)

        self.sqlite.create_table("""
            CREATE INDEX IF NOT EXISTS idx_workflow_hash
            ON workflow_cache(environment_name, workflow_hash)
        """)

        self.sqlite.create_table("""
            CREATE INDEX IF NOT EXISTS idx_resolution_context
            ON workflow_cache(environment_name, resolution_context_hash)
        """)

    def _migrate_schema(self, from_version: int, to_version: int) -> None:
        """Migrate database schema between versions.

        Args:
            from_version: Current schema version
            to_version: Target schema version
        """
        if from_version == to_version:
            return

        logger.info(f"Migrating workflow cache schema v{from_version} → v{to_version}")

        # Drop and recreate (cache is ephemeral)
        self.sqlite.execute_write("DROP TABLE IF EXISTS workflow_cache")
        self.sqlite.execute_write("DROP INDEX IF EXISTS idx_workflow_hash")
        self.sqlite.execute_write("DROP INDEX IF EXISTS idx_resolution_context")

        # Create v2 schema
        self._create_v2_schema()

        # Update version
        self.sqlite.execute_write("DELETE FROM schema_info")
        self.sqlite.execute_write("INSERT INTO schema_info (version) VALUES (?)", (to_version,))

        logger.info("Schema migration complete")

    def get(
        self,
        env_name: str,
        workflow_name: str,
        workflow_path: Path,
        pyproject_path: Path | None = None
    ) -> CachedWorkflowAnalysis | None:
        """Get cached workflow analysis + resolution with smart invalidation.

        Uses multi-phase lookup:
        1. Session cache (instant, includes mtime for auto-invalidation)
        2. Workflow mtime + size match (fast)
        3. Pyproject mtime fast-reject (instant)
        4. Resolution context hash check (moderate)
        5. Content hash fallback (slow)

        Args:
            env_name: Environment name
            workflow_name: Workflow name
            workflow_path: Path to workflow file
            pyproject_path: Path to pyproject.toml (for context checking)

        Returns:
            CachedWorkflowAnalysis with dependencies and resolution, or None if cache miss
        """
        import time
        start_time = time.perf_counter()

        # Get workflow file stats (needed for session key and later phases)
        try:
            stat = workflow_path.stat()
            mtime = stat.st_mtime
            size = stat.st_size
        except OSError as e:
            logger.warning(f"Failed to stat workflow file {workflow_path}: {e}")
            return None

        # Phase 1: Check session cache (with mtime in key for auto-invalidation)
        # This ensures session cache automatically invalidates when file changes,
        # critical for long-running services where Environment instances persist
        session_key = f"{env_name}:{workflow_name}:{mtime}"

        if session_key in self._session_cache:
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.debug(f"[CACHE] Session HIT for '{workflow_name}' ({elapsed:.2f}ms)")
            return self._session_cache[session_key]

        # Phase 2: Fast path - mtime + size match
        query_start = time.perf_counter()
        query = """
            SELECT workflow_hash, dependencies_json, resolution_json,
                   resolution_context_hash, pyproject_mtime, models_sync_time, comfygit_version
            FROM workflow_cache
            WHERE environment_name = ? AND workflow_name = ?
              AND workflow_mtime = ? AND workflow_size = ?
        """
        results = self.sqlite.execute_query(query, (env_name, workflow_name, mtime, size))
        query_elapsed = (time.perf_counter() - query_start) * 1000

        cached_row = None
        if results:
            cached_row = results[0]
            logger.debug(f"[CACHE] DB query (mtime+size) HIT for '{workflow_name}' ({query_elapsed:.2f}ms)")

            # Verify content hash matches (prevents stale cache from race conditions)
            # This catches the case where another process stored a resolution
            # computed against different content but with the same mtime
            hash_start = time.perf_counter()
            try:
                current_hash = compute_workflow_hash(workflow_path)
            except Exception as e:
                logger.warning(f"Failed to compute workflow hash for {workflow_path}: {e}")
                return None
            hash_elapsed = (time.perf_counter() - hash_start) * 1000

            if current_hash != cached_row['workflow_hash']:
                logger.debug(
                    f"[CACHE] mtime+size matched but hash differs for '{workflow_name}' "
                    f"(cached={cached_row['workflow_hash']}, current={current_hash}, {hash_elapsed:.2f}ms) - treating as MISS"
                )
                # Content changed - cache is stale
                return None

            logger.debug(f"[CACHE] Hash verification passed for '{workflow_name}' ({hash_elapsed:.2f}ms)")
        else:
            logger.debug(f"[CACHE] DB query (mtime+size) MISS for '{workflow_name}' ({query_elapsed:.2f}ms)")
            # mtime+size miss = file metadata changed, so cache is definitely stale
            # No need to check content hash - if mtime changed, the resolution is outdated

        if not cached_row:
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.debug(f"[CACHE] MISS (workflow content changed) for '{workflow_name}' ({elapsed:.2f}ms total)")
            return None

        # Deserialize dependencies (always valid if workflow content matches)
        deser_start = time.perf_counter()
        dependencies = self._deserialize_dependencies(cached_row['dependencies_json'])
        deser_elapsed = (time.perf_counter() - deser_start) * 1000
        logger.debug(f"[CACHE] Deserialization took {deser_elapsed:.2f}ms")

        # Check version match
        if cached_row['comfygit_version'] != _get_version():
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.debug(f"[CACHE] PARTIAL HIT (version mismatch) for '{workflow_name}' ({elapsed:.2f}ms total)")
            cached = CachedWorkflowAnalysis(
                dependencies=dependencies,
                resolution=None,
                needs_reresolution=True
            )
            self._session_cache[session_key] = cached
            return cached

        # Phase 4: Check resolution context
        if pyproject_path and pyproject_path.exists():
            pyproject_mtime = pyproject_path.stat().st_mtime
            cached_pyproject_mtime = cached_row['pyproject_mtime']
            mtime_diff = abs(pyproject_mtime - cached_pyproject_mtime)

            logger.debug(f"[CACHE] Pyproject mtime check for '{workflow_name}': current={pyproject_mtime:.6f}, cached={cached_pyproject_mtime:.6f}, diff={mtime_diff:.6f}s")

            # Fast reject: if pyproject hasn't been touched, context can't have changed
            # UNLESS the model index has changed (checked via models_sync_time)
            if pyproject_mtime == cached_pyproject_mtime:
                # Check if model index has changed since cache was created
                cached_sync_time = cached_row.get('models_sync_time')
                current_sync_time = None

                if self.workspace_config_manager:
                    try:
                        config = self.workspace_config_manager.load()
                        if config.global_model_directory and config.global_model_directory.last_sync:
                            current_sync_time = config.global_model_directory.last_sync
                    except Exception as e:
                        logger.warning(f"Failed to check current model sync time: {e}")

                # Compare sync times (both might be None, which is fine)
                if cached_sync_time != current_sync_time:
                    # Model index changed - invalidate cache
                    logger.debug(
                        f"[CACHE] Model index changed for '{workflow_name}': "
                        f"cached_sync={cached_sync_time}, current_sync={current_sync_time}"
                    )
                    cached = CachedWorkflowAnalysis(
                        dependencies=dependencies,
                        resolution=None,
                        needs_reresolution=True
                    )
                    self._session_cache[session_key] = cached
                    elapsed = (time.perf_counter() - start_time) * 1000
                    logger.debug(f"[CACHE] PARTIAL HIT (model index changed) for '{workflow_name}' ({elapsed:.2f}ms total)")
                    return cached

                # Nothing changed - full cache hit
                resolution = self._deserialize_resolution(cached_row['resolution_json']) if cached_row['resolution_json'] else None
                cached = CachedWorkflowAnalysis(
                    dependencies=dependencies,
                    resolution=resolution,
                    needs_reresolution=False
                )
                self._session_cache[session_key] = cached
                elapsed = (time.perf_counter() - start_time) * 1000
                logger.debug(f"[CACHE] FULL HIT (pyproject unchanged, model index unchanged) for '{workflow_name}' ({elapsed:.2f}ms total)")
                return cached

            logger.debug(f"[CACHE] Pyproject mtime changed for '{workflow_name}', computing context hash...")

            # Pyproject changed - check if it affects THIS workflow
            if self.pyproject_manager and self.model_repository:
                context_start = time.perf_counter()
                current_context_hash = self._compute_resolution_context_hash(
                    dependencies,
                    workflow_name
                )
                context_elapsed = (time.perf_counter() - context_start) * 1000
                logger.debug(f"[CACHE] Context hash computation took {context_elapsed:.2f}ms for '{workflow_name}'")

                if current_context_hash == cached_row['resolution_context_hash']:
                    # Pyproject changed but not for THIS workflow - still valid
                    # Update pyproject_mtime to avoid recomputing context hash next time
                    self._update_pyproject_mtime(env_name, workflow_name, pyproject_mtime)

                    resolution = self._deserialize_resolution(cached_row['resolution_json']) if cached_row['resolution_json'] else None
                    cached = CachedWorkflowAnalysis(
                        dependencies=dependencies,
                        resolution=resolution,
                        needs_reresolution=False
                    )
                    self._session_cache[session_key] = cached
                    elapsed = (time.perf_counter() - start_time) * 1000
                    logger.debug(f"[CACHE] FULL HIT (context unchanged) for '{workflow_name}' ({elapsed:.2f}ms total)")
                    return cached
                else:
                    elapsed = (time.perf_counter() - start_time) * 1000
                    logger.debug(f"[CACHE] PARTIAL HIT (context changed) for '{workflow_name}' - need re-resolution ({elapsed:.2f}ms total)")

        # Context changed or can't verify - return dependencies but signal re-resolution needed
        cached = CachedWorkflowAnalysis(
            dependencies=dependencies,
            resolution=None,
            needs_reresolution=True
        )
        self._session_cache[session_key] = cached
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.debug(f"[CACHE] PARTIAL HIT (context verification failed) for '{workflow_name}' ({elapsed:.2f}ms total)")
        return cached

    def set(
        self,
        env_name: str,
        workflow_name: str,
        workflow_path: Path,
        dependencies: WorkflowDependencies,
        resolution: ResolutionResult | None = None,
        pyproject_path: Path | None = None
    ) -> None:
        """Store workflow analysis and resolution in cache.

        Args:
            env_name: Environment name
            workflow_name: Workflow name
            workflow_path: Path to workflow file
            dependencies: Analysis result to cache
            resolution: Resolution result to cache (optional)
            pyproject_path: Path to pyproject.toml (for context hash)
        """
        # Compute workflow hash
        try:
            workflow_hash = compute_workflow_hash(workflow_path)
        except Exception as e:
            logger.warning(f"Failed to compute workflow hash, skipping cache: {e}")
            return

        # Get workflow file stats
        try:
            stat = workflow_path.stat()
            workflow_mtime = stat.st_mtime
            workflow_size = stat.st_size
        except OSError as e:
            logger.warning(f"Failed to stat workflow file, skipping cache: {e}")
            return

        # Get pyproject mtime
        pyproject_mtime = 0.0
        if pyproject_path and pyproject_path.exists():
            try:
                pyproject_mtime = pyproject_path.stat().st_mtime
            except OSError:
                pass

        # Compute resolution context hash
        resolution_context_hash = ""
        if self.pyproject_manager and self.model_repository:
            resolution_context_hash = self._compute_resolution_context_hash(
                dependencies,
                workflow_name
            )

        # Get models_sync_time for cache invalidation check
        models_sync_time = None
        if self.workspace_config_manager:
            try:
                config = self.workspace_config_manager.load()
                if config.global_model_directory and config.global_model_directory.last_sync:
                    models_sync_time = config.global_model_directory.last_sync
            except Exception:
                pass

        # Serialize data
        dependencies_json = self._serialize_dependencies(dependencies)
        resolution_json = self._serialize_resolution(resolution) if resolution else None
        comfygit_version = _get_version()

        # Store in SQLite
        query = """
            INSERT OR REPLACE INTO workflow_cache
            (environment_name, workflow_name, workflow_hash, workflow_mtime,
             workflow_size, resolution_context_hash, pyproject_mtime, models_sync_time,
             comfygit_version, dependencies_json, resolution_json, cached_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cached_at = int(time.time())
        self.sqlite.execute_write(
            query,
            (env_name, workflow_name, workflow_hash, workflow_mtime, workflow_size,
             resolution_context_hash, pyproject_mtime, models_sync_time, comfygit_version,
             dependencies_json, resolution_json, cached_at)
        )

        # Update session cache (with mtime in key for auto-invalidation)
        session_key = f"{env_name}:{workflow_name}:{workflow_mtime}"
        self._session_cache[session_key] = CachedWorkflowAnalysis(
            dependencies=dependencies,
            resolution=resolution,
            needs_reresolution=False
        )

        logger.debug(f"Cached workflow '{workflow_name}' (hash={workflow_hash}, context={resolution_context_hash})")

    def invalidate(self, env_name: str, workflow_name: str | None = None) -> None:
        """Invalidate cache entries.

        Args:
            env_name: Environment name
            workflow_name: Optional workflow name (if None, invalidate entire environment)
        """
        if workflow_name:
            # Invalidate specific workflow
            query = "DELETE FROM workflow_cache WHERE environment_name = ? AND workflow_name = ?"
            self.sqlite.execute_write(query, (env_name, workflow_name))

            # Clear from session cache - need to clear all mtime variants
            # Session keys now include mtime: "env:workflow:mtime"
            prefix = f"{env_name}:{workflow_name}:"
            keys_to_remove = [k for k in self._session_cache if k.startswith(prefix)]
            for key in keys_to_remove:
                del self._session_cache[key]

            logger.debug(f"Invalidated cache for workflow '{workflow_name}'")
        else:
            # Invalidate entire environment
            query = "DELETE FROM workflow_cache WHERE environment_name = ?"
            self.sqlite.execute_write(query, (env_name,))

            # Clear matching session cache entries
            keys_to_remove = [k for k in self._session_cache if k.startswith(f"{env_name}:")]
            for key in keys_to_remove:
                del self._session_cache[key]

            logger.debug(f"Invalidated cache for environment '{env_name}'")

    def _update_pyproject_mtime(self, env_name: str, workflow_name: str, new_mtime: float) -> None:
        """Update pyproject_mtime in cache after successful context check.

        This optimization avoids recomputing context hash on subsequent runs
        when pyproject hasn't changed.

        Args:
            env_name: Environment name
            workflow_name: Workflow name
            new_mtime: New pyproject mtime to store
        """
        query = """
            UPDATE workflow_cache
            SET pyproject_mtime = ?
            WHERE environment_name = ? AND workflow_name = ?
        """
        self.sqlite.execute_write(query, (new_mtime, env_name, workflow_name))
        logger.debug(f"Updated pyproject_mtime for '{workflow_name}' to {new_mtime}")

    def _serialize_dependencies(self, dependencies: WorkflowDependencies) -> str:
        """Serialize WorkflowDependencies to JSON string.

        Args:
            dependencies: Dependencies object

        Returns:
            JSON string
        """
        # Convert to dict and serialize
        deps_dict = asdict(dependencies)
        return json.dumps(deps_dict)

    def _deserialize_dependencies(self, dependencies_json: str) -> WorkflowDependencies:
        """Deserialize JSON string to WorkflowDependencies.

        Uses **kwargs to auto-forward new fields without explicit mapping.
        """
        from ..models.workflow import WorkflowNode, WorkflowNodeWidgetRef

        deps_dict = json.loads(dependencies_json)

        # Reconstruct nested dataclasses
        builtin_nodes = [WorkflowNode(**node) for node in deps_dict.get('builtin_nodes', [])]
        version_gated_nodes = [WorkflowNode(**node) for node in deps_dict.get('version_gated_nodes', [])]
        non_builtin_nodes = [WorkflowNode(**node) for node in deps_dict.get('non_builtin_nodes', [])]
        found_models = [WorkflowNodeWidgetRef(**ref) for ref in deps_dict.get('found_models', [])]

        # Auto-forward all other fields, override nested objects.
        # Filter by runtime dataclass fields to tolerate mixed package versions
        # (e.g., cache contains version_gated_nodes but older runtime class does not).
        dependency_field_names = {f.name for f in fields(WorkflowDependencies)}
        simple_fields = {
            k: v for k, v in deps_dict.items()
            if (
                k in dependency_field_names
                and k not in ('builtin_nodes', 'version_gated_nodes', 'non_builtin_nodes', 'found_models')
            )
        }

        kwargs = {
            **simple_fields,
            "builtin_nodes": builtin_nodes,
            "non_builtin_nodes": non_builtin_nodes,
            "found_models": found_models,
        }
        if "version_gated_nodes" in dependency_field_names:
            kwargs["version_gated_nodes"] = version_gated_nodes

        return WorkflowDependencies(
            **kwargs
        )

    def _serialize_resolution(self, resolution: ResolutionResult) -> str:
        """Serialize ResolutionResult to JSON string.

        Args:
            resolution: Resolution result object

        Returns:
            JSON string
        """
        from pathlib import Path

        def convert_paths(obj):
            """Recursively convert Path objects to strings for JSON serialization."""
            if isinstance(obj, Path):
                return str(obj)
            elif isinstance(obj, dict):
                return {k: convert_paths(v) for k, v in obj.items()}
            elif isinstance(obj, list | tuple):
                return [convert_paths(item) for item in obj]
            return obj

        res_dict = asdict(resolution)
        res_dict = convert_paths(res_dict)
        return json.dumps(res_dict)

    def _deserialize_resolution(self, resolution_json: str) -> ResolutionResult:
        """Deserialize JSON string to ResolutionResult.

        Args:
            resolution_json: JSON string

        Returns:
            ResolutionResult object
        """
        from pathlib import Path

        from ..models.node_mapping import GlobalNodePackage, GlobalNodePackageVersion
        from ..models.shared import ModelWithLocation
        from ..models.workflow import (
            DownloadResult,
            ResolvedModel,
            ResolvedNodePackage,
            WorkflowNode,
            WorkflowNodeWidgetRef,
        )

        res_dict = json.loads(resolution_json)

        # Helper to reconstruct GlobalNodePackage with nested versions
        def reconstruct_package_data(pkg_data: dict | None) -> GlobalNodePackage | None:
            if pkg_data is None:
                return None
            # Reconstruct nested GlobalNodePackageVersion objects
            versions = pkg_data.get('versions', {})
            if versions:
                versions = {
                    k: GlobalNodePackageVersion(**v) if isinstance(v, dict) else v
                    for k, v in versions.items()
                }
            return GlobalNodePackage(
                **{**pkg_data, 'versions': versions}
            )

        # Reconstruct ResolvedNodePackage with nested package_data
        def reconstruct_node_package(node_dict: dict) -> ResolvedNodePackage:
            pkg_data = node_dict.get('package_data')
            return ResolvedNodePackage(
                **{**node_dict, 'package_data': reconstruct_package_data(pkg_data)}
            )

        # Reconstruct ResolvedModel with nested objects
        # Uses **kwargs to auto-forward new fields without explicit mapping
        def reconstruct_resolved_model(model_dict: dict) -> ResolvedModel:
            # Fields requiring special handling (nested objects, Path conversion)
            reference = WorkflowNodeWidgetRef(**model_dict['reference'])

            resolved_model = None
            if model_dict.get('resolved_model'):
                resolved_model = ModelWithLocation(**model_dict['resolved_model'])

            target_path = None
            if model_dict.get('target_path'):
                target_path = Path(model_dict['target_path'])

            # Auto-forward all other fields via **kwargs
            # Exclude fields we're handling explicitly to avoid duplicate kwargs
            simple_fields = {
                k: v for k, v in model_dict.items()
                if k not in ('reference', 'resolved_model', 'target_path')
            }

            return ResolvedModel(
                **simple_fields,
                reference=reference,
                resolved_model=resolved_model,
                target_path=target_path,
            )

        # Reconstruct nested dataclasses
        nodes_resolved = [reconstruct_node_package(node) for node in res_dict.get('nodes_resolved', [])]
        nodes_version_gated = [WorkflowNode(**node) for node in res_dict.get('nodes_version_gated', [])]
        nodes_uninstallable = [
            reconstruct_node_package(node) for node in res_dict.get('nodes_uninstallable', [])
        ]
        nodes_unresolved = [WorkflowNode(**node) for node in res_dict.get('nodes_unresolved', [])]
        nodes_ambiguous = [
            [reconstruct_node_package(pkg) for pkg in group]
            for group in res_dict.get('nodes_ambiguous', [])
        ]

        models_resolved = [reconstruct_resolved_model(model) for model in res_dict.get('models_resolved', [])]
        models_unresolved = [WorkflowNodeWidgetRef(**ref) for ref in res_dict.get('models_unresolved', [])]
        models_ambiguous = [
            [reconstruct_resolved_model(model) for model in group]
            for group in res_dict.get('models_ambiguous', [])
        ]

        download_results = [DownloadResult(**dl) for dl in res_dict.get('download_results', [])]

        # Auto-forward any new fields, override nested objects
        simple_fields = {
            k: v for k, v in res_dict.items()
            if k not in (
                'nodes_resolved', 'nodes_version_gated', 'nodes_uninstallable',
                'nodes_unresolved', 'nodes_ambiguous',
                'models_resolved', 'models_unresolved', 'models_ambiguous',
                'download_results'
            )
        }

        return ResolutionResult(
            **simple_fields,
            nodes_resolved=nodes_resolved,
            nodes_version_gated=nodes_version_gated,
            nodes_uninstallable=nodes_uninstallable,
            nodes_unresolved=nodes_unresolved,
            nodes_ambiguous=nodes_ambiguous,
            models_resolved=models_resolved,
            models_unresolved=models_unresolved,
            models_ambiguous=models_ambiguous,
            download_results=download_results
        )

    def _compute_resolution_context_hash(
        self,
        dependencies: WorkflowDependencies,
        workflow_name: str
    ) -> str:
        """Compute workflow-specific resolution context hash.

        Only includes pyproject/model data that affects THIS workflow's resolution.

        Args:
            dependencies: Workflow dependencies
            workflow_name: Workflow name

        Returns:
            16-character hex hash of resolution context
        """
        if not self.pyproject_manager or not self.model_repository:
            return ""

        import time

        import blake3

        context_start = time.perf_counter()
        context = {}

        # 1. Custom node mappings for nodes in THIS workflow
        step_start = time.perf_counter()
        node_types = {n.type for n in dependencies.non_builtin_nodes}
        custom_map = self.pyproject_manager.workflows.get_custom_node_map(workflow_name)
        context["custom_mappings"] = {
            node_type: custom_map[node_type]
            for node_type in node_types
            if node_type in custom_map
        }
        step_elapsed = (time.perf_counter() - step_start) * 1000
        logger.debug(f"[CONTEXT] Step 1 (custom mappings) took {step_elapsed:.2f}ms")

        # 2. Declared packages for nodes THIS workflow uses
        # Use authoritative workflow.nodes list instead of inferring from workflow content
        step_start = time.perf_counter()

        # Read nodes list from workflow config (written by apply_resolution)
        workflow_config = self.pyproject_manager.workflows.get_all_with_resolutions().get(workflow_name, {})
        relevant_packages = set(workflow_config.get('nodes', []))

        # Get global package metadata
        declared_packages = self.pyproject_manager.nodes.get_existing()

        context["declared_packages"] = {
            pkg: {
                "version": declared_packages[pkg].version,
                "repository": declared_packages[pkg].repository,
                "source": declared_packages[pkg].source
            }
            for pkg in relevant_packages
            if pkg in declared_packages
        }
        step_elapsed = (time.perf_counter() - step_start) * 1000
        logger.debug(f"[CONTEXT] Step 2 (declared packages) took {step_elapsed:.2f}ms")

        # 3. Model entries from pyproject for THIS workflow
        step_start = time.perf_counter()
        workflow_models = self.pyproject_manager.workflows.get_workflow_models(workflow_name)
        model_pyproject_data = {}
        for manifest_model in workflow_models:
            for ref in manifest_model.nodes:
                ref_key = f"{ref.node_id}_{ref.widget_index}"
                model_pyproject_data[ref_key] = {
                    "hash": manifest_model.hash,
                    "status": manifest_model.status,
                    "criticality": manifest_model.criticality,
                    "sources": manifest_model.sources,
                    "relative_path": manifest_model.relative_path,
                }

        context["workflow_models_pyproject"] = model_pyproject_data
        step_elapsed = (time.perf_counter() - step_start) * 1000
        logger.debug(f"[CONTEXT] Step 3 (workflow models) took {step_elapsed:.2f}ms")

        # 4. Model index subset (only models THIS workflow references)
        step_start = time.perf_counter()
        model_index_subset = {}
        for model_ref in dependencies.found_models:
            filename = Path(model_ref.widget_value).name
            models = self.model_repository.find_by_filename(filename)
            if models:
                model_index_subset[filename] = [m.hash for m in models]

        context["model_index_subset"] = model_index_subset
        step_elapsed = (time.perf_counter() - step_start) * 1000
        logger.debug(f"[CONTEXT] Step 4 (model index queries, {len(dependencies.found_models)} models) took {step_elapsed:.2f}ms")

        # 5. Model index sync time (invalidate when model index changes)
        step_start = time.perf_counter()
        if self.workspace_config_manager:
            try:
                config = self.workspace_config_manager.load()
                if config.global_model_directory and config.global_model_directory.last_sync:
                    context["models_sync_time"] = config.global_model_directory.last_sync
                else:
                    context["models_sync_time"] = None
            except Exception as e:
                logger.warning(f"Failed to get model sync time: {e}")
                context["models_sync_time"] = None
        else:
            context["models_sync_time"] = None
        step_elapsed = (time.perf_counter() - step_start) * 1000
        logger.debug(f"[CONTEXT] Step 5 (model sync time) took {step_elapsed:.2f}ms")

        # 6. Comfygit version (global invalidator)
        context["comfygit_version"] = _get_version()

        # Hash the normalized context
        step_start = time.perf_counter()
        context_json = json.dumps(context, sort_keys=True)
        hasher = blake3.blake3()
        hasher.update(context_json.encode('utf-8'))
        hash_result = hasher.hexdigest()[:16]
        step_elapsed = (time.perf_counter() - step_start) * 1000
        logger.debug(f"[CONTEXT] Step 6 (JSON + hash) took {step_elapsed:.2f}ms")

        total_elapsed = (time.perf_counter() - context_start) * 1000
        logger.debug(f"[CONTEXT] Total context hash computation: {total_elapsed:.2f}ms")

        return hash_result
