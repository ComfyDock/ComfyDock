# Environment Manifest Model

This spec describes the tracked environment data shape that core, manager, CLI,
deploy, and ComfyGit Cloud should agree on.

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

### CGSPEC-NODE-03 [PLANNED]: Node criticality defaults to required
Validation: TEST

When a custom node manifest entry omits criticality, readers should treat it as
`required`. This keeps existing manifests conservative while allowing users to
mark intentionally non-deployable or experimental nodes as `optional`.

### CGSPEC-NODE-04 [PLANNED]: Optional nodes may remain installed locally without blocking builds
Validation: MIXED

An optional custom node can be present in a local authoring environment without
being required for cloud build readiness. The manifest should still make this
intent explicit so cloud planners do not have to infer it from workflow JSON.

## Models

### CGSPEC-MODEL-01 [LIVE]: Models use content-oriented metadata
Validation: TEST

Model metadata should include enough information to identify the file, expected
location, category, source URLs when known, and content hash when available.

### CGSPEC-MODEL-02 [LIVE]: Required models without source proof are blockers
Validation: TEST

A required model that lacks a usable source and cannot be matched by known hash
is not reproducible. Export, import, push-readiness, or cloud-build readiness
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
