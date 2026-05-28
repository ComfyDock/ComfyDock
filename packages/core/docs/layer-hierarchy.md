# Core Package Layer Hierarchy

This document defines the import hierarchy and functional responsibilities for the `comfygit-core` package. Layers are ordered from lowest (foundation) to highest (orchestration).

## Import Rules

- **Lower layers CANNOT import from higher layers**
- **Same-level imports are allowed** (e.g., utils/ can import from other utils/)
- **All layers can import from models/** (foundation layer)
- **Cross-cutting concerns** (logging, configs) can be imported by any layer

---

## Layer 0: Foundation (No internal dependencies)

### `models/`
**Purpose**: Core data structures, protocols, and exceptions
**Dependencies**: None (pure data models)
**Key Files**:
- `protocols.py` - Interface definitions (Strategy protocols)
- `exceptions.py` - Custom exception classes
- `shared.py` - Shared data models (NodeInfo, ModelWithLocation, etc.)
- `workflow.py` - Workflow-specific models
- `environment.py` - Environment status models
- `workspace_config.py` - Workspace configuration models

### `configs/`
**Purpose**: Static configuration and constants
**Dependencies**: None
**Key Files**:
- `comfyui_builtin_nodes.py` - ComfyUI node type mappings
- `comfyui_models.py` - Model type to directory mappings
- `model_config.py` - Model scanning configuration

### `logging/`
**Purpose**: Logging setup
**Dependencies**: None
**Key Files**:
- `logging_config.py` - Logger initialization

### `constants.py`
**Purpose**: Global constants
**Dependencies**: None

---

## Layer 1: Infrastructure & Utilities

### `utils/`
**Purpose**: Generic helper functions and operations
**Dependencies**: models/, configs/
**Key Files**:
- `filesystem.py` - File system operations
- `git.py` - Git command wrappers
- `common.py` - Common utilities
- `download.py` - Download helpers
- `requirements.py` - Requirements file parsing
- `dependency_parser.py` - Dependency string parsing
- `version.py` - Version comparison
- `conflict_parser.py` - Node conflict detection
- `system_detector.py` - System detection
- `progress.py` - Progress reporting
- `retry.py` - Retry logic
- `comfyui_ops.py` - ComfyUI-specific operations
- `input_signature.py` - Input validation

### `infrastructure/`
**Purpose**: Low-level infrastructure services
**Dependencies**: models/, logging/
**Key Files**:
- `sqlite_manager.py` - SQLite database operations

### `integrations/`
**Purpose**: External tool integrations
**Dependencies**: models/, utils/
**Key Files**:
- `uv_command.py` - UV package manager integration

---

## Layer 2: External Communication

### `clients/`
**Purpose**: HTTP clients for external APIs
**Dependencies**: models/, utils/, logging/
**Key Files**:
- `registry_client.py` - ComfyUI Registry API client
- `github_client.py` - GitHub API client
- `civitai_client.py` - CivitAI API client

### `caching/`
**Purpose**: Caching for API responses and downloaded nodes
**Dependencies**: models/, utils/, logging/
**Key Files**:
- `api_cache.py` - Generic API response caching
- `custom_node_cache.py` - Custom node download cache

---

## Layer 3: Data Access & Storage

### `repositories/`
**Purpose**: Data persistence and retrieval
**Dependencies**: models/, infrastructure/, utils/, logging/
**Key Files**:
- `model_repository.py` - Model index database operations
- `workspace_config_repository.py` - Workspace configuration persistence
- `workflow_repository.py` - Workflow file operations

---

## Layer 4: Analysis & Resolution

### `analyzers/`
**Purpose**: Parse and analyze files and state
**Dependencies**: models/, utils/, configs/, logging/
**Key Files**:
- `workflow_dependency_parser.py` - Parse workflow JSON for dependencies
- `custom_node_scanner.py` - Scan node directories for requirements
- `model_scanner.py` - Scan directories for model files
- `node_classifier.py` - Classify node types
- `git_change_parser.py` - Parse git changes
- `status_scanner.py` - Environment state comparison

### `resolvers/`
**Purpose**: Resolve references to concrete resources
**Dependencies**: models/, repositories/, clients/, caching/, utils/, logging/
**Key Files**:
- `model_resolver.py` - Resolve workflow model references to index
- `global_node_resolver.py` - Resolve node types to packages (GitHub URL → Registry ID)

### `validation/`
**Purpose**: Validate operations before execution
**Dependencies**: models/, integrations/, utils/, logging/
**Key Files**:
- `resolution_tester.py` - Test dependency resolution in isolated env

---

## Layer 5: Business Logic Services

### `services/`
**Purpose**: Coordinated business operations
**Dependencies**: models/, analyzers/, resolvers/, clients/, caching/, repositories/, utils/, logging/
**Key Files**:
- `node_lookup_service.py` - Find nodes from registry/git (stateless service)
- `registry_data_manager.py` - Manage registry data cache

### `strategies/`
**Purpose**: Strategy pattern implementations for user interaction
**Dependencies**: models/protocols.py
**Key Files**:
- `confirmation.py` - Confirmation strategies
- `auto.py` - Auto-confirmation strategy

---

## Layer 6: Orchestration & Management

### `managers/`
**Purpose**: Coordinate complex multi-step operations
**Dependencies**: ALL lower layers (models/, repositories/, services/, analyzers/, resolvers/, integrations/, utils/, logging/)
**Key Files**:
- `pyproject_manager.py` - pyproject.toml read/write operations
- `uv_project_manager.py` - UV project lifecycle (uses integrations/uv_command.py)
- `node_manager.py` - Node add/remove/update/reconcile operations
- `workflow_manager.py` - Workflow analysis/resolution/commit operations
- `model_path_manager.py` - Model path configuration
- `model_manifest_manager.py` - Model manifest operations
- `git_manager.py` - Git commit/rollback operations

---

## Layer 7: Factories

### `factories/`
**Purpose**: Object construction and initialization
**Dependencies**: ALL lower layers
**Key Files**:
- `workspace_factory.py` - Create/find workspaces
- `environment_factory.py` - Create environments
- `uv_factory.py` - Create UV managers

---

## Layer 8: Public API (Top Level)

### `core/`
**Purpose**: Primary entry points and orchestration
**Dependencies**: ALL lower layers (especially managers/, factories/)
**Key Files**:
- `workspace.py` - Workspace class (owns multiple environments)
- `environment.py` - Environment class (owns managers, coordinates operations)

---

## Import Flow Visualization

```
┌─────────────────────────────────────────────────────────┐
│ Layer 8: core/                                          │
│   - workspace.py, environment.py                        │
│   (Public API, coordinates everything)                  │
└────────────────────────┬────────────────────────────────┘
                         │ imports from
┌────────────────────────▼────────────────────────────────┐
│ Layer 7: factories/                                     │
│   - workspace_factory.py, environment_factory.py        │
│   (Object construction)                                 │
└────────────────────────┬────────────────────────────────┘
                         │ imports from
┌────────────────────────▼────────────────────────────────┐
│ Layer 6: managers/                                      │
│   - node_manager.py, workflow_manager.py, etc.          │
│   (Complex multi-step operations)                       │
└────────────────────────┬────────────────────────────────┘
                         │ imports from
┌────────────────────────▼────────────────────────────────┐
│ Layer 5: services/, strategies/                         │
│   - node_lookup_service.py, registry_data_manager.py    │
│   (Coordinated business operations)                     │
└────────────────────────┬────────────────────────────────┘
                         │ imports from
┌────────────────────────▼────────────────────────────────┐
│ Layer 4: analyzers/, resolvers/, validation/            │
│   - workflow_dependency_parser.py, model_resolver.py    │
│   (Analysis and resolution logic)                       │
└────────────────────────┬────────────────────────────────┘
                         │ imports from
┌────────────────────────▼────────────────────────────────┐
│ Layer 3: repositories/                                  │
│   - model_repository.py, workspace_config_repository.py │
│   (Data persistence)                                    │
└────────────────────────┬────────────────────────────────┘
                         │ imports from
┌────────────────────────▼────────────────────────────────┐
│ Layer 2: clients/, caching/                             │
│   - registry_client.py, github_client.py, caches        │
│   (External communication)                              │
└────────────────────────┬────────────────────────────────┘
                         │ imports from
┌────────────────────────▼────────────────────────────────┐
│ Layer 1: utils/, infrastructure/, integrations/         │
│   - filesystem.py, git.py, sqlite_manager.py, uv_cmd    │
│   (Generic utilities and infrastructure)                │
└────────────────────────┬────────────────────────────────┘
                         │ imports from
┌────────────────────────▼────────────────────────────────┐
│ Layer 0: models/, configs/, logging/, constants.py      │
│   (Foundation - no internal dependencies)               │
└─────────────────────────────────────────────────────────┘
```

---

## Functional Abstraction Levels

### Low-Level (Foundation)
- **models/**: Data structures only
- **configs/**: Static configuration
- **utils/**: Generic helpers (filesystem, git, parsing)
- **infrastructure/**: Database operations
- **integrations/**: External tool wrappers

### Mid-Level (Communication & Storage)
- **clients/**: External API communication
- **caching/**: Response and file caching
- **repositories/**: Data persistence layer

### High-Level (Domain Logic)
- **analyzers/**: Parse and understand files/state
- **resolvers/**: Map references to concrete resources
- **validation/**: Pre-flight checks
- **services/**: Stateless business operations
- **strategies/**: User interaction patterns

### Orchestration (Top Level)
- **managers/**: Multi-step coordinated operations
- **factories/**: Object construction
- **core/**: Public API (Workspace, Environment)

---

## Key Design Principles

1. **Dependency Inversion**: High-level modules depend on abstractions (protocols in models/)
2. **Single Responsibility**: Each layer has a clear, focused purpose
3. **No Circular Dependencies**: Strict layer ordering prevents cycles
4. **Testability**: Lower layers are easily testable in isolation
5. **Stateless Services**: Services in Layer 5 are stateless, state lives in managers/core

---

## Example Import Chains

### Adding a Node (node_manager.py)
```
node_manager.py (Layer 6)
  → node_lookup_service.py (Layer 5)
    → registry_client.py (Layer 2)
      → api_cache.py (Layer 2)
        → utils/filesystem.py (Layer 1)
          → models/shared.py (Layer 0)
```

### Resolving a Workflow (workflow_manager.py)
```
workflow_manager.py (Layer 6)
  → workflow_dependency_parser.py (Layer 4)
    → model_resolver.py (Layer 4)
      → model_repository.py (Layer 3)
        → sqlite_manager.py (Layer 1)
          → models/workflow.py (Layer 0)
```

### Creating an Environment (environment_factory.py)
```
environment_factory.py (Layer 7)
  → environment.py (Layer 8 - creates instance)
    → node_manager.py (Layer 6)
    → workflow_manager.py (Layer 6)
    → git_manager.py (Layer 6)
      → utils/git.py (Layer 1)
        → models/exceptions.py (Layer 0)
```
