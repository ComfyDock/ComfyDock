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

Resolver previews must model the same local sync inputs used by real
environment sync. That includes active overlays from `.overlay-config.toml`,
local overlays such as `overlays/.local.toml`, and machine-local PyTorch backend
selection from `.pytorch-backend`. These files are not portable manifest truth,
but they are part of the current machine's dependency solve and must be included
when answering "what would this install change here?".
The comparison baseline should be generated with those same active overlays
before the proposed node is added, so existing overlay-vs-lock drift is not
reported as part of the node install diff.

Apply must be guarded by the preview baseline. A preview result includes a
fingerprint of the current resolved package baseline, a fingerprint of the
normalized package diff, and a fingerprint of the proposed resolved package
state. Applying an accepted preview must re-run the preview against the current
environment state under the environment operation lock and abort if the accepted
fingerprints no longer match. If the preview itself cannot be generated without
package metadata/build work, callers should treat that as a separate preview
failure state rather than as an approved dependency change.

Current implementation status: core exposes the typed preview primitive,
fingerprinted preview results, and a guarded apply entry point on Environment
and NodeManager. Manager can present and apply reviewed node dependency changes.
CLI parity for reviewed dependency apply remains future work.

### CGSYNC-LIFE-07 [LIVE]: Sync normalizes ComfyGit-managed resolver tools
Validation: TEST

Before running uv sync, core should ensure the environment manifest expresses the
current ComfyGit-managed resolver policy. This includes keeping `uv` in the
`comfygit-system` dependency group at the current minimum and recording a
matching uv override so transitive dependencies cannot force the resolver below
the version needed for manifest features such as `exclude-dependencies`.

This normalization applies to create, sync, repair, run, materialization, and
node-install paths that reconcile the environment. In the current pre-customer
phase, an old checkout may therefore become dirty after reconciliation because
ComfyGit repaired stale system-tool metadata.

### CGSYNC-LIFE-08 [DEFERRED]: Historical toolchain migrations should become explicit
Validation: HUMAN_REVIEW

The current lifecycle intentionally repairs old ComfyGit-managed resolver
metadata during reconciliation. After environments become user-owned
compatibility artifacts, checkout and sync should grow a more explicit migration
mode: current ComfyGit may declare the runtime minimum it needs, while the
environment records the exact tool version it was last materialized with.
Reconciliation should then ask the caller to migrate or repair when those layers
conflict instead of silently changing historical commits.

### CGSYNC-LIFE-09 [LIVE]: Switch observer primitives are shared core lifecycle state
Validation: TEST

Core owns the restart-stable switch observer primitives that are shared by the
CLI supervisor and Manager integration. This includes the switch status schema,
switch log entry schema, metadata filenames, read/write helpers, observer
advertisement payload, and small HTTP observer server used to expose status and
recent logs outside the ComfyUI process being restarted.

Process-specific lifecycle authorities, such as `cg run` and the Manager
orchestrator, may still decide when to stop, sync, and restart ComfyUI. They
should not duplicate the status/log schema or observer server implementation.

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

Workflow contract readiness includes API prompt artifact availability. If a
manifest execution contract references `workflow_api/<name>.api.json`, handoff
readiness should verify that the file exists in `.cec/` before export, push, or
build/materialize planning succeeds.

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

### CGSYNC-READY-04 [LIVE]: Core readiness does not prove live import success
Validation: HUMAN_REVIEW

Core readiness is allowed to report whether custom nodes have portable
acquisition metadata, required versus optional criticality, and manifest-backed
handoff state. It must not report a custom node as imported or failed to import
inside the currently running ComfyUI process.

Live import health is process-local runtime evidence. Manager and serve
runtimes may layer that evidence into their own status surfaces, but they must
not treat it as a core sync input or rewrite manifest criticality from it.

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
