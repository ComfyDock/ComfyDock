# ComfyGit Core Contract

ComfyGit Core owns environment state, dependency metadata, local runtime
materialization, and library APIs used by the CLI, manager, deploy tooling, and
future cloud services.

## Library Boundary

### CGCORE-LIB-01 [LIVE]: Core stays UI-agnostic
Validation: STATIC

Core library code must not depend on a specific frontend, terminal UI, or ComfyUI
panel implementation. User interaction belongs behind callback protocols,
strategies, or callers in CLI/manager/deploy packages.

### CGCORE-LIB-02 [LIVE]: Core should avoid direct print/input interaction
Validation: STATIC

Core code should not use `print()` or `input()` for normal behavior. Callers own
rendering, prompting, progress display, and cancellation UX.

### CGCORE-LIB-03 [LIVE]: Workspace and Environment are the primary public API
Validation: MIXED

Callers should enter core behavior through Workspace and Environment APIs rather
than directly orchestrating manager internals. Manager classes may be used for
internal composition, tests, and advanced package-local behavior.

## Portable Environment Contract

### CGCORE-MAN-01 [LIVE]: Environment manifests are the portable source of truth
Validation: TEST

An environment repository's tracked `pyproject.toml` carries the portable recipe
for recreating the environment: ComfyUI/Python intent, Python dependencies,
custom nodes, workflows, workflow contracts, and model metadata.

### CGCORE-MAN-02 [LIVE]: Machine-local configuration is not committed as manifest truth
Validation: TEST

Machine-specific sync inputs such as PyTorch backend selection and local UV source
overrides belong in gitignored environment-local files, then get injected during
sync/run. They must not become required tracked manifest state.

### CGCORE-MAN-03 [PARTIAL]: Runtime directories are derived materialization
Validation: MIXED

The ComfyUI checkout, virtual environment, installed custom nodes, symlinks, and
model links are materialized from tracked manifest state plus machine-local
configuration. Sync/repair should be able to recreate them instead of treating
their current disk contents as authoritative.

### CGCORE-MAN-04 [LIVE]: Git commits are environment snapshots
Validation: TEST

Environment changes meant to be shared or used by cloud services should be
recorded in git. Core git operations should preserve the environment repository
as the auditable history of manifest and workflow changes.

## Dependency Reproducibility

### CGCORE-DEP-01 [LIVE]: Python package state is resolved through uv
Validation: TEST

ComfyGit-managed environments use uv to resolve and sync Python dependencies.
Manual package installs into the environment virtualenv are not durable unless
captured in manifest dependency state or machine-local injection config.

### CGCORE-DEP-02 [LIVE]: Models are external assets, not image/package payloads
Validation: MIXED

Model files are tracked by metadata such as filename, category, relative path,
hash, sources, and workflow references. The model bytes themselves stay external
to the Python package and environment manifest.

### CGCORE-DEP-03 [LIVE]: Model criticality affects reproducibility gates
Validation: TEST

Model references can be required, flexible, or optional. Required unresolved
models must be surfaced as blockers during export/import/build-readiness flows;
optional unresolved models may be treated as warnings.

### CGCORE-DEP-04 [PLANNED]: Custom node criticality is manifest-declared
Validation: MIXED

Custom nodes should support an explicit `criticality = "required" | "optional"`
field in manifest metadata. Missing criticality defaults to required. Required
nodes without a reproducible acquisition path block build readiness; optional
nodes warn instead.

### CGCORE-DEP-05 [PLANNED]: Workflow graph usage is advisory for custom node criticality
Validation: HUMAN_REVIEW

The presence or absence of custom node types in workflow JSON is not authoritative
proof that an installed custom node package is safe to omit. Side effects,
extensions, and runtime hooks mean user-declared criticality wins.

## Resolution And Sync

### CGCORE-SYNC-01 [LIVE]: Sync reconciles toward declared state
Validation: TEST

Sync should reconcile installed packages, custom nodes, workflows, models, and
derived configuration toward the manifest plus active local configuration instead
of only appending missing pieces.

### CGCORE-SYNC-02 [PARTIAL]: Readiness checks should fail before destructive or expensive work
Validation: MIXED

When core can detect missing required sources, unresolved dependencies, invalid
manifest state, or unavailable required models before a push/export/build-like
operation, it should report those issues before doing expensive or surprising
work.

### CGCORE-SYNC-03 [LIVE]: Development overrides are local by default
Validation: TEST

Editable local package and node paths are development conveniences. They should be
kept in local configuration unless explicitly converted into portable manifest
source metadata.
