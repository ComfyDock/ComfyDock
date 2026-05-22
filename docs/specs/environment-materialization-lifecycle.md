# Environment Materialization Lifecycle

This spec describes how ComfyGit should hydrate a portable environment source
into a runnable runtime environment for headless contexts such as Docker builds,
remote machines, CI smoke tests, or API-serving containers.

Materialization is related to import, but it is not the same product flow.
Import is an authoring workflow for a person setting up an environment.
Materialization is a non-interactive runtime/build workflow for recreating a
declared environment from portable truth.

## Command Shape

### CGMAT-CMD-01 [LIVE]: `cg materialize` is a top-level headless command
Validation: MIXED

The CLI exposes a top-level `cg materialize SOURCE` command that creates a
managed environment from a portable source without prompting. The command should
accept an explicit environment name and should be usable in Dockerfile, CI, and
remote-machine setup scripts.

Expected options include:

- `--name <env>` for the target environment name.
- `--workspace <path>` for an explicit workspace root.
- `--models-dir <path>` for the machine-local model directory.
- `--branch <ref>` for Git sources.
- `--torch-backend <backend>` for local PyTorch backend selection.
- `--models skip|required|all` for model download strategy.
- `--with-manager` to opt into Manager installation.
- `--use` to set the materialized environment active.
- `--replace` to intentionally remove an existing target environment.

### CGMAT-CMD-02 [LIVE]: Materialize defaults are runtime-safe
Validation: TEST

`cg materialize` defaults to behavior suitable for build/runtime contexts:

- model strategy: `skip`
- Manager registration: disabled
- PyTorch backend: `auto`
- sync error handling: fail the command
- import commit creation: disabled

These defaults avoid slow model downloads, UI-only dependencies, and misleading
authoring commits in generated runtime environments. Callers can opt into model
downloads or Manager installation explicitly.

## Source Handling

### CGMAT-SRC-01 [LIVE]: Materialization supports Git, bundle, and directory sources
Validation: MIXED

Materialization accepts the same portable sources as import where possible:
Git repositories, exported bundles, and plain directories containing a portable
environment repository. Git and bundle sources may reuse existing import source
preparation logic. Directory sources require a dedicated preparation path.

### CGMAT-SRC-02 [LIVE]: Directory sources are copied as portable recipe input
Validation: TEST

A directory source is valid when it contains a `pyproject.toml` environment
manifest. The materialization path copies portable recipe files such as:

- `pyproject.toml`
- `.python-version`
- `package_config.toml`
- `workflows/`
- shared, non-local `overlays/*.toml`

The materialization path should not copy:

- `.git/` from plain directory sources
- `.venv/`
- `.complete`
- cache directories
- local overlays
- ComfyUI runtime checkouts
- generated SQLite databases
- logs
- model bytes

Git sources preserve repository identity through the Git import path. Plain
directory sources are treated as source snapshots, not as Git history.

### CGMAT-SRC-03 [LIVE]: Model directory is configured before environment construction
Validation: TEST

When `--models-dir` is provided, workspace model-directory configuration should
be updated before constructing the target `Environment`. Environment instances
read the workspace model directory during initialization, so setting it after
construction risks creating symlinks to stale model paths.

## Core API Shape

### CGMAT-API-01 [LIVE]: Core exposes typed materialization inputs and results
Validation: STATIC

Core exposes typed materialization objects rather than passing ad hoc
dictionaries through CLI and runtime code. A minimal model should include:

- source path or URL
- target environment name
- optional workspace path
- optional Git branch/ref
- optional model directory
- model strategy
- PyTorch backend
- Manager inclusion flag
- active-environment flag
- replace behavior
- sync-failure policy
- import-commit policy

The result should report the materialized environment name, workspace path,
environment path, manifest repository path, ComfyUI path, selected model strategy,
and resolved torch backend when available.

### CGMAT-API-02 [LIVE]: Workspace owns materialization orchestration
Validation: MIXED

Callers should enter materialization through a workspace-level API rather than
orchestrating factory and environment internals directly. The workspace API
validates the environment name, configures machine-local model directory
state, prepares the source through the appropriate factory method, calls
finalization with materialization defaults, and cleans up partial environments on
failure.

### CGMAT-API-03 [LIVE]: Import finalization is shared but parameterized
Validation: TEST

Materialization reuses the existing import finalization phases where
possible: ComfyUI restore/clone, built-in extraction, symlink setup, workflow
copy, uv sync, custom node installation, and model-intent preparation. The shared
finalization path is parameterized so import and materialize can differ
without duplicating the environment setup pipeline.

Important behavioral switches:

- `create_import_commit=true` for authoring import, `false` for materialize.
- `fail_on_sync_errors=false` for current import behavior, `true` for
  materialize.
- `no_manager=false` for normal import unless requested, `true` for
  materialize unless `--with-manager` is used.

### CGMAT-API-04 [PARTIAL]: Built-in extraction captures model-loader metadata
Validation: MIXED

Create, import, repair, and materialization flows should refresh local derived
metadata from the active ComfyUI checkout before workflow dependency analysis is
treated as complete. This derived metadata should include the current built-in
node inventory, active ComfyUI model folder paths, and generated built-in
model-loader mappings used by core workflow parsing.

These extraction artifacts belong in local runtime state, not in the portable
environment manifest. If extraction fails or ComfyUI is unavailable, callers may
continue with static fallback metadata, but should not silently rewrite manifest
model dependencies based on incomplete extraction. Current create/import/refresh
paths can extract and consume folder-path and model-loader metadata, but broad
coverage of all dynamic ComfyUI loader forms remains partial.

## Failure And Cleanup

### CGMAT-FAIL-01 [LIVE]: Materialization exits nonzero on dependency sync failure
Validation: TEST

If uv sync, custom-node installation, required dependency resolution, or manifest
validation fails, materialization should fail the command and leave no completed
environment marker. Partial environment cleanup should use the same cleanup
policy as import/create.

### CGMAT-FAIL-02 [PARTIAL]: Model downloads are explicit materialization work
Validation: TEST

Materialization should preserve model download intents even when `--models skip`
is used, but it should not download model bytes unless the caller chooses
`--models required` or `--models all`. Model download failures should fail
materialization when downloads were explicitly requested.

## Non-Goals

### CGMAT-NONGOAL-01 [LIVE]: Materialize does not launch ComfyUI
Validation: HUMAN_REVIEW

Materialization prepares an environment. It does not run ComfyUI, start
`cg serve`, bind network ports, or expose endpoints. Runtime launch belongs to
`cg run`, `cg serve`, container entrypoints, or deployment adapters.

### CGMAT-NONGOAL-02 [LIVE]: Materialize does not redefine readiness policy
Validation: MIXED

Materialization should consume core readiness, provenance, and dependency
criticality semantics. It should not introduce a separate build-only definition
of required models, optional nodes, source provenance, or portable manifest
validity.
