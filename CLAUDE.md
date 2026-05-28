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
| `packages/studio/` | Shared React/Vite Studio frontend bundled into CLI static assets and reused by hosted Cloud surfaces. |
| `packages/studio-runtime/` | Python runtime for contract-shaped HTTP APIs, Studio static serving, uploads, gallery/run state, and ComfyUI execution adapters shared by CLI and Manager. |
| `docs/contracts/` | Active truth-layer contracts. Highest-precedence behavioral guarantees. |
| `docs/specs/` | Active truth-layer lifecycle, manifest, and dependency semantics. |
| `docs/comfygit-docs/` | Public user documentation site. Do not treat as active architecture truth. |
| `docker/`, `tests/` | Runtime images and cross-package tests. |

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
- Git commits are environment snapshots for local collaboration and build
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
- `packages/studio/AGENTS.md`

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

Hosted deployment code should consume manifest/core semantics rather than
inventing parallel environment metadata.

## Core Type Boundaries

Core is consumed by Manager, CLI, Cloud, and future runtime adapters. Stable
domain results that cross package or repo boundaries should use typed
dataclasses, protocols, or explicit model objects instead of anonymous nested
dictionaries.

Use dictionaries at serialization and dynamic-data edges:

- HTTP/API responses
- JSON/TOML parsing
- provider payloads with unstable schemas
- narrow test fixtures

When a typed result needs to cross an API boundary, expose a `to_dict()` method
or dedicated serializer at that edge. Keep the core service return type typed so
callers can inspect the shape through IDEs and type checkers. Avoid
`dict[str, Any]` returns for stable domain concepts such as readiness results,
build plans, dependency proofs, source candidates, environment summaries, and
manifest-derived reports.

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
uv run pytest packages/studio-runtime/tests/ -v
uv run pytest packages/cli/tests/ -v
npm --prefix packages/studio run build
uv run ruff check --fix
uv run ty check packages/core/src/comfygit_core/models/readiness.py packages/core/src/comfygit_core/services/environment_readiness.py
```

Core, Studio runtime, CLI, and bundled Studio release artifacts use lockstep versioning:

```bash
make show-versions
make bump-version VERSION=<version>
make check-versions
```

`packages/studio` is not a Python package, but it is versioned with the Python
packages because the `comfygit-studio` Python runtime release ships its built
static output.

Release setup for a new ComfyGit version:

1. Pick one version for `comfygit-core`, `comfygit-studio`, `comfygit`, and
   `@comfygit/studio`.
2. Run `make bump-version VERSION=<version>`.
3. Run `uv lock` from the repo root so `uv.lock` reflects the Python package
   graph.
4. Run `make check-versions` and `make build-all`. `make build-all` builds
   Studio, syncs `packages/studio/dist/static/` into
   `packages/studio-runtime/comfygit_studio/static/`, then builds the Python
   packages.
5. Run focused tests for the changed areas, plus truth-layer validation when
   contracts/specs changed.
6. Commit the version bump, lockfile, bundled Studio static assets, and release
   tooling/doc updates together.

The publish workflow on `main` publishes `comfygit-core` first, waits until that
version is visible on PyPI, then publishes `comfygit-studio`, then publishes the
CLI package. This ordering matters because `comfygit-studio` pins
`comfygit-core==<version>` and `comfygit` pins both
`comfygit-core==<version>` and `comfygit-studio==<version>`.

`packages/deploy`/`comfygit-deploy` has been retired and deleted. Do not add it
back to workspace members, lockstep versioning, tests, build targets, or publish
workflows. Hosted deployment belongs to ComfyGit Cloud; local/manual serving
belongs to `cg serve`.

Manager release ordering is separate and dependent on this repo. After
`comfygit-core==<version>` and `comfygit-studio==<version>` are published on
PyPI, the sibling `comfygit-manager` repo can pin those exact versions, rebuild
its panel, and publish its ComfyUI registry release. Do not publish Manager
against unpublished core or Studio runtime pins.

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
uv run pytest packages/studio-runtime/tests/ -v
uv run pytest packages/cli/tests/ -v
npm --prefix packages/studio run build
```

Type validation for new/changed core library boundaries:

```bash
uv run ty check <changed-core-files>
```

Pylance-style validation for new/changed Python files:

```bash
uv run pyright <changed-python-files>
```

If `pyright` is not installed in the current uv environment, use the Node
distribution against the repo venv so imports resolve like the local CLI does:

```bash
npx --yes pyright --pythonpath .venv/bin/python <changed-python-files>
```

Start with targeted files rather than forcing whole-repo type strictness at
once. Expand coverage when the touched areas are clean.

If available in the current environment, `/validate` runs the repo validation
workspace script (`dev/scripts/validation-workspace.sh`).

## Engineering Preferences

- Keep behavior simple and explicit; this is still a pre-customer MVP.
- Avoid unnecessary fallbacks, compatibility layers, and broad abstractions.
- Prefer changing old code to match the new model over carrying legacy behavior.
- Add enough tests to protect the main path and important edge cases; do not add
  large test matrices for low-risk changes.
- Keep all packages cross-platform where practical: Linux, macOS, and Windows.
- Prefer file-level constants for shared lookup tables, MIME/extension maps,
  protocol strings, limits, and other values likely to expand or change. Avoid
  duplicating inline dictionaries or magic literals across helper functions when
  a single top-level constant would make future changes safer.
