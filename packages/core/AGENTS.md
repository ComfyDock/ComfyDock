## Important Documents
#### only read if instructed
- docs/layer-hierarchy.md
- docs/architecture.md

## Core Package
- Code under packages/core should be assumed to be a library and properly abstracted from client rendering code.
- DO NOT couple this code with a particular frontend implementation like the CLI!
- We should NOT see any print() or input() in the core libary code.

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
