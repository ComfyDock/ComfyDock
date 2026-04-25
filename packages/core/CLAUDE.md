<!-- NOTE: packages/core/AGENTS.md and packages/core/CLAUDE.md must stay in sync. -->

# ComfyGit Core Agent Guide

`packages/core` is the UI-agnostic library package. It owns workspace and
environment state, manifest semantics, sync/materialization behavior, model and
node metadata, git orchestration, and callback/protocol contracts used by CLI,
manager, deploy, and cloud-facing tooling.

## Active Truth Layer

Read root truth-layer docs before changing core behavior:

- `../../docs/contracts/core/CONTRACT.md` - active core contract and invariants.
- `../../docs/specs/environment-manifest-model.md` - tracked manifest semantics.
- `../../docs/specs/environment-sync-lifecycle.md` - sync/run/git lifecycle.
- `../../docs/specs/dependency-criticality.md` - model/node required vs optional behavior.
- `../../docs/spec-driven-development.md` - clause syntax and validation rules.

Package docs are supporting reference:

- `docs/architecture.md` - core layer overview.
- `docs/layer-hierarchy.md` - package-local layering reference.
- `docs/knowledge/` - topic-specific behavior notes.
- `docs/plans/` - planning docs; verify against truth-layer clauses before treating as current.

## Core Boundaries

- Keep core independent of CLI, manager UI, and ComfyUI panel rendering.
- Avoid normal-use `print()` and `input()` in core; expose callbacks,
  strategies, protocols, return values, and exceptions so callers own UX.
- Prefer `Workspace` and `Environment` as public entry points. Keep direct manager
  access for internal composition, tests, and package-local advanced behavior.
- Do not put cloud-only policy into core. Core should write/read portable
  manifest semantics that cloud can consume.

## Source Map

| Path | Purpose |
| --- | --- |
| `src/comfygit_core/core/` | Public `Workspace` and `Environment` APIs. |
| `src/comfygit_core/managers/` | Stateful orchestration for pyproject, uv, git, nodes, workflows, models, overlays, and symlinks. |
| `src/comfygit_core/models/` | Dataclasses, protocols, exceptions, manifest/workflow/sync types. |
| `src/comfygit_core/resolvers/` | Node and model resolution logic. |
| `src/comfygit_core/services/` | Stateless business logic, registry/model lookup, downloads, workflow services. |
| `src/comfygit_core/repositories/` | SQLite-backed caches and persistent indexes. |
| `src/comfygit_core/analyzers/` | Workflow, git, config, model, and custom-node analysis. |
| `src/comfygit_core/integrations/` | External command integrations such as uv. |
| `src/comfygit_core/utils/` | Low-level filesystem, git, dependency, PyTorch, retry, and parsing helpers. |

Check existing managers/services before adding new abstractions.

## Key Managers

| Manager | File | Main responsibility |
| --- | --- | --- |
| `PyprojectManager` | `managers/pyproject_manager.py` | Manifest CRUD and temporary uv/PyTorch injection. |
| `UVProjectManager` | `managers/uv_project_manager.py` | uv sync/add/remove operations. |
| `OverlayManager` | `managers/overlay_manager.py` | Overlay loading and legacy `.local-uv-config` migration. |
| `PyTorchBackendManager` | `managers/pytorch_backend_manager.py` | `.pytorch-backend`, GPU probing, torch source config. |
| `NodeManager` | `managers/node_manager.py` | Custom node install/remove/update. |
| `WorkflowManager` | `managers/workflow_manager.py` | Workflow tracking, node/model resolution, contract metadata. |
| `EnvironmentModelManager` | `managers/environment_model_manager.py` | Environment-level model status and metadata aggregation. |
| `GitManager` | `managers/git_manager.py` | Environment repo git operations. |
| `ExportImportManager` | `managers/export_import_manager.py` | Portable environment import/export. |

## Manifest And Local State

Tracked portable truth lives in each environment repo's `pyproject.toml`.
Runtime/materialized state lives under environment runtime directories such as
`.cec/`, virtualenvs, ComfyUI checkouts, symlinks, caches, and local SQLite DBs.

Machine-local sync inputs are not portable manifest truth:

- `.pytorch-backend` stores local torch backend choice and generated source pins.
- Local uv overrides now flow through overlays, with legacy `.local-uv-config`
  migrated by `OverlayManager`.

`PyprojectManager.uv_injection_context()` temporarily merges local overlays and
PyTorch backend config into `pyproject.toml` for uv operations, then restores the
tracked manifest in a `finally` path. Preserve that invariant.

## Dependency Criticality

Current model criticality supports required, flexible, and optional. Required
unresolved models are reproducibility blockers; optional unresolved models are
warnings.

Custom node criticality is planned as explicit manifest metadata:

- Supported values should start as `required` and `optional`.
- Missing criticality reads as `required`.
- Optional unresolved nodes warn instead of blocking cloud/build readiness.
- Workflow graph usage can inform UI messaging, but must not silently downgrade
  user-declared custom node criticality.

## Testing

Run tests from the repo root with uv:

```bash
uv run pytest packages/core/tests/ -v
uv run pytest packages/core/tests/unit/managers/test_pyproject_manager.py -v
uv run pytest packages/core/tests/ -k "injection" -v
```

Core tests should usually exercise core APIs and fixtures rather than subprocess
CLI calls. See `tests/README.md` for fixture details:

- `test_workspace` creates an isolated workspace.
- `test_env` creates a minimal environment without cloning ComfyUI.
- `test_models` creates indexed model stubs.
- `tests/helpers/` has workflow builders and pyproject assertions.

## Style

- Keep orchestration methods scannable; extract complex decision logic.
- Prefer guard clauses over nested branches.
- Avoid state-tracking boolean flags when the actual state can be checked.
- Keep compatibility/fallback code only when it protects real current behavior.
- Add focused tests for main paths and important edge cases; avoid large matrices
  for low-risk changes.
