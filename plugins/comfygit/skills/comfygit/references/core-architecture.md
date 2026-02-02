# ComfyGit Core Architecture

Library internals, data flow, and key abstractions for understanding and extending ComfyGit.

## Table of Contents
- [Layered Architecture](#layered-architecture)
- [Key Entry Points](#key-entry-points)
- [Managers](#managers)
- [Resolution System](#resolution-system)
- [Data Models](#data-models)
- [Protocols (Callbacks)](#protocols-callbacks)
- [Error Handling](#error-handling)

---

## Layered Architecture

```
┌──────────────────────────────────────┐
│  Public API Layer                    │
│  Workspace, Environment              │
└───────────────┬──────────────────────┘
                │
┌───────────────▼──────────────────────┐
│  Managers Layer                      │
│  Node, Workflow, Git, Model, UV      │
└───────────────┬──────────────────────┘
                │
┌───────────────▼──────────────────────┐
│  Resolvers & Services Layer          │
│  GlobalNodeResolver, ModelResolver   │
│  NodeLookupService, ModelDownloader  │
└───────────────┬──────────────────────┘
                │
┌───────────────▼──────────────────────┐
│  Repositories Layer                  │
│  ModelRepository, WorkflowRepository │
│  SQLite caching, JSON config         │
└───────────────┬──────────────────────┘
                │
┌───────────────▼──────────────────────┐
│  Clients & Utils Layer               │
│  Registry, GitHub, CivitAI clients   │
│  Git utils, filesystem helpers       │
└──────────────────────────────────────┘
```

**Key Principles:**
- **Library-first**: No print/input in core - all UI via protocols
- **Immutable managers**: Stateless, dependencies injected at construction
- **Protocol-driven**: Strategies injected for customizable behavior

---

## Key Entry Points

### WorkspaceFactory

```python
from comfygit_core.factories import WorkspaceFactory

# Discover existing workspace
workspace = WorkspaceFactory.find()  # Uses COMFYGIT_HOME or ~/comfygit

# Create new workspace
workspace = WorkspaceFactory.create(Path("/path/to/workspace"))

# Get paths without validation
paths = WorkspaceFactory.get_paths()
```

### Workspace

```python
# Environment management
envs = workspace.list_environments()
env = workspace.get_environment("production")
env = workspace.create_environment(
    name="new-env",
    python_version="3.12",
    comfyui_version="snapshot",
    torch_backend="cu121"
)
workspace.delete_environment("old-env")

# Model management
models = workspace.list_models()
results = workspace.search_models("sdxl")
workspace.sync_model_directory()

# Import/Export
workspace.import_environment(tarball_path, name="imported")
workspace.import_from_git(git_url, name="from-git", branch="main")
```

### Environment

```python
# Status
status = env.status()
manager_status = env.get_manager_status()

# Node operations
info = env.add_node("comfyui-manager")
result = env.remove_node("node-name")
env.update_node("node-name")

# Workflow operations
env.sync_workflow(
    workflow_path=Path("workflow.json"),
    node_strategy=my_node_strategy,
    model_strategy=my_model_strategy,
    callbacks=my_callbacks
)
status = env.get_workflow_status()

# Git operations
env.commit_changes("message")
env.checkout("branch-name")

# Model operations
env.add_model(url, target_path=Path("checkpoints/model.safetensors"))
missing = env.detect_missing_models()
```

---

## Managers

### NodeManager

Orchestrates node installation, removal, and updates.

**Key methods:**
- `add_node(identifier, no_test=False)` → `NodeInfo`
- `remove_node(identifier)` → `NodeRemovalResult`
- `update_node(identifier, confirmation_strategy)` → `UpdateResult`

**Transactional pattern:**
1. Test dependencies in isolation (before filesystem changes)
2. Snapshot pyproject state
3. Copy/symlink to custom_nodes/
4. Update pyproject.toml
5. uv sync
6. On error: Automatic rollback (restore pyproject + cleanup filesystem)

### WorkflowManager

Manages workflow analysis, resolution, and sync.

**Key methods:**
- `sync_workflow(path, node_strategy, model_strategy, callbacks)`
- `get_workflow_status()` → `WorkflowSyncStatus`
- `get_detailed_workflow_status(name)` → `DetailedWorkflowStatus`

**Resolution flow:**
1. Parse workflow JSON
2. Extract node types + model references
3. Resolve unknown nodes (GlobalNodeResolver)
4. Install missing nodes
5. Resolve missing models (ModelResolver)
6. Download missing models
7. Update pyproject.toml + cache

### GitManager

High-level git workflow for environment version control.

**Key methods:**
- `get_status(pyproject)` → `GitStatus`
- `commit(message)` → commit SHA
- `checkout(ref)`
- `reset(ref, mode)`
- `get_history(limit)` → `list[GitCommit]`

**Features:**
- Local git config (not global) to avoid conflicts
- Smart identity detection (env vars → system user → fallback)
- Standard .gitignore for ComfyUI patterns

### EnvironmentGitOrchestrator

Coordinates git operations with environment state.

**Key methods:**
- `checkout(ref, strategy, force)`
- `reset(ref, mode, strategy, force)`
- `merge(ref, strategy)`
- `pull(remote, branch, strategy)`

**Post-git synchronization:**
- Reconcile nodes (add/remove based on pyproject changes)
- Restore workflows from .cec to ComfyUI
- Sync Python packages

### UVProjectManager

Python dependency management via uv.

**Key methods:**
- `add_dependency(package, group, dev, editable, bounds)`
- `remove_dependency(package)`
- `sync_project(pytorch_manager)`
- `lock_project()`

---

## Resolution System

### GlobalNodeResolver

Maps workflow nodes to registry packages using input signatures.

**Resolution priority:**
1. Custom mappings (from pyproject `custom_node_map`)
2. Properties field (`node.properties.cnr_id` from workflow)
3. Input signature matching (exact match)
4. Type-only matching (fallback)
5. Manual user selection (interactive)

```python
resolver = GlobalNodeResolver(node_mappings_repo)
packages = resolver.resolve_single_node_with_context(node, context)
```

### ModelResolver

Resolves model references using multiple strategies.

**Resolution strategies (in order):**
1. Context resolution (pyproject tracking)
2. Exact path match
3. Reconstructed paths (for native loaders)
4. Case-insensitive match
5. Filename-only match
6. Property-based download intent
7. Return None (unresolved)

```python
resolver = ModelResolver(model_repo, model_config)
resolved = resolver.resolve_model(ref, context)
```

### NodeLookupService

Finds nodes and analyzes requirements.

**Key methods:**
- `find_node(identifier, ref)` → `NodeInfo | None`
- `download_to_cache(node_info)` → `Path`
- `scan_requirements(cache_path)` → `list[str]`

**Strategy:** Git URLs → GitHub API; Registry IDs → Live API (fallback to cache)

---

## Data Models

### NodeInfo

Complete node information across lifecycle.

```python
@dataclass
class NodeInfo:
    name: str
    package_id: str
    version: str
    source_type: str  # "registry", "git", "dev"
    github_url: str | None
    requirements: list[str]
```

### ResolvedNodePackage

Result of node resolution.

```python
@dataclass
class ResolvedNodePackage:
    package_id: str
    package_data: GlobalNodePackage | None
    node_type: str
    match_type: str  # "exact", "type_only", "custom_mapping", "user_confirmed"
    match_confidence: float
    is_optional: bool = False
```

### ResolvedModel

Result of model resolution.

```python
@dataclass
class ResolvedModel:
    workflow: str
    reference: WorkflowNodeWidgetRef
    resolved_model: ModelWithLocation | None
    model_source: str | None  # URL for download intent
    is_optional: bool
    match_type: str
    target_path: Path | None
```

### ModelWithLocation

Model with filesystem location.

```python
@dataclass
class ModelWithLocation:
    hash: str  # xxhash short hash (primary key)
    file_size: int
    blake3_hash: str
    relative_path: str
    filename: str
    base_directory: str
```

---

## Protocols (Callbacks)

### NodeResolutionStrategy

```python
class NodeResolutionStrategy(Protocol):
    def resolve_unknown_node(
        self,
        node_type: str,
        possible: list[ResolvedNodePackage],
        context: NodeResolutionContext
    ) -> ResolvedNodePackage | None: ...

    def confirm_node_install(self, package: ResolvedNodePackage) -> bool: ...
```

### ModelResolutionStrategy

```python
class ModelResolutionStrategy(Protocol):
    def resolve_model(
        self,
        reference: WorkflowNodeWidgetRef,
        candidates: list[ResolvedModel],
        context: ModelResolutionContext
    ) -> ResolvedModel | None: ...
```

### SyncCallbacks

```python
class SyncCallbacks(Protocol):
    def on_dependency_group_start(self, group_name: str, is_optional: bool): ...
    def on_dependency_group_complete(self, group_name: str, success: bool, error: str | None): ...
```

### RollbackStrategy

```python
class RollbackStrategy(Protocol):
    def confirm_destructive_rollback(
        self,
        git_changes: list[str],
        workflow_changes: list[str]
    ) -> bool: ...
```

---

## Error Handling

### Exception Hierarchy

```python
CDEnvironmentError          # Base environment error
├── CDNodeConflictError     # Node installation conflicts
├── CDDependencyConflictError  # UV dependency resolution failure
├── CDNodeNotFoundError     # Node not found in registry/filesystem
├── CDRegistryDataError     # Registry cache issues
└── CDWorkflowError         # Workflow parsing/resolution errors
```

### Context Objects

**NodeConflictContext:**
- `conflict_type`: "duplicate", "filesystem", "version_mismatch"
- `local_remote_url`: URL of existing node
- `expected_remote_url`: URL of requested node
- `suggested_actions`: List of `NodeAction` with CLI commands

**DependencyConflictContext:**
- `conflicting_packages`: List of (pkg1, pkg2) tuples
- `conflict_descriptions`: Human-readable descriptions
- `raw_stderr`: Full UV error output
- `suggested_actions`: List of `NodeAction`

**NodeAction:**
```python
@dataclass
class NodeAction:
    action_type: str  # "remove_node", "add_node_force", "add_constraint", etc.
    description: str
    node_identifier: str | None
    node_name: str | None
```

---

## Data Flow Examples

### Node Installation

```
Environment.add_node("comfyui-manager")
  ↓
NodeManager.add_node()
  ├─ NodeLookupService.find_node() → NodeInfo
  ├─ Download to workspace cache
  ├─ Scan requirements.txt
  ├─ Test dependencies in isolation (uv pip install --dry-run)
  ├─ Snapshot pyproject state
  ├─ Copy to custom_nodes/
  ├─ Update pyproject.toml
  ├─ uv sync
  └─ On error: Restore snapshot + cleanup
```

### Workflow Sync

```
Environment.sync_workflow(path)
  ↓
WorkflowManager.sync_workflow()
  ├─ Parse workflow JSON
  ├─ WorkflowDependencyParser.analyze_dependencies()
  │   ├─ Classify nodes (builtin vs custom)
  │   └─ Extract model references
  ├─ GlobalNodeResolver.resolve_single_node_with_context() [per node]
  ├─ NodeManager.add_node() [for uninstalled nodes]
  ├─ ModelResolver.resolve_model() [per model ref]
  ├─ ModelDownloader.download() [for download intents]
  └─ Update pyproject.toml + workflow cache
```

### Git Checkout

```
Environment.checkout("feature-branch")
  ↓
EnvironmentGitOrchestrator.checkout()
  ├─ Check for uncommitted changes
  ├─ Snapshot current node list
  ├─ GitManager.checkout()
  ├─ Load new pyproject.toml
  ├─ Reconcile nodes:
  │   ├─ Remove nodes not in new pyproject
  │   └─ Install nodes added in new pyproject
  ├─ Restore workflows (copy from .cec to ComfyUI)
  └─ uv sync
```
