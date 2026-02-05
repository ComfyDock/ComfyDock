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

**Python commands:** Use `uv run` for running Python scripts and tools (e.g., `uv run docs/comfygit-docs/scripts/generate_cli_reference.py`). Avoid calling `python` directly.

Cross-platform testing: `uv run dev/scripts/cross-platform-test.py` (see `dev/cross-platform-test.toml` for config).

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

### When to Use Beads
- **Use beads** for multi-session work, work with dependencies, or discovered tasks
- **Skip beads** for simple single-session fixes where tracking adds no value
- When in doubt, prefer beads - persistence you don't need beats lost context

### Session Workflow
```bash
# 1. Find available work
bd ready                    # Show unblocked issues

# 2. Read the issue details
bd show cg-xxx              # Full context, acceptance criteria, files to modify

# 3. Claim the work
bd update cg-xxx --status=in_progress

# 4. Implement the task...

# 5. Close when done
bd close cg-xxx --reason="Implemented in commit abc123"

# 6. Sync at session end
bd sync
```

### Common Commands
```bash
bd ready                           # Show unblocked work
bd list --status=open              # All open issues
bd show cg-xxx                     # View issue details
bd blocked                         # Show blocked issues and why

# Creating issues
bd create --title="Fix the bug" --type=bug --priority=2
bd create --title="New feature" --type=feature --priority=2

# Priority: 0=critical, 1=high, 2=medium (default), 3=low, 4=backlog
# Types: task, bug, feature, epic

# Dependencies
bd dep add cg-yyy cg-xxx           # cg-yyy depends on cg-xxx (xxx blocks yyy)

# Closing
bd close cg-xxx                    # Close single issue
bd close cg-xxx cg-yyy cg-zzz      # Close multiple at once
bd close cg-xxx --reason="Done in commit abc"  # Close with reason
```

### For Epics with Child Tasks
```bash
bd create --title="Big feature" --type=epic
bd create --title="Phase 1" --type=task --parent=cg-xxx
bd create --title="Phase 2" --type=task --parent=cg-xxx
bd dep add cg-xxx.2 cg-xxx.1       # Phase 2 depends on Phase 1
```

### Reading Bead Notes
Beads contain detailed implementation context in their notes:
- **Context & Goal** - Why this matters
- **Current vs Target State** - Code before/after with file paths
- **Files Inventory** - What to read/modify/create
- **Acceptance Criteria** - How to verify completion

Always run `bd show <id>` before starting work to get full context.

## General

Don't make any implementation overly complex. This is a one-person dev MVP project.
We are still pre-customer - any unnecessary fallbacks, unnecessary versioning, testing overkill should be avoided.
2-3 tests per file with only the main happy path tested is fine.
Simple, elegant, maintainable code is the goal.
We DONT want any legacy or backwards compatible code. If you make changes that will break older code that's good, make the new changes and then fix the older code to use the new code.
