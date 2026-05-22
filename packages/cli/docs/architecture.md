# ComfyGit CLI - Architecture Overview

ComfyGit CLI is a **library-first thin shell** wrapping comfygit-core. It provides command-line access to workspace and environment operations through argparse-based command handlers, with all domain logic delegated to the core library.

## Core Philosophy

- **Zero domain logic** - CLI is presentation layer only
- **Protocol-driven** - Uses core's callback protocols (ConfirmationStrategy, ModelResolutionStrategy, etc.) for interactive behavior
- **Public core facade** - Discovers and initializes Workspace through the documented core API
- **Decorator-based logging** - Environment context attached via @with_env_logging / @with_workspace_logging

## Architecture Pattern

```
User Command
    ↓
cli.py (argparse routing)
    ↓
EnvironmentCommands / GlobalCommands (handlers)
    ↓
Strategy implementations (interactive.py, error_formatter.py)
    ↓
comfygit_core.* (library API)
```

## Module Organization

| Module | Purpose | Key Classes |
|--------|---------|------------|
| **cli.py** | Argument parsing, command routing | Main entry point, parser setup, argcomplete integration |
| **env_commands.py** | Environment-scoped commands | EnvironmentCommands handler (node add/remove, workflow sync, etc.) |
| **global_commands.py** | Workspace-scoped commands | GlobalCommands handler (init, import/export, searches) |
| **cli_utils.py** | Workspace discovery & validation | get_workspace_or_exit(), get_workspace_optional() |
| **completers.py** | Shell tab completion | Custom argcomplete completers (env names, node names, workflows) |
| **strategies/** | Interactive behavior plugins | InteractiveNodeStrategy, InteractiveModelStrategy (implements core protocols) |
| **formatters/** | User-facing error messages | NodeErrorFormatter (core errors → CLI recommendations) |
| **logging/** | Environment-specific logging | setup_logging(), with_env_logging decorator, compressed handler |
| **utils/** | UI helpers | Progress callbacks, pagination, CivitAI auth help |

## Key Abstractions

### Command Handlers
- **EnvironmentCommands**: Instance per CLI invocation; cached_property for workspace access
- **GlobalCommands**: Same pattern for workspace-level operations
- Pattern: `def command(self, args: argparse.Namespace, logger=None) -> None:`

### Strategy Implementations
- **InteractiveNodeStrategy / InteractiveModelStrategy**: Implement core's protocol interfaces for interactive resolution
- Used when workflow dependencies cannot be auto-resolved; prompts user for choices
- Reusable across commands that need interactive resolution

### Error Formatting
- **NodeErrorFormatter**: Converts core CDNodeConflictError, CDDependencyConflictError to CLI-friendly messages
- Includes remediation commands and suggestions

### Logging Decorator Pattern
- `@with_env_logging("command-name")`: Attaches environment-specific logging context
- `@with_workspace_logging()`: Workspace-level logging
- Automatic handler management; context preserved across function calls

## Command Flow Example

```
$ cg -e production node add comfygit-manager

1. cli.py parses args, routes to EnvironmentCommands.node_add()
2. Handler gets workspace via cached_property
3. @with_env_logging decorator attaches "production" context
4. Handler calls env.add_node() (core API)
5. If conflict detected, InteractiveNodeStrategy prompts user
6. On success, prints status; on error, NodeErrorFormatter formats message
7. Logging captured to .config/comfygit/logs/production-<timestamp>.log
```

## Entry Points

**CLI Scripts** (defined in pyproject.toml):
- `comfygit` / `cg` - Both route to cli.py:main()

**Handler Classes**:
- `EnvironmentCommands` - ~30 methods for node/model/workflow/py commands
- `GlobalCommands` - init, import, export, search, list, model downloads
- `CompletionCommands` - Shell completion setup (bash, zsh, fish)

**Core Integration**:
- `Workspace.open()` / `Workspace.open_or_create()` - Discovers or initializes workspace state through the public core API
- `Environment.add_node()` / `remove_node()` / `sync_workflow()` / etc. - Delegated operations

## Dependencies

**Internal**: comfygit-core (exact version pinned via lockstep versioning)
**External**: argparse (stdlib), argcomplete (3.5+), aiohttp (async registry lookups)

## Design Patterns

### Protocol Implementation
Core defines resolution strategies as TYPE_CHECKING protocols; CLI provides implementations:
```python
class InteractiveNodeStrategy(NodeResolutionStrategy):
    def resolve(...) -> ResolvedNodePackage:
        # User prompts and selection logic
```

### Workspace Caching
Handlers use `@cached_property` to initialize workspace once per CLI invocation:
```python
class EnvironmentCommands:
    @cached_property
    def workspace(self) -> Workspace:
        return get_workspace_or_exit()
```

### Error Recovery
Commands catch core exceptions and format into user guidance:
```python
except CDNodeConflictError as e:
    print(NodeErrorFormatter.format_conflict(e))
    sys.exit(1)
```

## Testing Strategy

MVP-focused testing with main happy paths covered:
- Command handler tests mock workspace/environment
- Formatter tests verify error message output
- Integration tests run through full CLI flow
- No over-testing of core functionality (tested in core package)

## Where to Look

- **Adding a new command?** → env_commands.py or global_commands.py, follow existing handler pattern
- **Need interactive resolution?** → Create strategy in strategies/, implement core protocol
- **Error formatting issue?** → formatters/error_formatter.py
- **Logging not appearing?** → logging/logging_config.py or environment_logger.py
- **Shell completion missing?** → completers.py
- **Workspace discovery failing?** → cli_utils.py or COMFYGIT_HOME env var

## Coupling Rules

- **Never import from formatters/logging into commands** - Use dependency injection via logger parameter
- **Never add domain logic to CLI** - If it's not user interaction, it belongs in core
- **Never print in strategies** - Use return values; calling code handles output
- **Never call git or domain subprocesses directly** - Use core managers for
  environment behavior; narrow CLI adapters such as container engines may own
  their external process boundary
- **Always use Protocol types from core** - No custom interfaces in CLI

## Package-Local Deltas

- [Container Runtime Command Delta](specs/container-runtime-delta.md) - planned
  direction for `cg container ...`, Docker/Podman engine abstraction, UID/GID
  defaults, GPU option mapping, and container lifecycle commands.
