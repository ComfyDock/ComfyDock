# ComfyGit Core

Core library for programmatic ComfyUI environment and package management. Build custom tools, GUIs, web interfaces, or CI/CD integrations on top of ComfyGit's architecture.

> **MVP Status**: This library is under active development. APIs may change between versions. Pin your dependencies to specific versions in production.

## What is ComfyGit Core?

ComfyGit Core is the **reusable library** that powers the `cg` CLI and can power your own tools. It provides:

- **Workspace & Environment Management** - Create and manage isolated ComfyUI installations
- **Custom Node Management** - Install, update, remove nodes with automatic conflict resolution
- **Workflow Tracking** - Track workflows and resolve missing dependencies
- **Model Management** - Content-addressable model index with automatic resolution
- **Version Control** - Git-based commit/rollback for environment snapshots
- **Export/Import** - Package and share complete working environments
- **Strategy Pattern** - Plug in your own UI logic via callbacks

This is a **library, not a CLI**. No `print()` or `input()` statements - all user interaction happens through callbacks you provide.

## Installation

Published to PyPI as `comfygit-core`:

```bash
# With pip
pip install comfygit-core

# With uv
uv add comfygit-core
```

## Quick Start

### Basic Workspace and Environment Operations

```python
from pathlib import Path
from comfygit_core.factories.workspace_factory import WorkspaceFactory

# Create a new workspace
workspace = WorkspaceFactory.create(Path.home() / "my-comfyui-workspace")

# Or find an existing workspace
workspace = WorkspaceFactory.find(Path.home() / "my-comfyui-workspace")

# Create an environment (downloads ComfyUI, sets up Python venv)
env = workspace.create_environment(
    name="production",
    python_version="3.12",
    comfyui_version="master",  # or specific commit hash
    torch_backend="auto"  # auto-detect GPU, or "cpu", "cu121", etc.
)

# List all environments
environments = workspace.list_environments()
for env in environments:
    print(f"Environment: {env.name} at {env.path}")

# Get a specific environment
env = workspace.get_environment("production")

# Set active environment (for CLI convenience, optional for library usage)
workspace.set_active_environment("production")
active = workspace.get_active_environment()

# Delete an environment
workspace.delete_environment("production")
```

**API Reference**: See `src/comfygit_core/core/workspace.py` for full `Workspace` API and `src/comfygit_core/factories/workspace_factory.py` for factory methods.

### Node Management

```python
# Add a node from ComfyUI registry
result = env.add_node("comfyui-manager")

# Add a node from GitHub URL with version
result = env.add_node(
    "https://github.com/ltdrdata/ComfyUI-Impact-Pack@v5.0"
)

# Track a development node (your own node under development)
result = env.add_node(
    "/path/to/my-custom-node",
    is_development=True  # marks as development node
)

# Add with strict mode (fail on conflicts instead of auto-resolving)
result = env.add_node("some-node", strict=True)

# List installed nodes
nodes = env.list_nodes()
for node in nodes:
    print(f"{node.name}: {node.source} ({node.version})")

# Remove a node
result = env.remove_node("comfyui-manager")

# Update a node to latest version
update_result = env.update_node("comfyui-impact-pack")
```

**Node Sources**: Nodes can come from:
- `registry` - ComfyUI official registry
- `git` - GitHub/GitLab repositories
- `development` - Local nodes under development

**Automatic Conflict Resolution**: By default, ComfyGit probes dependencies and auto-resolves conflicts. Use `strict=True` to fail immediately on conflicts instead.

**API Reference**: See `src/comfygit_core/core/environment.py` for node methods and `src/comfygit_core/managers/node_manager.py` for implementation details.

### Workflow Tracking and Sync

```python
from pathlib import Path

# Sync an environment (install missing nodes, sync Python deps)
result = env.sync(
    node_strategy=my_node_strategy,  # custom strategy for ambiguous nodes
    model_strategy=my_model_strategy,  # custom strategy for missing models
)

# List tracked workflows
workflows = env.list_workflows()

# Resolve workflow dependencies (finds missing nodes and models)
result = env.resolve_workflow(
    Path("my-workflow.json"),
    node_strategy=my_node_strategy,
    model_strategy=my_model_strategy,
)
```

**API Reference**: See `src/comfygit_core/managers/workflow_manager.py` for workflow operations.

### Model Management

```python
# Add a model download source to an existing model
result = env.add_model_source(
    identifier="model-name",
    url="https://civitai.com/api/download/models/12345"
)

# Models are symlinked into environments from workspace model directory
# No duplication - all environments share the workspace model index
```

**Model Index**: Uses Blake3 quick hash (first/middle/last 15MB) for fast identification.

### Version Control (Commit/Push/Pull)

```python
# Commit current state
env.commit(message="Added Impact Pack and configured workflows")

# View commit history
commits = env.get_commit_history(limit=10)
for commit in commits:
    print(f"{commit['hash'][:8]}: {commit['message']}")

# Push to remote
env.push_commits(remote="origin", branch="main")

# Pull and repair (handles merge conflicts)
env.pull_and_repair(remote="origin", branch="main")
```

**What Gets Committed**:
- `pyproject.toml` - Node metadata, model references, Python dependencies
- `uv.lock` - Locked Python dependency versions
- `.cec/workflows/` - Tracked workflow files

**What Doesn't Get Committed**:
- Node source code (tracked in metadata, downloaded on demand)
- Model files (too large, referenced by hash)
- `.venv/` - Python virtual environment (recreated from lock)

**API Reference**: See `src/comfygit_core/core/environment.py` for version control methods.

### Export and Import

```python
from comfygit_core.models.protocols import ExportCallbacks, ImportCallbacks

# Export environment
class MyExportCallbacks(ExportCallbacks):
    def on_progress(self, step: str, current: int, total: int):
        print(f"{step}: {current}/{total}")

env.export_environment(
    output_path=Path("production-env.tar.gz"),
    callbacks=MyExportCallbacks()
)

# Import environment from tarball
class MyImportCallbacks(ImportCallbacks):
    def on_node_download_start(self, node_name: str):
        print(f"Downloading node: {node_name}")

workspace.import_environment(
    source=Path("production-env.tar.gz"),
    name="imported-production",
    callbacks=MyImportCallbacks(),
    torch_backend="auto"
)

# Import from git repository
workspace.import_from_git(
    url="https://github.com/user/my-comfyui-env.git",
    name="team-env",
    branch="main",
    callbacks=MyImportCallbacks()
)
```

**API Reference**: See `src/comfygit_core/models/protocols.py` for callback protocols.

## Strategy Pattern (Custom UI Integration)

ComfyGit Core uses the **strategy pattern** to allow custom frontends to provide their own UI logic.

### Node Resolution Strategy

When adding nodes with ambiguous names:

```python
from comfygit_core.models.protocols import NodeResolutionStrategy
from comfygit_core.models.shared import NodeInfo

class CLINodeStrategy(NodeResolutionStrategy):
    """Interactive CLI node resolution."""

    def resolve_ambiguous(
        self,
        node_identifier: str,
        candidates: list[NodeInfo]
    ) -> NodeInfo:
        """User picks from multiple matches."""
        print(f"Multiple nodes match '{node_identifier}':")
        for i, node in enumerate(candidates, 1):
            print(f"  {i}. {node.name} ({node.source})")

        choice = int(input("Select: ")) - 1
        return candidates[choice]

# Use your strategy
env.add_node("comfyui", strategy=CLINodeStrategy())
```

### Model Resolution Strategy

When workflows reference missing models:

```python
from comfygit_core.models.protocols import ModelResolutionStrategy

class CLIModelStrategy(ModelResolutionStrategy):
    """Interactive CLI model resolution."""

    def resolve_missing_model(
        self,
        model_reference: str,
        candidates: list
    ) -> object | None:
        """User picks from search results or skips."""
        if not candidates:
            print(f"No models found for '{model_reference}'")
            return None

        print(f"Found models for '{model_reference}':")
        for i, model in enumerate(candidates, 1):
            print(f"  {i}. {model.filename}")
        print(f"  {len(candidates)+1}. Skip")

        choice = int(input("Select: "))
        if choice == len(candidates) + 1:
            return None

        return candidates[choice - 1]
```

### Available Protocols

- `NodeResolutionStrategy` - Handle ambiguous node names
- `ModelResolutionStrategy` - Handle missing model resolution
- `ConfirmationStrategy` - Handle destructive operations
- `RollbackStrategy` - Handle rollback confirmations
- `SyncCallbacks` - Progress updates during sync
- `ExportCallbacks` - Progress updates during export
- `ImportCallbacks` - Progress updates during import

**API Reference**: See `src/comfygit_core/models/protocols.py` for all strategy protocols.

## Architecture Overview

ComfyGit Core uses a **layered architecture** separating concerns:

```
┌─────────────────────────────────────────────────────────────┐
│  API Layer (Workspace, Environment)                         │
│  - High-level operations                                    │
│  - Public API surface                                       │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│  Management Layer (Managers)                                │
│  - NodeManager: Node installation/removal                   │
│  - WorkflowManager: Workflow tracking/resolution            │
│  - GitManager: Git operations                               │
│  - PyprojectManager: pyproject.toml manipulation            │
│  - UVProjectManager: UV command execution                   │
│  - PyTorchBackendManager: GPU backend management            │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│  Service Layer (Services)                                   │
│  - NodeLookupService: Find nodes across sources             │
│  - ModelDownloader: Download models from URLs               │
│  - RegistryDataManager: ComfyUI registry cache              │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│  Repository Layer (Data Access)                             │
│  - ModelRepository: SQLite model index                      │
│  - WorkflowRepository: Workflow caching                     │
│  - NodeMappingsRepository: Node-to-package mappings         │
└─────────────────────────────────────────────────────────────┘
```

### Key Patterns

- **Concurrency Control** - Environment-level operation locks prevent concurrent mutations
- **Protocol-based Plugins** - Strategies injected via constructor for UI flexibility
- **Stateful Managers** - Encapsulate domain operations with filesystem state

### Component Organization

| Directory | Purpose |
|-----------|---------|
| `core/` | Workspace & Environment public API |
| `managers/` | Orchestration layer, state management |
| `services/` | Stateless business logic |
| `repositories/` | Data persistence (SQLite, JSON, TOML) |
| `analyzers/` | Parsing & extraction |
| `resolvers/` | Action determination |
| `models/` | Data structures, protocols |
| `factories/` | Object construction, dependency injection |
| `strategies/` | Built-in strategy implementations |
| `clients/` | External API clients (CivitAI, GitHub) |
| `utils/` | Utilities (git, filesystem, retry) |
| `merging/` | Semantic merge operations |

## Error Handling

ComfyGit Core uses a custom exception hierarchy:

```python
from comfygit_core.models.exceptions import (
    ComfyDockError,         # Base exception
    CDWorkspaceError,       # Workspace-related errors
    CDEnvironmentError,     # Environment-related errors
    CDNodeConflictError,    # Node installation conflicts
    CDNodeNotFoundError,    # Node not found
    CDDependencyConflictError,  # Python dependency conflicts
)

try:
    env.add_node("some-node")
except CDNodeConflictError as e:
    print(f"Conflict: {e}")
    # Access conflict details via e.conflicts
except CDNodeNotFoundError as e:
    print(f"Not found: {e}")
except ComfyDockError as e:
    print(f"ComfyGit error: {e}")
```

**API Reference**: See `src/comfygit_core/models/exceptions.py` for all exception types.

## Development

### Running Tests

```bash
# All tests
uv run pytest packages/core/tests/

# With coverage
uv run pytest packages/core/tests/ --cov=comfygit_core

# Specific test file
uv run pytest packages/core/tests/test_environment.py -v
```

### Project Structure

```
packages/core/
├── src/comfygit_core/
│   ├── core/              # Workspace & Environment
│   ├── managers/          # Orchestration layer
│   ├── services/          # Business logic
│   ├── repositories/      # Data access
│   ├── analyzers/         # Parsing & extraction
│   ├── resolvers/         # Action determination
│   ├── models/            # Data structures
│   ├── factories/         # Object construction
│   ├── strategies/        # Built-in strategies
│   ├── clients/           # External API clients
│   ├── utils/             # Utilities
│   ├── merging/           # Semantic merge
│   └── configs/           # Static configuration
├── tests/                 # Test suite
├── docs/                  # Architecture docs
└── pyproject.toml         # Package metadata
```

## Comparison to CLI

The CLI (`comfygit` package) is built on top of this core library:

| Core Library | CLI Package |
|--------------|-------------|
| Programmatic Python API | Command-line interface |
| Strategy callbacks for UI | Interactive terminal UI |
| No user interaction | Prompts, progress bars, formatting |
| `workspace.create_environment()` | `cg env create <name>` |
| `env.add_node()` | `cg node add <id>` |
| Returns data structures | Prints formatted output |

**Use the core library when:**
- Building a custom GUI (Qt, Electron, web UI)
- CI/CD automation
- Scripting bulk operations
- Integrating into larger tools

**Use the CLI when:**
- Interactive terminal usage
- Quick manual operations
- You want the pre-built UX

## Documentation

- **User Guide**: [docs.comfygit.org](https://docs.comfygit.org)
- **Architecture Details**: See `docs/architecture.md` in this package
- **Source Code**: All source in `src/comfygit_core/` with inline documentation

## License

ComfyGit Core is licensed under **AGPL-3.0**.

See [LICENSE.txt](../../LICENSE.txt) for the full license text.

## Version & Stability

**Current Version**: 0.3.14

**Stability**: MVP - APIs may change between versions. Pin your dependencies:

```toml
# pyproject.toml
dependencies = [
    "comfygit-core>=0.3.14,<0.4.0"  # Pin to minor version
]
```
