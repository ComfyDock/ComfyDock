# Environment Manifest Model

This spec describes the tracked environment data shape that core, manager, CLI,
deploy, and serve/runtime adapters should agree on.

## Manifest Authority

### CGSPEC-MAN-01 [LIVE]: `pyproject.toml` is the tracked manifest file
Validation: TEST

ComfyGit environment repositories store the portable manifest in `pyproject.toml`.
Core may use helper files and databases for cache/runtime state, but portable
environment intent belongs in the manifest.

### CGSPEC-MAN-02 [LIVE]: `[tool.comfygit]` owns ComfyGit-specific metadata
Validation: TEST

ComfyGit-specific environment metadata belongs under `[tool.comfygit]` tables.
Standard Python project metadata and dependency groups should continue to use
standard `pyproject.toml` locations where possible.

### CGSPEC-MAN-03 [LIVE]: Workflows are named manifest entries
Validation: TEST

Tracked workflows should have stable names in the manifest and should reference
their required node packages, model metadata, and execution contract metadata
where available.

### CGSPEC-MAN-04 [PARTIAL]: Workflow contracts are deployable API metadata
Validation: MIXED

Workflow input/output contracts should be stored in tracked environment state so
future build/deploy systems can expose a stable execution API for a workflow at a
specific commit.

### CGSPEC-MAN-05 [PLANNED]: Workflow contracts should be executable without Manager
Validation: MIXED

Workflow execution contracts are portable environment metadata, not ComfyGit
Manager UI state. A ComfyGit environment created or maintained by CLI alone
should still be able to serve contract-shaped workflow requests when the runtime
has the workflow JSON, manifest contract, and a reachable ComfyUI server.

### CGSPEC-MAN-06 [PLANNED]: API workflow prompts are not manifest truth
Validation: MIXED

Environment repositories should not need to track ComfyUI API-format prompt JSON
beside the UI-format workflow JSON. The UI workflow remains the editable,
reviewable, user-authored artifact; the API prompt is generated from it when a
runtime needs to submit work to ComfyUI's `/prompt` endpoint. If tooling stores
an API prompt for debugging, caching, or validation, that artifact must be
treated as derived and replaceable rather than authoritative manifest state.

### CGSPEC-MAN-07 [LIVE]: Workflow contract numeric metadata must remain TOML-safe
Validation: TEST

Workflow contract inputs may mirror ComfyUI widget metadata whose numeric values
exceed TOML's signed 64-bit integer range, especially unsigned seed bounds. Core
must serialize out-of-range integers as strings in `pyproject.toml` and convert
them back to numeric values when loading typed workflow contract models. This
keeps the manifest parseable by strict TOML readers without losing numeric
precision for runtime and UI consumers.

### CGSPEC-MAN-08 [LIVE]: Core exposes a typed read-only manifest snapshot
Validation: TEST

Core should expose a typed read-only projection of the current manifest that is
derived from the same freshness-aware `pyproject.toml` load path as existing
handlers. The snapshot is a consumer-facing read model for services such as
readiness, build planning, and serve/runtime adapters. It must not replace the
`pyproject.toml` file as the persisted authority, and callers should request a
new snapshot after manifest mutations.

## Custom Nodes

### CGSPEC-NODE-01 [LIVE]: Installed node packages are manifest-visible
Validation: TEST

Custom node packages that are part of the portable environment should appear in
manifest node metadata with enough identity to install or inspect them.

### CGSPEC-NODE-02 [LIVE]: Registry, Git URL, and local development nodes are distinct cases
Validation: MIXED

Core should preserve whether a node came from a registry entry, a Git/source URL,
or a local development path. Local development paths are not portable by
themselves.

### CGSPEC-NODE-03 [LIVE]: Node criticality defaults to required
Validation: TEST

When a custom node manifest entry omits criticality, readers should treat it as
`required`. This keeps existing manifests conservative while allowing users to
mark intentionally non-deployable or experimental nodes as `optional`.

### CGSPEC-NODE-04 [PARTIAL]: Optional nodes may remain installed locally without blocking builds
Validation: MIXED

An optional custom node can be present in a local authoring environment without
being required for build readiness. The manifest should still make this intent
explicit so build planners do not have to infer it from workflow JSON. Workflow
graph analysis must not set this field automatically. Core and manager can now
persist this intent; centralized core readiness and build planner consumption are
still in progress.

## Models

### CGSPEC-MODEL-01 [LIVE]: Models use content-oriented metadata
Validation: TEST

Model metadata should include enough information to identify the file, expected
location, category, source URLs when known, and content hash when available.

### CGSPEC-MODEL-02 [LIVE]: Required models without source proof are blockers
Validation: TEST

A required model that lacks a usable source and cannot be matched by known hash
is not reproducible. Export, import, push-readiness, or build-readiness
flows should surface that as a blocking issue.

### CGSPEC-MODEL-03 [LIVE]: Optional model gaps are warnings
Validation: TEST

Optional models may be unresolved without blocking every operation. Callers should
still surface the missing metadata clearly so the user understands the environment
may behave differently.

## Local Configuration

### CGSPEC-LOCAL-01 [LIVE]: PyTorch backend selection is machine-local
Validation: TEST

The selected PyTorch backend and exact wheel pins are stored in local environment
configuration and injected during sync/run. They are not portable manifest truth.

### CGSPEC-LOCAL-02 [LIVE]: Local UV sources are machine-local
Validation: TEST

Local editable source paths and private local indexes belong in gitignored local
configuration. They should be injected into uv resolution when active, but not
committed as the portable environment recipe.
