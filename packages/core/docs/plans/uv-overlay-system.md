# Implementation Plan: UV Overlay System

**Created:** 2026-02-06
**Status:** Draft

## Problem Statement

ComfyGit environments currently embed ALL dependencies (including platform-specific packages like `sageattention`) directly in pyproject.toml. UV resolves all dependencies — including optional ones — during `uv sync`, which means packages that cannot be built on the local machine (e.g., CUDA-only packages on macOS) cause resolution failures even when the user never requested that extra.

The existing injection system has two separate mechanisms for machine-local config:
- `.pytorch-backend` — auto-detected PyTorch backend (custom format, auto-gitignored)
- `.local-uv-config` — machine-specific UV sources/indexes (TOML, auto-gitignored)

These are hard-coded into `uv_injection_context()` with separate code paths. There's no way for users to create their own injectable dependency sets (e.g., "GPU acceleration packages" or "development tools") that layer on top of the base environment.

**The goal:** A composable overlay system where `.toml` files can inject additional dependencies, UV sources, constraints, and settings into the resolution — layered on top of the base pyproject.toml. Some overlays are shareable (checked into git), others are machine-local (gitignored). This enables environments to ship minimal portable dependencies while letting users opt into platform-specific acceleration packages.

## Proposed Solution

### Concept: UV Overlays

An **overlay** is a standalone TOML file that declares additional packages and UV configuration to merge into pyproject.toml during sync/run. Overlays compose additively — multiple overlays can be stacked.

**Two types:**
1. **Shared overlays** — Checked into git alongside the environment (e.g., `sageattention.toml`). Available to anyone who clones the environment. Opt-in at runtime.
2. **Local overlays** — Machine-specific, auto-gitignored (e.g., dev source paths, private indexes). Always active when present.

**PyTorch becomes a special-cased auto-generated overlay** — the probing logic stays, but it produces config in the same format as any other overlay, and the injection pipeline treats it uniformly.

### Overlay File Format

Overlays use a flat TOML structure (similar to `uv.toml`, not the nested `[tool.uv]` of pyproject.toml):

```toml
# .cec/overlays/sageattention.toml

[overlay]
description = "SageAttention GPU acceleration for CUDA systems"

[dependencies]
# Packages to inject into [project.dependencies]
packages = ["sageattention"]

[sources]
# UV source overrides (maps to [tool.uv.sources])
sageattention = { git = "https://github.com/thu-ml/SageAttention.git" }

[settings]
# UV settings to merge
no-build-isolation-package = ["sageattention"]

[[dependency-metadata]]
# Pre-provided metadata so UV can resolve without building
name = "sageattention"
version = "2.1.1"
requires-dist = ["torch"]
requires-python = ">=3.9"

[constraints]
# Version constraints to inject (maps to [tool.uv.constraint-dependencies])
packages = []

[[index]]
# Additional UV indexes
# name = "custom-index"
# url = "https://custom.pypi.org/simple/"
# explicit = true
```

### Directory Structure

```
.cec/
├── pyproject.toml              # Base tracked config
├── overlays/                   # Overlay directory
│   ├── sageattention.toml      # Shared (tracked in git)
│   ├── triton.toml             # Shared (tracked in git)
│   └── .local.toml             # Machine-local (gitignored via dot-prefix convention)
├── .pytorch-backend            # Still exists for probing state (generates overlay at runtime)
├── .overlay-config.toml        # Persistent activation config (gitignored)
└── .gitignore                  # Auto-managed entries
```

**Convention:** Files starting with `.` in overlays/ are auto-gitignored (machine-local). Regular names are tracked.

### Activation Model

Overlays can be activated three ways:

1. **CLI flag (one-time):** `cg run --overlay sageattention` or `cg sync --overlay sageattention`
2. **Persistent config:** `cg env-config overlays enable sageattention` (writes to `.overlay-config.toml`)
3. **Always-on local:** `.local.toml` overlay is always injected when present (replaces `.local-uv-config`)

`.overlay-config.toml` format:
```toml
# Active overlays for this machine (gitignored)
active = ["sageattention", "triton"]
```

### Merge Semantics

Overlays merge **additively** in order: base pyproject.toml → local overlay → activated overlays (alphabetical) → CLI overlays → PyTorch (last, wins on torch conflicts).

| Field | Merge Strategy |
|-------|---------------|
| `dependencies.packages` | Union (append to `[project.dependencies]`) |
| `sources` | Merge by package name (last-wins per package) |
| `settings.no-build-isolation-package` | Union (additive list) |
| `dependency-metadata` | Merge by package name (last-wins) |
| `constraints.packages` | Union with dedup by package name (last-wins per package) |
| `index` | Merge by index name (last-wins per name) |

**Conflicts:** If two overlays declare different sources for the same package, last-wins (with a logged warning). This keeps it simple — no error-on-conflict complexity.

### PyTorch Integration

PyTorch stays special-cased for **probing** (auto-detection logic remains in `PyTorchBackendManager`), but the injection now goes through the same overlay pipeline:

1. `PyTorchBackendManager.get_pytorch_config()` returns the same dict format it does now
2. The injection pipeline converts it to overlay format internally
3. PyTorch is always injected **last** so it wins on torch/torchvision/torchaudio conflicts

The `.pytorch-backend` file stays as-is (probing state storage). No migration needed — it's an implementation detail of the PyTorch overlay generation.

### Migration from `.local-uv-config`

Per project philosophy of "no legacy/backwards-compatible code": auto-migrate on first access. If `.local-uv-config` exists and `.cec/overlays/.local.toml` doesn't, convert format, write new file, delete old file.

## Implementation Steps

### Phase 1: Core Overlay Infrastructure

1. **Create `OverlayConfig` model** — Dataclass for parsed overlay
   - Fields: description, dependencies, sources, settings, dependency_metadata, constraints, indexes
   - `to_injection_payload() -> dict` — Convert to the existing `_inject_uv_config()` payload format
   - Files: `packages/core/src/comfygit_core/models/overlay.py`

2. **Create `OverlayManager`** — New manager class
   - `load_overlay(path) -> OverlayConfig` — Parse and validate overlay TOML
   - `list_overlays() -> list[OverlayInfo]` — List available overlays in `.cec/overlays/`
   - `get_active_overlays() -> list[str]` — Read `.overlay-config.toml`
   - `set_active_overlays(names)` — Write `.overlay-config.toml`
   - `collect_overlays(extra_names) -> list[OverlayConfig]` — Gather all applicable overlays in merge order
   - Auto-migrate `.local-uv-config` to `.cec/overlays/.local.toml` on first access
   - Files: `packages/core/src/comfygit_core/managers/overlay_manager.py`

3. **Refactor `uv_injection_context()`** — Generalize to accept overlays
   - New signature: `uv_injection_context(overlays: list[OverlayConfig])`
   - Add dependency injection support (inject into `[project.dependencies]`)
   - Add `dependency-metadata` injection into `[[tool.uv.dependency-metadata]]`
   - Add `no-build-isolation-package` injection
   - Keep strip-before-inject pattern for PyTorch
   - Files: `packages/core/src/comfygit_core/managers/pyproject_manager.py` (lines 466-539, 766-854)

4. **Update `UVProjectManager.sync_project()`** — Use overlay pipeline
   - Replace `pytorch_manager`/`local_uv_config_manager` params with overlay collection
   - Files: `packages/core/src/comfygit_core/managers/uv_project_manager.py` (line 250)

5. **Wire into `Environment`** — Pass overlays through sync/run
   - `Environment.sync()` collects overlays and passes to `UVProjectManager`
   - Files: `packages/core/src/comfygit_core/core/environment.py`

6. **Remove `LocalUVConfigManager`** — After migration logic is in OverlayManager
   - Files: `packages/core/src/comfygit_core/managers/local_uv_config_manager.py` (DELETE)

### Phase 2: CLI Commands

7. **Add overlay CLI commands**
   - `cg env-config overlays list` — Show available overlays and active status
   - `cg env-config overlays show <name>` — Show overlay contents
   - `cg env-config overlays enable <name>` — Activate overlay for this machine
   - `cg env-config overlays disable <name>` — Deactivate overlay
   - `cg env-config overlays create <name>` — Create template overlay file
   - Files: `packages/cli/comfygit_cli/env_commands.py`

8. **Add `--overlay` flag to `cg run` and `cg sync`**
   - Accepts overlay name(s), resolves from `.cec/overlays/<name>.toml`
   - Files: `packages/cli/comfygit_cli/cli.py`, `packages/cli/comfygit_cli/env_commands.py`

9. **Replace old `env-config local-sources` commands** with overlay equivalents
   - Files: `packages/cli/comfygit_cli/env_commands.py` (lines 443-564)

### Phase 3: Export/Import Support

10. **Export shared overlays**
    - Include `.cec/overlays/*.toml` (non-dot-prefix) in export tarballs
    - Skip `.local.toml` and other dot-prefixed overlays
    - Files: `packages/core/src/comfygit_core/managers/export_import_manager.py`

11. **Import overlay awareness**
    - On import, detect overlays and inform user which are available
    - Files: `packages/core/src/comfygit_core/managers/export_import_manager.py`

### Future: Workspace-Level Overlays (out of scope)

- Workspace-level overlay directory and config
- Default overlays applied to all environments
- Override per-environment

## File References

| File | Purpose |
|------|---------|
| `packages/core/src/comfygit_core/managers/overlay_manager.py` | **NEW** — Overlay loading, activation, collection |
| `packages/core/src/comfygit_core/models/overlay.py` | **NEW** — OverlayConfig dataclass |
| `packages/core/src/comfygit_core/managers/pyproject_manager.py` | Refactor `uv_injection_context()` and injection methods |
| `packages/core/src/comfygit_core/managers/uv_project_manager.py` | Update sync to use overlay pipeline |
| `packages/core/src/comfygit_core/core/environment.py` | Wire overlay collection into sync/run |
| `packages/core/src/comfygit_core/managers/pytorch_backend_manager.py` | No changes — generates config consumed as overlay internally |
| `packages/core/src/comfygit_core/managers/local_uv_config_manager.py` | **DELETE** after migration |
| `packages/core/src/comfygit_core/managers/export_import_manager.py` | Include shared overlays in export |
| `packages/cli/comfygit_cli/env_commands.py` | New overlay commands, replace local-sources |
| `packages/cli/comfygit_cli/cli.py` | Add --overlay flag to run/sync parsers |

## Testing Strategy

- **Unit tests for OverlayManager:** Load/parse overlay files, collect in correct order, validate format
- **Unit tests for overlay injection:** Verify dependencies, sources, constraints, metadata merge correctly into pyproject config
- **Unit test for migration:** `.local-uv-config` auto-migrates to `.local.toml`
- **Integration test:** End-to-end sync with overlay applied, verify pyproject restored after sync
- **2-3 tests per component** per project guidelines

## Open Questions

- [ ] Should overlay names allow subdirectories (e.g., `overlays/gpu/sageattention.toml`)?
- [ ] Should `cg env-config overlays create` be interactive or just create a template file?
- [ ] For `.overlay-config.toml`: should there be a way to declare "default overlays" that ARE tracked? (e.g., a tracked `.cec/overlay-defaults.toml` with suggested overlays, vs gitignored `.overlay-config.toml` for local activation)
- [ ] Should we support overlay-level platform markers to auto-skip on incompatible systems?
- [ ] Naming: "overlay" vs "addon" vs "layer" vs "profile"?

## Example: Sageattention Workflow

After this feature ships, an environment creator would:

1. Remove `sageattention` from base `[project.optional-dependencies]`
2. Create `.cec/overlays/sageattention.toml` with the overlay config
3. Commit both changes. Export environment.

**On a CUDA machine:**
```bash
cg import <url>
cg -e myenv env-config overlays enable sageattention
cg -e myenv sync   # resolves base + sageattention overlay
```

**On macOS:**
```bash
cg import <url>
cg -e myenv sync   # resolves base only — no sageattention, no build failure
```
