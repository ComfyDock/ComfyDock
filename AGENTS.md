<!-- NOTE: This file must stay in sync with CLAUDE.md. If you update one, update the other. -->

## Project Overview

ComfyGit is a monorepo workspace using uv for Python package management. It provides unified environment management for ComfyUI through multiple coordinated packages. Licensed under GPL-3.0.

### Packages

| Package | PyPI Name | CLI Commands | Description |
|---------|-----------|--------------|-------------|
| `packages/core/` | comfygit-core | — | Core library for environment management |
| `packages/cli/` | comfygit | `comfygit`, `cg` | Main CLI |
| `packages/deploy/` | comfygit-deploy | `cg-deploy` | Remote deployment |

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

## CLI Reference

### Global Commands
```bash
cg init                          # Initialize workspace
cg list                          # List all environments
cg update                        # Upgrade ComfyGit CLI to latest version
cg update --check                # Check for updates without upgrading
cg import <source>               # Import environment from tarball or git URL
cg export                        # Export environment
cg config                        # Manage configuration settings
cg completion                    # Manage shell tab completion
```

### Environment Lifecycle
```bash
cg create <name>                 # Create new environment
cg use <name>                    # Set active environment
cg delete <name>                 # Delete environment
cg -e <name> run                 # Run ComfyUI
cg -e <name> run --no-sync       # Run without syncing first
cg -e <name> run -- --port 8189  # Pass args to ComfyUI via --
cg -e <name> status              # Show sync + git status
cg -e <name> manifest            # Show pyproject.toml contents
cg -e <name> sync                # Sync packages and dependencies
cg -e <name> repair              # Repair environment to match pyproject
cg -e <name> doctor              # Diagnose and repair uv tooling
cg -e <name> doctor --check-only # Check only, don't repair
```

### Node Management
```bash
cg -e <name> node add <id>           # Add node (registry ID, GitHub URL, or local dir)
cg -e <name> node add <id> --dev     # Track existing local development node
cg -e <name> node add <id> --strict  # Fail on dependency conflicts
cg -e <name> node remove <id>        # Remove node
cg -e <name> node update <id>        # Update node to latest
cg -e <name> node list               # List installed nodes
```

### Python Dependencies
```bash
cg -e <name> py add <packages>              # Add Python dependencies
cg -e <name> py add <pkg> --no-build-isolation  # For CUDA packages needing PyTorch at build time
cg -e <name> py add <pkg> --optional <extra> # Add to optional dependency group
cg -e <name> py add <pkg> --group <group>    # Add to dependency group
cg -e <name> py add <pkg> --dev              # Add to dev dependencies
cg -e <name> py add <pkg> --editable         # Install as editable
cg -e <name> py add -r requirements.txt      # Add from requirements file
cg -e <name> py remove <packages>            # Remove dependencies
cg -e <name> py remove-group <group>         # Remove entire dependency group
cg -e <name> py list                         # List dependencies
cg -e <name> py uv <args>                    # Direct UV passthrough (advanced)
```

### Git Operations
```bash
cg -e <name> commit -m "message"  # Commit environment changes
cg -e <name> log                  # Show commit history
cg -e <name> branch               # List/create/delete branches
cg -e <name> switch <branch>      # Switch branches
cg -e <name> checkout <ref>       # Checkout commits/branches/files
cg -e <name> pull                 # Pull and repair environment
cg -e <name> push                 # Push to remote
cg -e <name> remote               # Manage git remotes
cg -e <name> merge <branch>       # Merge branch
cg -e <name> reset                # Reset HEAD
cg -e <name> revert               # Revert a commit
```

### Environment Configuration
```bash
# PyTorch backend (machine-specific, gitignored)
cg -e <name> env-config torch-backend show     # Show current backend
cg -e <name> env-config torch-backend set <be>  # Set backend (cu128, cpu, etc.)
cg -e <name> env-config torch-backend detect    # Auto-detect recommended backend

# Local UV source overrides (machine-specific, gitignored)
cg -e <name> env-config local-sources show       # Show local overrides
cg -e <name> env-config local-sources add <pkg> --path /path --editable  # Add local source
cg -e <name> env-config local-sources remove <pkg>  # Remove local source

# Default sync extras
cg -e <name> env-config extras show              # Show default extras
cg -e <name> env-config extras add <extra>       # Add default extra for sync
cg -e <name> env-config extras remove <extra>    # Remove default extra
```

### Optional Extras (one-time flags)
```bash
cg -e <name> sync --extra <extra>      # Sync with optional extra
cg -e <name> sync --all-extras         # Sync with all extras
cg -e <name> run --extra <extra>       # Run with optional extra
cg -e <name> run --all-extras          # Run with all extras
cg -e <name> node add <id> --extra <e> # Install node with optional extra
```

### PyTorch Backend Override (one-time)
```bash
cg -e <name> sync --torch-backend cu128   # Override for this sync only
cg -e <name> run --torch-backend cpu      # Override for this run only
# Valid backends: cpu, cu124, cu126, cu128, rocm6.3, xpu
```

### Manager (comfygit-manager custom node)
```bash
cg -e <name> manager status   # Show manager version and update availability
cg -e <name> manager update   # Update or migrate comfygit-manager
```

### Other
```bash
cg -e <name> workflow list    # List tracked workflows
cg -e <name> constraint       # Manage UV constraint dependencies
cg -e <name> model            # Manage model index
cg -e <name> metadata         # Manage environment metadata
cg registry                   # Manage node registry cache
cg orch                       # Monitor/control orchestrator
cg debug                      # Show debug logs
```

## Machine-Specific Dependency Injection

ComfyGit keeps environments portable by separating machine-specific config from the tracked `pyproject.toml`. Two gitignored files handle this:

### `.pytorch-backend`
Auto-detected per machine. Stores the PyTorch CUDA backend (e.g., `cu128`, `cpu`) and exact wheel versions. On import/create, ComfyGit probes the local GPU and writes this file. During sync, the PyTorch config is temporarily injected into pyproject.toml, resolved by UV, then removed.

### `.local-uv-config`
Machine-specific TOML file for overriding package sources, adding custom indexes, or pinning constraint dependencies. Managed via `cg env-config local-sources`. Contents are injected at sync time but never committed.

```toml
# Example: Use local editable build of sageattention
[sources]
sageattention = { path = "/home/user/SageAttention", editable = true }

# Example: Custom package index
[[index]]
name = "corp"
url = "https://pypi.corp/simple/"
```

### Update Notice System
Background PyPI check runs on every CLI invocation. If a newer version exists, a one-line notice is printed to stderr. Cached in `~/.config/comfygit/update_state.json` with 24h recheck window. Disable with `COMFYGIT_NO_UPDATE_CHECK=1`.

### Environment Name Validation
Names must be 1-64 chars, alphanumeric + hyphens/underscores, no leading/trailing hyphens. Applied at create and import time.

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
make install / make dev / make test / make lint
```

Cross-platform testing: `python dev/scripts/cross-platform-test.py` (config: `dev/cross-platform-test.toml`).

## Running Tests

**Always use `uv run pytest`** (never bare `pytest`).

```bash
uv run pytest packages/core/tests/ -v                    # All core tests
uv run pytest packages/core/tests/unit/managers/test_pyproject_manager.py -v  # Specific file
uv run pytest packages/core/tests/ -k "injection" -v     # Pattern match
```

Test locations: `packages/core/tests/{unit,integration}/`, `packages/cli/tests/`, `packages/deploy/tests/`

## Validation

Use `/validate` after features or fixes that change observable behavior (uses `dev/scripts/validation-workspace.sh`).

## Important Notes

- All packages must have the same version (lockstep) — use `make bump-version`
- Code should work across Linux, Windows, and Mac

## Issue Tracking (Beads)

Uses beads (`bd`) with prefix **`cg-`**. Use for multi-session or dependent work; skip for simple single-session fixes.

```bash
# Workflow: bd ready → bd show cg-xxx → bd update cg-xxx --status=in_progress → implement → bd close cg-xxx --reason="..." → bd sync
bd ready                           # Show unblocked work
bd show cg-xxx                     # Full context + acceptance criteria
bd list --status=open              # All open issues
bd create --title="..." --type=bug --priority=2  # Types: task/bug/feature/epic, Priority: 0-4
bd dep add cg-yyy cg-xxx           # cg-yyy depends on cg-xxx
bd close cg-xxx cg-yyy             # Close one or more
```

Always run `bd show <id>` before starting work — beads contain implementation context, file lists, and acceptance criteria.

### Commit Convention — Bead References

**When a commit implements, fixes, or closes a bead, include the bead ID(s) in the commit message.** This creates traceability between git history and issue tracking.

Format: `<description> [<bead-id>]` or `<description> [<bead-id>, <bead-id>]`

```
Fix cnr_id mapping upgrade flow and add resolver tests [cg-e7u]
Add version-indexed builtins pipeline [crd-5pa, cg-2ih]
Fix builtin extraction for cls constant node IDs [cg-2ih]
```

- Place bead ID(s) at the end of the first line in square brackets
- Use this for commits that directly address bead work — skip for unrelated housekeeping commits
- If a commit fully resolves a bead, also close it with `bd close`

## General

Don't make any implementation overly complex. This is a one-person dev MVP project.
We are still pre-customer - any unnecessary fallbacks, unnecessary versioning, testing overkill should be avoided.
2-3 tests per file with only the main happy path tested is fine.
Simple, elegant, maintainable code is the goal.
We DONT want any legacy or backwards compatible code. If you make changes that will break older code that's good, make the new changes and then fix the older code to use the new code.
