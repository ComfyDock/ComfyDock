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
in manifest dependencies or local overlay configuration.

### CGSYNC-LIFE-02A [PARTIAL]: Dry-run sync is a read-only planning path
Validation: TEST

Dry-run sync should build and return a reconciliation plan without mutating the
tracked manifest, local overlay configuration, virtual environment, custom-node
checkout directories, workflow copies, symlinks, completion markers, cache
state, or gitignore entries. Implementation may still share planning code with
real sync, but write-capable phases should be explicit and skipped unless the
caller requested apply mode.

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

### CGSYNC-LIFE-10 [LIVE]: Environment mutations are serialized by an environment-local operation lock
Validation: TEST

Mutating environment operations should run under the environment operation lock
so concurrent CLI, Manager, or runtime calls do not interleave writes to
manifest, lockfiles, node checkouts, workflow copies, symlinks, and git state.
The lock should cover sync, manager update, model/node/workflow mutations, git
handoff operations, import finalization where practical, and destructive
operations that reconcile runtime state.

### CGSYNC-LIFE-10A [PARTIAL]: Sync orchestration has explicit plan and apply phases
Validation: MIXED

Environment sync is implemented as a small public facade over a coordinator with
named apply phases. It should continue moving toward explicit plan/apply
separation across the phases: plan environment state, reconcile Python
dependencies, reconcile custom nodes, restore workflows, resolve or prepare
models, configure symlinks, and mark completion. Each phase should report
typed outcome data and make side effects explicit so import, pull/checkout,
repair, materialization, and run supervision can reuse the same lifecycle
without duplicating policy in `Environment`.

### CGSYNC-LIFE-11 [LIVE]: Incomplete environments are hidden and cleaned up
Validation: TEST

Create, import, and materialization should mark an environment complete only
after tracked source state and derived runtime state are sufficiently
initialized. Workspace listing should exclude environments without the
completion marker. Failure paths should attempt to remove incomplete
environment directories while preserving completed environments and explicit
user-data deletion semantics.

## Import

### CGSYNC-IMPORT-01 [LIVE]: Import is an authoring setup flow
Validation: MIXED

Normal import should prepare an editable local environment for a human user:
preserve git identity/remotes for git imports, initialize or restore tracked
source state for bundle and directory imports, restore workflows into ComfyUI,
install/register Manager unless headless mode is requested, and permit
import-specific commits and softer sync failure handling. Materialization remains
the runtime hydration flow with stricter defaults described in
`docs/specs/environment-materialization-lifecycle.md`.

## Custom Node Lifecycle

### CGSYNC-NODE-01 [LIVE]: Node install and update mutate manifest, filesystem, and uv as one lifecycle
Validation: TEST

Adding or updating a registry/git custom node should prepare lookup metadata,
cached source contents, requirement metadata, manifest changes, filesystem
changes, and uv sync as one guarded operation. On install/update failure, core
should restore the previous manifest state and best-effort restore the previous
materialized node directory.

### CGSYNC-NODE-02 [LIVE]: Core reviewed dependency apply is fingerprint-guarded
Validation: TEST

Applying a reviewed node dependency change must regenerate the preview under the
environment operation lock and verify the accepted baseline, diff, and proposed
fingerprints before mutating the environment. Stale accepted previews must fail
instead of applying to a changed environment.

### CGSYNC-NODE-03 [PARTIAL]: CLI reviewed dependency apply remains future work
Validation: HUMAN_REVIEW

Core and Manager support reviewed dependency apply. CLI may detect and display
dependency conflicts and dependency previews, but it does not yet expose the
same first-class reviewed apply flow.

### CGSYNC-NODE-04 [LIVE]: Optional dependency fallback does not rewrite portable intent
Validation: TEST

If a uv sync operation discovers that an optional dependency group fails on the
current machine, core should return typed outcome data describing the failed and
skipped groups. Retrying the current sync while excluding those groups is a
local operation choice. The portable dependency group remains in
`pyproject.toml` unless the user explicitly edits or removes that optional
dependency intent.

## Local Configuration And Overlays

### CGSYNC-LOCAL-01 [LIVE]: Overlay materialization is disposable local dependency configuration
Validation: TEST

Local, shared, stock, and PyTorch overlays may materialize dependencies,
sources, indexes, constraints, and uv settings only in disposable uv project
copies during uv resolution.
`overlays/.local.toml` and `.overlay-config.toml` are machine-local activation
state; shared non-local overlays may be portable source files.

Overlay application must never mutate the tracked manifest file for sync/run
resolution.

### CGSYNC-LOCAL-02 [LIVE]: Overlay collection order is deterministic and PyTorch wins last
Validation: TEST

Overlay collection should apply in deterministic order: local overlay first,
active overlays sorted canonically, CLI one-time overlays, then generated
PyTorch overlay. Platform-incompatible overlays should be skipped rather than
forcing invalid local dependency state.

### CGSYNC-LOCAL-03 [LIVE]: Operation commands do not persist PyTorch backend overrides
Validation: TEST

Create/import/materialize may auto-detect and save a backend in
`.pytorch-backend`. Runtime operation commands such as sync, run, and pull
should read or auto-probe the environment-local backend when no override is
given. A `--torch-backend` override on those commands is a one-time sync input
and should not rewrite the saved backend file.

### CGSYNC-LOCAL-04 [LIVE]: Overlay-aware uv resolution uses disposable project copies
Validation: TEST

Sync, run-preflight sync, pull reconciliation, materialization, and other
overlay-aware uv resolution paths should build a disposable project copy before
running uv with materialized local state. The disposable project should live under a
gitignored environment-local scratch directory such as `.cec/.comfygit-tmp/`,
and each new operation should remove stale transaction directories before
creating a fresh one.

The project copy should include the files uv needs to resolve consistently:
`pyproject.toml`, `.python-version`, `package_config.toml`, `.pytorch-backend`,
`.overlay-config.toml`, shared/local overlay files, and any existing `uv.lock`.
Overlays are applied only to the copied `pyproject.toml`. The tracked
environment manifest must not be modified by overlay application, even
temporarily.

The uv process may still target the real managed virtualenv by setting
`UV_PROJECT_ENVIRONMENT` to the environment's runtime venv while using the
disposable project directory as the uv project root. If uv writes a lockfile, core
may copy the resulting `uv.lock` back to `.cec/uv.lock` only because that lockfile
is machine-local runtime state. The temporary `pyproject.toml` must never be
copied back after sync/run.

Relative local path sources need explicit handling when copied into a temporary
project root. Core should either persist local source paths as absolute paths or
rewrite relative local paths in the disposable copy so the solve refers to the
same source location as the real environment.

### CGSYNC-LOCAL-05 [PLANNED]: Dependency mutation separates manifest edits from overlay-aware sync
Validation: TEST

Commands that intentionally mutate portable dependency intent, such as
`cg py add`, should write only the requested portable manifest change to the real
environment `pyproject.toml`. They should not apply local overlays or PyTorch
backend state directly to that tracked file.

After the portable manifest edit is recorded, the command should perform
resolution and installation through the same disposable overlay-aware uv project
used by sync. This makes dependency mutation respect local backend/source/index
policy while preserving the manifest boundary between portable intent and
machine-local solve inputs.

For simple additive dependency writes, core may use uv in a manifest-only mode
such as `uv add --frozen` when supported, then run normal overlay-aware sync.
Operations that cannot be represented as a manifest-only uv edit should use an
equivalent core-owned manifest mutation plus overlay-aware sync, rather than
mutating the tracked manifest with local overlay state.

## Workflow Resolution

### CGSYNC-WF-01 [LIVE]: Workflow resolution writeback is owned by one manifest reconciler
Validation: TEST

Workflow resolution may discover custom-node package mappings, built-in node
usage, model dependencies, manual model dependencies, download intents,
criticality, and path/category fixes. The conversion from a resolution result to
portable manifest edits should be owned by one core reconciler so criticality,
manual dependency preservation, source/download intent persistence, and node
package writeback cannot drift across multiple call sites. Workflow JSON path
rewriting, cache invalidation, and pending download execution are separate side
effects that should remain outside the manifest reconciler.

### CGSYNC-WF-02 [LIVE]: Workflow caches are invalidated by semantic analysis and resolution inputs
Validation: TEST

Workflow dependency and resolution caches may use file metadata as fast lookup
keys, but cache correctness must be based on the semantic inputs that affect
parsing and resolution. Workflow dependency analysis must be invalidated when the
workflow file content changes or when local derived ComfyUI metadata that affects
parsing changes, including built-in node inventory, folder path mappings, and
generated model-loader metadata.

Workflow resolution may reuse cached dependency analysis only when the analysis
inputs are still valid. Resolution must be recomputed when manifest workflow
model/node data, model index candidates, registry node mappings, package aliases,
or resolver policy versions change. Refreshing local ComfyUI metadata must
invalidate cached workflow analysis/resolution and refresh resolver state that
was constructed from that metadata.

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

### CGSYNC-GIT-04 [LIVE]: Git handoff operations reconcile node, package, and workflow state after tree changes
Validation: TEST

Checkout, hard reset, branch switch, merge, revert, and pull should reconcile
derived environment state after changing tracked `.cec` state. Reconciliation
should reset manifest readers, reconcile custom-node filesystem state, sync uv
with local PyTorch/overlay materialization, and restore tracked workflows into ComfyUI.
Branch switch may preserve uncommitted workflow edits only when the target branch
does not overwrite them.

## Run Supervision

### CGSYNC-RUN-01 [LIVE]: `cg run` supervises sync, restart, and environment switch lifecycle
Validation: MIXED

`cg run` should sync before launching ComfyUI unless explicitly bypassed,
forward ComfyUI arguments, set ComfyGit runtime environment variables, and honor
well-known child exit codes for restart and environment switch. Restart should
force a fresh sync before relaunch. Environment switch should consume the target
request, sync the target environment, start target ComfyUI, and update shared
switch status/logs.

### CGSYNC-RUN-02 [LIVE]: Environment switch completion requires ComfyUI HTTP readiness
Validation: TEST

During supervisor-managed environment switching, the observer must not report
`complete` merely because the target process was started. It should move through
startup/validation states and only publish `complete` after the target ComfyUI
HTTP endpoint responds, mapping wildcard listen addresses to a local readiness
probe host.

## Readiness And Handoff

### CGSYNC-READY-01 [PARTIAL]: Core exposes UI-agnostic readiness results
Validation: MIXED

Core should provide structured readiness results that callers can use for
export, push, build planning, and future deploy gates. These results should
separate hard source-state blockers from reproducibility warnings and should not
contain CLI, manager, or Cloud presentation decisions.

Core now exposes the local handoff readiness result used by Manager export,
Manager push preview, and CLI export flows. Core also exposes a build-readiness
projection that consumes the same typed manifest snapshot and produces dependency
proof items for build/runtime planners. This remains partial until runtime
readiness and source-candidate repair consume the same result family.

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
by Manager and CLI handoff flows. Build-readiness dependency proof now consumes
these manifest semantics for custom-node criticality and source availability.
Source candidate discovery is still planned.

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

### CGSYNC-READY-05 [LIVE]: Handoff readiness blocks invalid or missing workflow API prompt artifacts
Validation: TEST

If a workflow execution contract references a `workflow_api/*.api.json` artifact,
export and push-readiness flows must treat missing or invalid artifact paths as
handoff blockers. Relative artifact paths must resolve inside the manifest
directory; absolute paths or path traversal should be invalid.

## Build Compatibility

### CGSYNC-BUILD-01 [PARTIAL]: Build readiness uses the same manifest semantics as local sync
Validation: MIXED

Build planning should read the same manifest fields core writes locally. If a
runtime needs a field for reproducibility, core/manager should make that field
first-class rather than relying on adapter-specific heuristics.

Core now exposes build-readiness helpers that classify Python dependencies,
custom node package provenance and criticality, workflow model source/cache
availability, and workflow contract summaries from `EnvironmentManifestSnapshot`
or parsed `pyproject.toml`. Cloud and runtime adapters may add target class,
base runtime, source validation policy, asset catalog state, persistence, and
deployment orchestration around that proof, but should not fork the
manifest-derived dependency semantics.

Materialization is the local/headless hydration step that build and runtime
adapters can call before running smoke tests or serve endpoints. It should not
create a second dependency policy; it should consume the same manifest and
readiness semantics described here.

### CGSYNC-BUILD-02 [PARTIAL]: Source metadata should be inspectable before push
Validation: MIXED

Users should be able to see and fix missing required model/node source metadata
before pushing a commit that another runtime cannot build. Manager has a first-pass
readiness surface for export/push handoff backed by a core readiness service;
build planners can now consume core build-readiness proofs. Source-candidate
repair UI remains follow-on work.
