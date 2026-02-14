# ComfyGit CLI Package

## Overview
CLI interface for ComfyGit, providing command-line tools for workspace and environment management.

## Key Documents
- @docs/codebase-map.md - Architecture and structure
- @../../CLAUDE.md - Root workspace instructions
- @../core/CLAUDE.md - Core package guidelines

## Development

### Type Checking

**IMPORTANT**: Always run both type checkers before completing implementations to catch IDE issues:

```bash
# Run mypy (stricter, CI/CD-style checking)
uv run mypy packages/cli/comfygit_cli/

# Run pyright (Pylance/IDE-style checking - catches "possibly unbound" etc.)
uv run pyright packages/cli/comfygit_cli/

# Run both together
uv run mypy packages/cli/comfygit_cli/ && uv run pyright packages/cli/comfygit_cli/
```

**Why both?**
- **mypy**: Catches type correctness issues, used in CI/CD
- **pyright**: Catches IDE-visible issues (unbound variables, flow analysis), matches VS Code Pylance

### Type Annotation Guidelines

1. **All command handlers**: `def command(self, args: argparse.Namespace) -> None:`
2. **Callbacks with logger**: `def command(self, args: argparse.Namespace, logger=None) -> None:`
3. **Helper functions**: Add full type annotations including return types
4. **Local variables**: Add type hints when pyright complains about inference
5. **Dictionary returns**: Use `dict[str, Any]` for heterogeneous dicts

### Common Type Issues

**Possibly Unbound Variables**:
```python
# BAD - variable only assigned in conditional
if not args.yes:
    preview = status.get_sync_preview()
# ... later use of preview fails

# GOOD - assign before conditional
preview: dict[str, Any] = status.get_sync_preview()
if not args.yes:
    # use preview
```

**Return vs Exit**:
```python
# BAD - function declared -> None but returns int
def command(self, args: argparse.Namespace) -> None:
    return 1  # Error!

# GOOD - use sys.exit() or just return
def command(self, args: argparse.Namespace) -> None:
    sys.exit(1)  # or just return (no value)
```

**Argcomplete Completers**:
```python
# Add type ignore for completer attribute (not in argparse stubs)
parser.add_argument("name").completer = env_completer  # type: ignore[attr-defined]
```

## Testing

```bash
# Run CLI tests
uv run pytest packages/cli/tests/ -v

# Run specific test
uv run pytest packages/cli/tests/test_status_displays_uninstalled_nodes.py -v

# Test with coverage
uv run pytest packages/cli/tests/ --cov=comfygit_cli
```

## Code Style

### Command Handler Pattern
```python
@with_env_logging("status")  # Use actual command name, e.g., "status", "node add"
def command(self, args: argparse.Namespace, logger=None) -> None:
    """Command description."""
    env = self._get_env(args)

    # Implementation

    # Use sys.exit() for early returns with error codes
    if error_condition:
        print("✗ Error message")
        sys.exit(1)

    # Normal completion - just return
    print("✓ Success")
```

### Error Handling
```python
try:
    # Operation
except CDEnvironmentError as e:
    print(f"✗ {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    if logger:
        logger.error(f"Command failed: {e}", exc_info=True)
    print(f"✗ Error: {e}", file=sys.stderr)
    sys.exit(1)
```

## Important Notes

- **No print() in core imports**: CLI layer handles all user output
- **Use sys.exit() not return**: For early exits with error codes
- **Logging via decorators**: Use `@with_env_logging` for environment commands
- **Type safety first**: Run pyright before marking work complete
- **Simple code**: This is pre-customer MVP - avoid over-engineering

## Pre-Commit Checklist

Before committing CLI changes:

1. ✅ Run `uv run mypy packages/cli/comfygit_cli/`
2. ✅ Run `uv run pyright packages/cli/comfygit_cli/`
3. ✅ Run `uv run pytest packages/cli/tests/`
4. ✅ Test manually with `uv run cg <command>`
5. ✅ Check no red squiggles in IDE

## Common Commands

```bash
# Run CLI locally
uv run cg --help

# Test specific command
uv run cg -e test-env status

# Install in dev mode
uv pip install -e packages/cli/

# Format code
uv run ruff format packages/cli/

# Lint and fix
uv run ruff check --fix packages/cli/
```

## Dependencies

- **comfygit-core**: Core library (DO NOT couple with CLI specifics)
- **argparse**: Command-line parsing
- **argcomplete**: Shell tab completion
- **aiohttp**: Async HTTP for registry operations

## Architecture

```
comfygit_cli/
├── cli.py                    # Main entry point, argument parsing
├── env_commands.py           # Environment-scoped commands (node, py, sync, run, git, env-config, etc.)
├── global_commands.py        # Workspace-scoped commands (init, create, import, export, etc.)
├── update_commands.py        # Update/upgrade commands (cg update)
├── completion_commands.py    # Shell completion setup commands
├── completers.py             # Shell completion logic (tab completion)
├── cli_utils.py              # CLI utility helpers
├── resolution_strategies.py  # Node/model resolution strategies
├── interactive/              # Interactive prompts and wizards
├── strategies/
│   └── interactive.py        # Interactive resolution strategies
├── formatters/
│   └── error_formatter.py    # Error message formatting
├── logging/
│   ├── logging_config.py     # Base logging setup
│   └── environment_logger.py # Environment-specific logging
└── utils/
    ├── progress.py           # Download progress display
    ├── pagination.py         # Terminal pagination
    ├── orchestrator.py       # Orchestrator process management
    ├── civitai_errors.py     # CivitAI error handling
    ├── update_checker.py     # Background PyPI update checker (24h cache)
    └── update_notice.py      # One-line update notice on stderr
```
