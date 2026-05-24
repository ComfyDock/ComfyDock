# ComfyGit Core - Architecture Overview

ComfyGit Core is a **library-first Python package** providing environment management APIs for ComfyUI without UI coupling. All external interaction happens through callback protocols and strategy patterns.

## Layered Architecture

```
┌─────────────────────────────────────────┐
│  Public API Layer                       │
│  Workspace, Environment, facade exports │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│  Managers (managers/)                   │
│  Node, Workflow, Git, Model, PyProject  │
│  Orchestrate operations using services  │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│  Services & Analysis Layer              │
│  Analyzers, Resolvers, Services         │
│  Stateless business logic & parsing     │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│  Data Layer                             │
│  Repositories, Caching, Models          │
│  Persistence & type definitions         │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│  Integration Layer                      │
│  Clients (API), Factories, Utils        │
│  External tools & low-level operations  │
└─────────────────────────────────────────┘
```

## Core Modules

| Module | Purpose | Key Concepts |
|--------|---------|--------------|
| **core/** | Public API | Workspace (multi-env), Environment (single env) |
| **models/** | Public typed contracts | Exported data classes, protocols, exceptions with context |
| **readiness.py**, **workflow.py**, **runtime.py**, **assets.py**, **git.py** | Public facades | Reusable domain helpers promoted for adapters |
| **managers/** | Orchestration | Environment orchestrators (Git, Model), Resource managers (Node, Workflow, Model symlinks), Config managers (PyProject, UV, PyTorch backend) |
| **manifest/** | Internal manifest abstraction | Pyproject-backed store, section handlers, edit helpers, overlay materialization, migration cleanup |
| **analyzers/** | Analysis | Parse workflows/git/status; classify nodes |
| **resolvers/** | Resolution | Map workflow nodes to packages; resolve model sources |
| **services/** | Business logic | Lookup, registry, downloads, import analysis |
| **repositories/** | Persistence | SQLite caching, workflow cache, config storage |
| **clients/** | External APIs | CivitAI, GitHub, ComfyUI registry |
| **factories/** | Internal DI | Create Workspace/Environment with dependencies behind public facades |
| **utils/** | Low-level | Git, filesystem, parsing, version, download |
| **caching/** | Cache layer | API cache, custom node cache, workflow cache |
| **configs/** | Reference data | Builtin nodes, model categories |

## Architecture Patterns

**Library Design**
- No print/input - all UI through callback protocols (NodeResolutionStrategy, ConfirmationStrategy)
- Stateful service managers - encapsulate domain operations with filesystem state
- Protocol-based plugins - strategies injected via constructor
- Concurrency control - environment-level operation locks prevent concurrent mutations

**Data Flow**
- Environment → Managers → Services/Analyzers → Repositories → External APIs
- Caching at repository layer reduces API calls (TTL expiration)
- Error context carried through exceptions for precise handling

**Extensibility**
- `NodeResolutionStrategy` / `ModelResolutionStrategy` for custom resolution behavior
- `ConfirmationStrategy` / `RollbackStrategy` for interactive decisions
- Callback protocols (`SyncCallbacks`, `ExportCallbacks`) for operation progress tracking

## Key Entry Points

**Workspace Operations:**
- `Workspace.open()` - Discover and load an existing workspace
- `Workspace.create()` - Create new workspace with validation
- `Workspace.open_or_create()` - Setup-friendly load-or-create entry point
- `Workspace.list_environments()` / `get_environment()` - List/get environments
- `Workspace.get_schema_version()` / `is_legacy_schema()` - Check workspace version
- `Workspace.upgrade_schema_if_needed()` - Migrate to current schema

**Environment Operations:**
- `Environment.add_node()` / `remove_node()` - Install/uninstall custom nodes
- `Environment.add_model()` - Download and install models
- `Environment.sync()` - Synchronize packages, nodes, workflows, and models
- `Environment.export()` - Bundle for portability
- `Environment.preview_pull()` / `preview_merge()` - Preview changes before merge
- `Environment.validate_merge()` / `execute_atomic_merge()` - Semantic merge with rollback

**Resolution:**
- `GlobalNodeResolver.resolve_single_node_with_context()` - Enhanced node resolution with context
- `GlobalNodeResolver.search_packages()` - Fuzzy search with heuristic boosting
- `ModelResolver.resolve_model()` - Resolve model sources using multiple strategies

Low-level resolvers, managers, repositories, factories, and utilities are
implementation details unless re-exported through a public facade module.
Adapters should import from `comfygit_core`, `comfygit_core.models`, or the
explicit facade modules instead of deep implementation paths.

The `manifest/` package is the internal boundary around the current
`pyproject.toml` implementation. `PyprojectManager` remains the compatibility
facade for existing core internals, but document storage, section ownership,
overlay materialization, and disposable uv project sync should live behind
manifest helpers. New callers should prefer `Environment.get_manifest_snapshot()`
or the public Environment/Workspace facade methods instead of reading raw TOML.

## Dependencies

**External:** aiohttp, requests, uv, pyyaml, tomlkit, blake3, packaging, psutil, requirements-parser
**Internal:** Protocol-based callbacks, type hints for IDE support (py.typed)

## Testing Strategy

Integration tests cover real-world flows (workflow caching, model resolution, git operations, rollback). MVP-focused with 2-3 tests per module covering happy paths.
