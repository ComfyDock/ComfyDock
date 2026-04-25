## Important Documents

- ../../docs/contracts/core/CONTRACT.md - active core contract and invariants.
- ../../docs/specs/environment-manifest-model.md - tracked manifest semantics.
- ../../docs/specs/environment-sync-lifecycle.md - sync/run/git lifecycle.
- ../../docs/specs/dependency-criticality.md - model/node required vs optional behavior.
- docs/architecture.md - core layer overview.
- docs/layer-hierarchy.md - package-local layering reference.

Treat root `docs/contracts/` and `docs/specs/` as the active truth layer. Package
docs here provide architecture and reference detail.

## Core Package
- Code under packages/core should be assumed to be a library and properly abstracted from client rendering code.
- DO NOT couple this code with a particular frontend implementation like the CLI!
- We should NOT see any print() or input() in the core library code.
- All user interaction happens through callback protocols (see `models/protocols.py`).

## Key Managers

| Manager | File | Purpose |
|---------|------|---------|
| `PyprojectManager` | `managers/pyproject_manager.py` | pyproject.toml CRUD, UV config injection/restoration |
| `UVProjectManager` | `managers/uv_project_manager.py` | UV sync, add, remove with injection context |
| `PyTorchBackendManager` | `managers/pytorch_backend_manager.py` | `.pytorch-backend` file, GPU probing, config generation |
| `LocalUVConfigManager` | `managers/local_uv_config_manager.py` | `.local-uv-config` file, machine-local UV overrides |
| `NodeManager` | `managers/node_manager.py` | Node install/remove/update |
| `WorkflowManager` | `managers/workflow_manager.py` | Workflow tracking/resolution |
| `GitManager` | `managers/git_manager.py` | Git operations (auto-strips local paths before commit) |
| `ExportImportManager` | `managers/export_import_manager.py` | Environment export/import |

## Injection System

The core uses a temporary injection pattern for machine-specific config:
1. `uv_injection_context()` in `PyprojectManager` saves original pyproject.toml
2. Injects `.local-uv-config` sources/indexes/constraints
3. Injects `.pytorch-backend` config (wins on torch conflicts)
4. UV resolves against the merged config
5. Original pyproject.toml is restored in `finally` block

Both `.pytorch-backend` and `.local-uv-config` are auto-gitignored.

## Python Environment Management

- ALWAYS use uv and the commands below for python environment management! NEVER try to run the system python!
- uv commands should be run in the root repo directory in order to use the repo's .venv

## Development

- `uv add <package>` - Install dependencies
- `uv run ruff check --fix` - Lint and auto-fix with ruff
- `uv pip list` - View dependencies
- `uv run <command>` - Run cli tools locally installed (e.g. uv run comfygit)

## Testing

- New tests should go under tests/ under their respective category.
- Read tests/README.md for info on how to create new integration tests.
- Try to add new tests to existing test files rather than creating new files (unless necessary)
- `uv run pytest tests/ -v` - Run all tests (full info)
- `uv run pytest <filename>` - Run specific test file

#### Testing comfygit cli
- Use the existing testing workspace by seeing what path exists in COMFYGIT_HOME (cg will default to this workspace)

## Code Style

Optimize for human readability — minimize mental energy to trace logic flow.

**Flatten nesting:**
- Extract conditional values early: `x = d.get('key') if d else None` instead of `if d: ... if d.get('key'): ...`
- Max 3-4 indentation levels in a method. If deeper, extract a helper.

**Guard clauses over nested ifs:**
- Return/continue early for rejection cases instead of wrapping the happy path in else blocks.
- Each early return should make the rejection reason obvious.

**No state-tracking flags:**
- Don't use boolean flags like `checked = True` to track whether something ran. Check the actual state instead (e.g., `result is not None`).

**Extract complex decision branches:**
- If an `if` block has 3+ outcomes with its own sub-conditions, extract it into a method that returns a value or None.
- The caller reads as a flat decision chain: `try A? → try B? → try C? → fallback`.

**Keep methods scannable:**
- A method's priorities/steps should be visible without scrolling.
- Decision logic in helpers, orchestration in the caller.

## General
Don't make any implementation overly complex. This is a one-person dev MVP project.
We are still pre-customer - any unnecessary fallbacks, unnecessary versioning, testing overkill should be avoided.
Simple, elegant, maintainable code is the goal.
We DONT want any legacy or backwards compatible code.
