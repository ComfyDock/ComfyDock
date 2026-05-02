# Environment Sync Lifecycle

This spec describes how ComfyGit turns an environment manifest into a runnable
local ComfyUI environment.

## Lifecycle

### CGSYNC-LIFE-01 [LIVE]: Create initializes tracked and derived state
Validation: TEST

Creating an environment should initialize the tracked manifest repository and the
derived `.cec` runtime state needed for sync/run.

### CGSYNC-LIFE-02 [LIVE]: Sync may recreate the virtual environment
Validation: TEST

Sync is allowed to recreate or replace the managed virtual environment. Users
should not rely on manually installed packages surviving unless they are captured
in manifest dependencies or local injection configuration.

### CGSYNC-LIFE-03 [LIVE]: Run syncs unless explicitly bypassed
Validation: TEST

Normal run behavior should make the environment runnable from declared state
before launching ComfyUI. Explicit no-sync flows are advanced escape hatches and
should not redefine the main lifecycle.

### CGSYNC-LIFE-04 [PARTIAL]: Repair restores derived state from truth
Validation: MIXED

Repair should use the manifest, lockfile, and local configuration to restore
missing or damaged derived runtime state. Gaps should be tracked as implementation
work, not treated as new truth.

### CGSYNC-LIFE-05 [PLANNED]: Materialize hydrates runtime state without authoring UX
Validation: MIXED

Headless runtime hydration belongs to the materialization lifecycle, not to
interactive import behavior. `cg materialize` should reuse sync/import internals
where practical, but it should use non-interactive defaults, explicit workspace
selection, strict sync failure handling, and no authoring commit by default.
See `docs/specs/environment-materialization-lifecycle.md`.

### CGSYNC-LIFE-06 [PARTIAL]: Risky dependency changes are previewed before apply
Validation: MIXED

When adding a node would require changing already-resolved shared Python
packages, ComfyGit should not silently mutate the current environment. Core
provides a UI-agnostic resolver preview that simulates adding the node to a
temporary project copy, re-locks that project, and reports the package diff
before the real manifest, lockfile, or virtual environment are changed.

The preview should report added, removed, upgraded, downgraded, and otherwise
changed packages in a typed shape that Manager, CLI, and automation can present
consistently. This preview is different from the existing dependency probe: the
probe may infer constraints from a temporary venv install, while the resolver
preview should model the full manifest/lockfile result that would be applied.

Callers may then offer explicit actions such as cancelling, applying the
resolved dependency changes to the current environment, or trying the change on
a new branch. A blind force install that bypasses this preview remains an
advanced escape hatch, not the default dependency policy.

Dependency review is exceptional. Normal additive installs should proceed
without review. A review should be requested when install preflight detects that
the node would materially change already-resolved shared packages, especially
downgrades, protected package changes, or constraint conflicts. Build/toolchain
failures such as packages that cannot compile in the current environment should
remain normal install failures with logs unless a resolver preview can produce a
meaningful lockfile diff.

Preview generation should be lazy and fresh. UI surfaces may mark a package as
`dependency_review_required` during an install attempt, but they should not show
or apply a package diff while any environment-mutating node install is active.
Once the install queue is idle, clicking review should run the core preview
against the current manifest and lockfile state.

Apply must be guarded by the preview baseline. A preview result should include
hashes for the manifest and lockfile state it was generated from, plus a stable
fingerprint of the normalized package diff. Applying an accepted preview should
abort if the current hashes differ from the preview baseline, and the final
applied dependency diff should match the accepted fingerprint. If the preview
itself cannot be generated without package metadata/build work, callers should
treat that as a separate preview failure state rather than as an approved
dependency change.

Current implementation status: core exposes the typed preview primitive and
environment/node-manager entry points. Manager and CLI apply flows still need to
present the preview and require explicit user confirmation before applying risky
resolver changes.

## Git And Remote Flows

### CGSYNC-GIT-01 [LIVE]: Commit records environment truth changes
Validation: TEST

Committing should capture meaningful manifest, workflow, contract, and metadata
changes in the environment repository.

### CGSYNC-GIT-02 [PARTIAL]: Push-readiness should report reproducibility blockers
Validation: MIXED

Before pushing an environment intended for another runtime, ComfyGit should be
able to report obvious blockers such as required models without sources or
required node packages without portable acquisition metadata.

### CGSYNC-GIT-03 [LIVE]: Pull/checkout should be followed by reconciliation
Validation: TEST

When git operations change tracked environment state, sync/repair should reconcile
the derived runtime so the local environment matches the checked-out commit.

## Readiness And Handoff

### CGSYNC-READY-01 [PARTIAL]: Core exposes a UI-agnostic readiness result
Validation: MIXED

Core should provide a structured readiness result that callers can use for
export, push, build planning, and future deploy gates. The result should
separate hard source-state blockers from reproducibility warnings and should not
contain CLI or manager presentation decisions.

Core now exposes the local handoff readiness result used by Manager export,
Manager push preview, and CLI export flows. This remains partial until workflow
contract readiness, runtime readiness, and build-plan readiness consume
the same shape.

### CGSYNC-READY-02 [PARTIAL]: Readiness uses core provenance semantics
Validation: MIXED

Readiness checks should classify model source gaps, custom node portable
provenance gaps, and dependency criticality through core services. Manager, CLI,
deploy, and runtime adapter code should not reimplement divergent rules for the same
manifest state.

Core now owns the current model-source and custom-node provenance semantics used
by Manager and CLI handoff flows. Source candidate discovery and
dependency-proof integration are still planned.

### CGSYNC-READY-03 [PLANNED]: Source candidate discovery supports readiness repair
Validation: MIXED

Core should expose reusable services for finding likely model source candidates
from workflow metadata and saved workflow text. Callers may present those
candidates differently, but scoring, deduplication, provider classification, and
already-known-source filtering should remain shared.

Manager currently owns the first source-candidate UI implementation. Extract it
when build/dependency proof needs the same candidate discovery behavior.

## Build Compatibility

### CGSYNC-BUILD-01 [PLANNED]: Build readiness uses the same manifest semantics as local sync
Validation: MIXED

Build planning should read the same manifest fields core writes locally. If a
runtime needs a field for reproducibility, core/manager should make that field
first-class rather than relying on adapter-specific heuristics.

Materialization is the local/headless hydration step that build and runtime
adapters can call before running smoke tests or serve endpoints. It should not
create a second dependency policy; it should consume the same manifest and
readiness semantics described here.

### CGSYNC-BUILD-02 [PARTIAL]: Source metadata should be inspectable before push
Validation: MIXED

Users should be able to see and fix missing required model/node source metadata
before pushing a commit that another runtime cannot build. Manager has a first-pass
readiness surface for export/push handoff backed by a core readiness service;
build planner integration is still planned.
