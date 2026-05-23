# E2E Tests for ComfyGit

End-to-end tests that verify ComfyGit CLI operations against real ComfyUI installations.

## Quick Start

```bash
# One-time setup (downloads PyTorch, ~2GB first run)
./tests/e2e/scripts/setup-fixtures.sh

# Run smoke tests (fast, no ComfyUI startup)
uv run pytest tests/e2e/tests/smoke/ -v

# Run the deterministic CLI authoring journey
make smoke-cli

# Run slower/network smoke lanes when relevant
make smoke-cli-registry
make smoke-cli-registry-heavy
make smoke-cli-run
make smoke-cli-full

# Run all E2E tests (includes ComfyUI lifecycle)
uv run pytest tests/e2e/tests/ -v

# Skip slow tests
uv run pytest tests/e2e/tests/ -v -m "not slow"
```

## Architecture

```
tests/e2e/
├── README.md              # This file
├── conftest.py            # Pytest fixtures (workspace, cg helper, etc.)
├── .env.example           # Configuration template
├── .gitignore             # Ignores fixtures/, .cache/, .env
├── scripts/
│   └── setup-fixtures.sh  # Creates test fixtures
├── specs/                 # YAML spec files (test documentation)
│   └── environment-lifecycle.yaml
├── tests/
│   ├── smoke/             # Fast tests (no ComfyUI startup)
│   │   ├── test_infrastructure.py
│   │   └── test_environment_basics.py
│   └── integration/       # Slower tests (require ComfyUI)
│       └── test_comfyui_lifecycle.py
├── fixtures/              # Pre-built workspaces (gitignored)
│   └── basic/             # Default fixture with ComfyUI v0.4.0
└── .cache/                # UV cache (gitignored)
    └── uv/                # Shared package cache
```

## Spec-Driven Testing

Tests are driven by YAML spec files in `specs/`. Each spec documents:
- **What** is being tested
- **Why** it matters (prevents future maintainers from removing "mysterious" tests)
- **Clause references** where the test protects active truth-layer behavior

See `specs/environment-lifecycle.yaml` for an example.

## Fixtures

### `basic_fixture` (session-scoped)
Pre-built workspace at `fixtures/basic/` with:
- Default environment (`environments/default/`)
- ComfyUI v0.4.0 installed
- Python 3.12 venv

### `workspace` (function-scoped)
Alias to `basic_fixture`. Treat as read-only.

### `cg` (function-scoped)
Helper function to run CLI commands:
```python
def test_status(cg):
    result = cg("-e", "default", "status")
    assert result.returncode == 0
    assert "default" in result.stdout
```

### `shared_uv_cache` (session-scoped)
Path to shared UV cache. Persists across test runs to avoid re-downloading PyTorch.

## Configuration

Copy `.env.example` to `.env` to customize:
```bash
E2E_UV_CACHE_DIR=${PWD}/.cache/uv
E2E_COMFYUI_BASE_DIR=${PWD}/.cache/comfyui-base
E2E_FIXTURES_DIR=${PWD}/fixtures
E2E_COMFYUI_VERSION=v0.4.0
E2E_PYTHON_VERSION=3.12
```

## Test Categories

### Smoke Tests (`tests/smoke/`)
Fast tests that verify CLI operations without starting ComfyUI:
- Fixture structure validation
- Basic commands (`status`, `list`, `--version`, `--help`)
- The disposable CLI authoring journey in `test_cli_journey.py`
- No `@pytest.mark.slow`

### Integration Tests (`tests/integration/`)
Slower tests that require running ComfyUI:
- ComfyUI startup/shutdown lifecycle
- Marked with `@pytest.mark.slow`
- Use port 18188 to avoid conflicts with dev (8188-8190)

### Registry Tests
Registry-backed custom-node lifecycle tests are marked with
`@pytest.mark.registry` and `@pytest.mark.network`. Run them before releases
that touch node install, registry, manifest, or sync behavior.

The default registry smoke uses a representative lightweight node so it remains
practical to run repeatedly. Heavier node packages with expensive dependency
resolution are covered by an opt-in slow lane:

```bash
make smoke-cli-registry-heavy
```

## Adding New Tests

1. **Create a spec** in `specs/` documenting what you're testing and why
2. **Write the test** in `tests/smoke/` or `tests/integration/`
3. **Reference the spec** in test docstrings: `Spec: scenario-id.test-id`
4. **Add `@pytest.mark.slow`** if test requires ComfyUI startup

## Troubleshooting

### "Fixture not found" error
Run `./tests/e2e/scripts/setup-fixtures.sh` to create fixtures.

### Port 18188 already in use
Integration tests use port 18188. Kill any existing process on that port.

### Slow first run
First run downloads PyTorch (~2GB). Subsequent runs use cached packages.

### Reset fixtures
```bash
./tests/e2e/scripts/setup-fixtures.sh --reset
```
