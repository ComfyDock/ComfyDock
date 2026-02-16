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

- Command handlers: `def command(self, args: argparse.Namespace, logger=None) -> None:`
- Use `dict[str, Any]` for heterogeneous dicts, add type hints when pyright complains
- Use `sys.exit(1)` not `return 1` for error exits (functions return `-> None`)
- Assign variables before conditionals to avoid "possibly unbound" errors
- Argcomplete: `parser.add_argument("name").completer = env_completer  # type: ignore[attr-defined]`

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

- Use `@with_env_logging("command_name")` decorator on environment commands
- Error exits: `print("✗ ...", file=sys.stderr); sys.exit(1)`
- No `print()`/`input()` in core imports — CLI layer handles all user output
- Pre-commit: `uv run mypy packages/cli/comfygit_cli/ && uv run pyright packages/cli/comfygit_cli/ && uv run pytest packages/cli/tests/`

## Common Commands

```bash
uv run cg --help                    # Run CLI locally
uv run cg -e test-env status        # Test specific command
uv run ruff check --fix packages/cli/  # Lint
uv run ruff format packages/cli/    # Format
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
