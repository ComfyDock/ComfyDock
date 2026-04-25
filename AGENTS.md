<!-- NOTE: AGENTS.md and CLAUDE.md must stay in sync. If you update one, update the other. -->

# ComfyGit Agent Guide

ComfyGit is a uv-managed Python monorepo for ComfyUI environment management.
It is licensed GPL-3.0 and currently optimized for a one-person, pre-customer
MVP workflow: simple, direct, maintainable changes beat generalized framework
work.

## Repo Map

| Path | Purpose |
| --- | --- |
| `packages/core/` | UI-agnostic library for workspaces, environments, manifests, sync, models, nodes, git, and resolution. |
| `packages/cli/` | `comfygit` / `cg` command-line interface over core behavior. |
| `packages/deploy/` | Remote deployment experiments and deployment-facing package code. |
| `docs/contracts/` | Active truth-layer contracts. Highest-precedence behavioral guarantees. |
| `docs/specs/` | Active truth-layer lifecycle, manifest, and dependency semantics. |
| `docs/comfygit-docs/` | Public user documentation site. Do not treat as active architecture truth. |
| `docker/`, `scripts/`, `tests/` | Runtime images, helper scripts, and cross-package tests. |

## Truth Layer

Before changing behavior, check the active truth layer in this order:

1. `docs/contracts/` - normative guarantees and boundaries.
2. `docs/specs/` - lifecycle/state-machine behavior and manifest semantics.
3. `packages/*/docs/` - package architecture, design notes, and reference.
4. `docs/comfygit-docs/` - public user documentation.

Use `docs/spec-driven-development.md` for clause syntax and validation rules.
If implementation direction conflicts with an active clause, update the truth
layer first. Reference clause IDs in substantial commits/tests when practical.

Key current direction:

- Environment repositories use tracked `pyproject.toml` as the portable source
  of truth.
- Git commits are environment snapshots for local collaboration and cloud build
  planning.
- Machine-specific settings such as PyTorch backend and local editable sources
  stay gitignored and are injected during sync/run.
- Model bytes are external assets; manifests track metadata, hashes, sources,
  paths, workflow references, and criticality.
- Custom node criticality is moving toward explicit manifest metadata:
  missing criticality reads as required, optional nodes warn instead of block,
  and workflow graph usage is advisory rather than authoritative.

## Codebase Navigation

For implementation work, start with the package architecture docs:

- `packages/core/docs/architecture.md`
- `packages/cli/docs/architecture.md`
- `packages/deploy/docs/architecture.md`

Then inspect concrete symbols with `rg` first. `pyast` is useful when available:

```bash
pyast overview packages/core/src/comfygit_core/
pyast symbols packages/core/src/comfygit_core/utils/
pyast search packages/core/src/comfygit_core/ "injection_context"
pyast deps "Environment.sync" packages/core/src/comfygit_core/core/environment.py
```

Core utility locations worth checking before reimplementing:

- `packages/core/src/comfygit_core/utils/` - git, filesystem, retry, parsing helpers.
- `packages/core/src/comfygit_core/services/` - downloads, lookups, registry.
- `packages/core/src/comfygit_core/managers/` - orchestration over manifest, uv, git, nodes, workflows, and models.
- `packages/core/src/comfygit_core/models/` - dataclasses, protocols, exceptions, and shared schema types.

## Package Boundaries

Core is a library. Do not couple it to CLI, manager UI, or ComfyUI panel rendering.
Normal core behavior should avoid `print()` and `input()`; use callbacks,
protocols, strategies, and return values so callers own UX.

CLI code should translate user commands into core calls and render output. Avoid
moving core policy into CLI handlers unless it is truly command-specific.

Deploy code should consume manifest/core semantics rather than inventing parallel
environment metadata.

## Environment Model

ComfyGit keeps portable environment truth separate from machine-local runtime
configuration.

- Tracked manifest: `pyproject.toml`.
- Runtime state: `.cec/`, virtualenvs, checkouts, symlinks, caches, and local databases.
- Local PyTorch backend: `.pytorch-backend`, gitignored.
- Local uv source/index overrides: `.local-uv-config`, gitignored.

Sync/run may recreate the managed virtualenv. Manual package installs into that
venv are disposable unless captured with `cg -e <env> py add ...` or local uv
source configuration.

Useful environment commands:

```bash
cg create <name>
cg use <name>
cg -e <name> sync
cg -e <name> run
cg -e <name> status
cg -e <name> manifest
cg -e <name> node add <id>
cg -e <name> py add <package>
cg -e <name> commit -m "message"
cg -e <name> push
cg -e <name> env-config local-sources add <pkg> --path <path> --editable
cg -e <name> env-config torch-backend detect
```

## Development Commands

Use uv from the repo root. Do not use bare system Python for development tasks.

```bash
make install
make dev
make test
make lint
uv run pytest packages/core/tests/ -v
uv run pytest packages/cli/tests/ -v
uv run pytest packages/deploy/tests/ -v
uv run ruff check --fix
```

All packages use lockstep versioning:

```bash
make show-versions
make bump-version VERSION=<version>
make check-versions
```

## Validation

Use focused tests for narrow changes and broader validation for behavior touching
manifest, sync, git, import/export, or package boundaries.

Truth-layer validation:

```bash
python3 <path-to-spec-workflows-skill>/scripts/validate_contract_docs.py docs
```

Repo validation:

```bash
uv run pytest packages/core/tests/ -v
uv run pytest packages/cli/tests/ -v
uv run pytest packages/deploy/tests/ -v
```

If available in the current environment, `/validate` runs the repo validation
workspace script (`dev/scripts/validation-workspace.sh`).

## Engineering Preferences

- Keep behavior simple and explicit; this is still a pre-customer MVP.
- Avoid unnecessary fallbacks, compatibility layers, and broad abstractions.
- Prefer changing old code to match the new model over carrying legacy behavior.
- Add enough tests to protect the main path and important edge cases; do not add
  large test matrices for low-risk changes.
- Keep all packages cross-platform where practical: Linux, macOS, and Windows.
