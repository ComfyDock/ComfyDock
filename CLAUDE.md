## Project Overview

ComfyGit is a monorepo workspace using uv for Python package management. It provides unified environment management for ComfyUI through multiple coordinated packages.

### Codebase Navigation

**For implementation tasks**, read the relevant architecture overview first:
- @packages/core/docs/architecture.md - Core library: layers, managers, services, protocols
- @packages/cli/docs/architecture.md - CLI: command handlers, strategies, formatters
- @packages/deploy/docs/architecture.md - Deploy: providers, worker server, async patterns

**Then use pyast** for specific symbol lookups:
```bash
# overview/symbols take a DIRECTORY (not a file)
pyast overview packages/core/src/comfygit_core/
pyast symbols packages/core/src/comfygit_core/utils/

# search takes PATH first, then QUERY (pyast search <path> <query>)
pyast search packages/core/src/comfygit_core/ "retry"
pyast search packages/core/src/comfygit_core/managers/ "injection_context"

# deps takes SYMBOL then FILE
pyast deps "Environment.sync" packages/core/src/comfygit_core/core/environment.py
```

**Key utility locations** (check before reimplementing):
- `packages/core/src/comfygit_core/utils/` - git, filesystem, retry, parsing helpers
- `packages/core/src/comfygit_core/services/` - downloads, lookups, registry

## Version Management

All packages use **lockstep versioning** - same version number, always.

```bash
make show-versions              # Check current versions
make bump-version VERSION=0.4.0 # Bump all packages
make check-versions             # CI validation
```

Publishing is automated via `.github/workflows/publish.yml` - push version bump to main and the workflow handles PyPI publishing and GitHub releases.

## Development Commands

```bash
make install    # Install all packages in dev mode
make dev        # Start dev environment
make test       # Run all tests
make lint       # Run linting
```

Cross-platform testing: `python dev/scripts/cross-platform-test.py` (see `dev/cross-platform-test.toml` for config).

## Running Tests

**IMPORTANT:** Always use `uv run pytest`, never bare `pytest`. The project uses uv for dependency management and pytest is only available through the virtual environment.

```bash
# From repo root - run all tests
uv run pytest packages/core/tests/ -v

# Run specific test file
uv run pytest packages/core/tests/unit/managers/test_pyproject_manager.py -v

# Run specific test class or function
uv run pytest packages/core/tests/unit/managers/test_pyproject_manager.py::TestStripLocalPathSources -v

# Run tests matching a pattern
uv run pytest packages/core/tests/ -k "injection" -v

# Quick run (no verbose)
uv run pytest packages/core/tests/unit/managers/test_local_uv_config_manager.py -q
```

**Test locations:**
- `packages/core/tests/unit/` - Unit tests for core library
- `packages/core/tests/integration/` - Integration tests
- `packages/cli/tests/` - CLI tests
- `packages/deploy/tests/` - Deploy tests

## Validation

Use `/validate` after features or fixes that change observable behavior. The skill covers quick checks against the shared workspace and full validation with disposable workspaces via `dev/scripts/validation-workspace.sh`.

## Important Notes

- Both packages must always have the same version (lockstep)
- Never manually edit version numbers - use `make bump-version`
- Code should work across Linux, Windows, and Mac

## Issue Tracking (Beads)

This project uses beads (`bd`) for issue tracking with the **`cg-`** prefix.

```bash
bd ready                # Show unblocked work
bd show cg-abc          # View issue details
bd create "Fix the bug" --type=bug --priority=2
bd close cg-abc         # Close an issue
bd sync                 # Sync with remote
```

For epics with child tasks:
```bash
bd create "Big feature" --type=epic
bd create "Phase 1" --type=task --parent=cg-xxx
bd dep add cg-xxx.2 cg-xxx.1
```

## General

Don't make any implementation overly complex. This is a one-person dev MVP project.
We are still pre-customer - any unnecessary fallbacks, unnecessary versioning, testing overkill should be avoided.
2-3 tests per file with only the main happy path tested is fine.
Simple, elegant, maintainable code is the goal.
We DONT want any legacy or backwards compatible code. If you make changes that will break older code that's good, make the new changes and then fix the older code to use the new code.
