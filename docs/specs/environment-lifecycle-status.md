# Environment Lifecycle Status And Action Matrix

This spec defines the target status model for helping users understand what is
healthy, what is drifting, and what action should happen next in a managed
ComfyGit environment.

The current implementation already produces many useful signals in core, CLI,
and Manager, but action selection is scattered across status rendering, repair,
workflow resolve, readiness checks, commit flows, node UI, and runtime restart
flows. This file is the reference matrix for consolidating those signals into a
single composed lifecycle status in the future.

## Implementation Dossier

### CGLIFE-PLAN-01 [PARTIAL]: Lifecycle status work proceeds as staged, test-gated refactor
Validation: MIXED

The lifecycle status implementation should be split into small, reversible
slices that preserve existing status behavior while introducing the new typed
surface:

1. Define public lifecycle model types and stable action/issue identifiers.
2. Add a pure decision service with matrix-style unit tests over synthetic
   inputs.
3. Add an `Environment.get_lifecycle_status()` facade that composes existing
   core signals without changing `Environment.status()` semantics.
4. Add core integration tests that prove real environment drift produces the
   expected lifecycle issues and actions.
5. Migrate CLI status guidance to render lifecycle actions while keeping
   command behavior unchanged.
6. Expose lifecycle status through Manager backend/API surfaces so Manager UI
   can stop recreating the same priority rules.
7. Migrate Manager UI terminology and call-to-action rendering to the lifecycle
   action IDs in this spec.

Each slice should run the focused tests for the touched layer before moving to
the next slice. Broader CLI smoke validation should run once the CLI consumes
the lifecycle status facade.

### CGLIFE-PLAN-02 [PARTIAL]: Tests should lock behavior at the cheapest reliable layer
Validation: TEST

Lifecycle status coverage should prefer a layered test pyramid:

- Decision matrix unit tests for action priority, issue severity, blocking
  state, destructive flags, restart requirements, and disabled reasons.
- Core integration signal tests for real manifest/filesystem/workflow/git states
  such as missing declared nodes, untracked node folders, disabled nodes,
  unresolved workflow packages, missing models, detached HEAD, and uncommitted
  manifest changes.
- Adapter serialization/rendering tests that prove CLI and Manager preserve
  action IDs and layer labels without parsing display strings.
- CLI smoke tests for the main user flow after adapter wiring changes.

Do not make every matrix row a full end-to-end environment test. Registry,
runtime, provider, download, and browser-dependent states may use fakes or
adapter-provided runtime inputs when the core decision behavior is already
covered by unit tests.

### CGLIFE-PLAN-03 [PARTIAL]: Adapter wiring is additive before replacement
Validation: MIXED

CLI and Manager should first consume lifecycle status as an additive typed
surface. Existing status, readiness, node, workflow, and runtime endpoints may
remain during migration, but duplicated adapter-side priority rules should be
removed once equivalent lifecycle actions are available.

The migration should keep these boundaries:

- Core owns manifest/filesystem/snapshot/workspace-index decision policy.
- Manager supplies runtime and active-operation state that core cannot know
  from disk alone.
- CLI and Manager own labels, layout, confirmation UI, logs, and command
  execution.
- Adapters use lifecycle action IDs and issue IDs, not parsed prose, to select
  UI affordances.

### CGLIFE-PLAN-04 [LIVE]: Lifecycle refactoring must not widen the public API accidentally
Validation: STATIC

The lifecycle status surface should be exported through deliberate public
modules such as `comfygit_core.models` and `Environment.get_lifecycle_status()`.
New helper scanners, context builders, and decision internals should remain
private unless they are intentionally documented as adapter-facing APIs.

This keeps the public contract centered on typed results and the
`Workspace`/`Environment` facades while still allowing internal implementation
modules to change.

## Layer Model

### CGLIFE-STATUS-01 [PARTIAL]: Lifecycle status separates environment layers
Validation: MIXED

ComfyGit should distinguish these layers when reporting environment health and
recommended actions:

- `manifest`: desired portable state declared by the tracked environment
  repository, especially `pyproject.toml`, tracked workflows, workflow API
  prompt artifacts, and manifest model/node metadata.
- `filesystem`: materialized local state on disk, including custom-node
  directories, workflow files inside ComfyUI, model files or symlinks, and the
  managed virtual environment.
- `runtime`: the currently running ComfyUI process state, including whether it
  has loaded installed custom nodes, whether imports failed, whether ComfyUI is
  ready, and whether restart is required.
- `snapshot`: Git handoff state for the environment repository: branch, detached
  HEAD, uncommitted changes, commit safety, push/export readiness, and portable
  provenance warnings.
- `workspace_index`: workspace-local derived state such as model index records,
  model source hints, registry cache, and generated ComfyUI model-loader
  metadata.
- `operation`: current or recent mutation state such as sync, repair, node
  install, workflow resolve, model download, import, switch, restart, and commit.

A user-facing status surface should not collapse these layers into one generic
state such as "not synced" when the underlying problem is known.

## Current Signal Inventory

### CGLIFE-STATUS-02 [PARTIAL]: Current core status signals are useful but not composed
Validation: LLM_REVIEW

Current core producers include:

| Producer | Current signals | Layer coverage | Gap |
| --- | --- | --- | --- |
| `Environment.status()` in `packages/core/src/comfygit_core/core/environment.py` | `EnvironmentStatus` with comparison, git, workflow, missing models | manifest, filesystem, snapshot, workspace_index | No runtime state or prioritized action model |
| `StatusScanner` in `packages/core/src/comfygit_core/analyzers/status_scanner.py` | missing nodes, extra nodes, disabled nodes, version mismatches, missing/untracked dev nodes, potential dev rename, targeted package sync checks | manifest vs filesystem custom nodes and uv materialization | Runtime restart state is still outside this scanner |
| `GitManager.get_status()` and git change parsing | branch, detached state, uncommitted changes, node/dependency/workflow/config changes | snapshot | Manifest dirty is inferred from Git status, not represented separately |
| `WorkflowManager.get_workflow_status()` and workflow analysis | workflow file sync, unresolved nodes/models, uninstalled packages, path sync, category mismatch, download intents, commit safety | manifest, filesystem, workspace_index | Workflow health is not ordered with node/filesystem/runtime health |
| `EnvironmentModelManager.get_missing_models()` | missing model entries with workflow references, criticality, download availability | manifest vs workspace_index/filesystem | Model index and manifest source proof are separate surfaces |
| `Environment.get_readiness()` | export/handoff blockers and reproducibility warnings | snapshot, manifest | Not a local runtime/materialization health check |
| `BuildReadinessService` | build dependency proof and blockers | manifest, snapshot | Ignores local filesystem/runtime drift by design |
| `Environment.sync()` result | package groups installed/skipped/failed, model downloads, errors | operation result | Post-action outcome, not preflight lifecycle status |
| `switch_observer` and `comfyui_readiness` | switch/restart/readiness progress and logs | runtime, operation | Not included in `Environment.status()` |

Current CLI and Manager adapters render additional action logic from these
signals. That action logic should eventually move into a typed composed status
or a shared decision service so adapters can render consistent guidance.

## Target Object Shape

### CGLIFE-STATUS-03 [PARTIAL]: Core exposes a typed composed lifecycle status
Validation: STATIC

Core should expose a typed, serializable composed status, tentatively named
`EnvironmentLifecycleStatus`, that can be consumed by CLI, Manager, Cloud, and
future adapters.

The status should include:

- environment identity: workspace path, environment name, current branch/ref,
  detached HEAD state, current commit, and runtime authority where known.
- layer summaries: `manifest`, `filesystem`, `runtime`, `snapshot`,
  `workspace_index`, and `operation`.
- issues: typed issue records with stable IDs, severity, layer, affected
  resources, blocking/non-blocking classification, and source signal.
- actions: typed action records with stable IDs, label, description, target
  layer, expected mutation domains, destructive/restart-required flags, enabled
  state, disabled reason, and confirmation requirements.
- raw source pointers: enough references to the original status/readiness/sync
  data for adapters to open detail views without reparsing messages.

Adapters may translate labels and layout, but they should not independently
recreate core lifecycle priority rules for common environment states.

### CGLIFE-STATUS-04 [PLANNED]: Mutation results report changed layers
Validation: STATIC

Mutating operations should report which layers they changed or require the user
to refresh. A node install, for example, may change manifest, filesystem, venv
packages, and runtime restart requirements. A workflow resolve may change
workflow metadata, model intent, custom-node mappings, downloads, and commit
safety.

Operation result models should therefore include layer delta fields such as:

- `manifest_changes`
- `filesystem_changes`
- `runtime_changes`
- `snapshot_changes`
- `workspace_index_changes`
- `restart_required`
- `status_refresh_required`

This keeps action results aligned with the lifecycle status instead of relying
on ambiguous phrases such as "applied", "installed", or "repaired".

## Decision Priority

### CGLIFE-STATUS-05 [PARTIAL]: Recommended actions use a stable priority order
Validation: HUMAN_REVIEW

When multiple states are present, the primary action should prefer the next step
that gets the user closer to a runnable and reproducible environment. The
initial priority order should be:

1. Setup state: create/open/import/switch into a managed environment before
   showing environment reconciliation actions.
2. Active operation state: wait, view logs, retry, or cancel if a sync/install/
   switch/restart/import is already running or recently failed.
3. Dangerous snapshot state: detached HEAD or conflicting uncommitted changes
   that make commit/pull/switch unsafe.
4. Materialization blockers: missing required nodes, failed dependency sync,
   missing required model files, model path/category problems, and workflow
   dependencies that prevent workflows from running.
5. Filesystem drift: extra/untracked nodes, disabled nodes, version mismatches,
   missing development-node checkouts, and potential dev-node renames.
6. Runtime blockers: restart required, ComfyUI not ready, or runtime custom-node
   import failures after materialization appears correct.
7. Reproducibility warnings: missing source/provenance for required or optional
   models/nodes and export/build-readiness warnings.
8. Snapshot actions: commit, push, export, or deploy after materialization and
   runtime health are acceptable.

Adapters may expose secondary actions at the same time, but the primary CTA
should not promote commit/export/deploy while required materialization or
runtime blockers remain unresolved.

### CGLIFE-STATUS-05A [LIVE]: Dependency diffs trigger materialization checks before commit
Validation: TEST

Normal status should avoid a full uv dry-run so high-frequency status rendering
stays responsive. When Git diff parsing detects dependency-group or uv
constraint changes in the manifest, lifecycle status must run a targeted uv
dry-run package sync check before choosing the primary action.

If uv reports that it would install, uninstall, update, downgrade, download, or
rewrite the lockfile, lifecycle status should surface
`dependencies_not_synced` and prefer `sync_environment` before
`commit_snapshot`. This prevents a node install that mutates dependency groups
from looking ready to commit while the virtual environment still lacks those
packages.

Validation coverage:

- `packages/core/tests/integration/test_lifecycle_status.py::test_lifecycle_status_recommends_sync_before_commit_for_dependency_changes`
- `packages/core/tests/unit/analyzers/test_status_scanner.py`
- `packages/core/tests/unit/managers/test_pytorch_overlay_materialization.py::test_overlay_dry_run_reports_stderr_without_copying_lock`
- `packages/cli/tests/test_status_suggestions.py::test_status_command_suggests_sync_for_package_drift`

## Action Matrix

### CGLIFE-STATUS-06 [PARTIAL]: Manifest and filesystem node drift has explicit actions
Validation: MIXED

| Scenario | Current signal source | Primary action | Secondary actions | Notes |
| --- | --- | --- | --- | --- |
| Manifest declares registry/git node; filesystem is missing it | `comparison.missing_nodes` | `sync_missing_nodes` / "Sync missing nodes" | open node details, remove from manifest if stale | If source/provenance is absent, action should become "Add source info" or "Remove from manifest" rather than blind sync. |
| Manifest declares development node; filesystem checkout is missing | `comparison.dev_nodes_missing` | `restore_or_relink_dev_node` / "Relink development node" | clone from git provenance if available, remove from manifest | Development local paths are not portable. Missing dev nodes are informational today but should still be visible. |
| Filesystem contains untracked non-git node folder | `comparison.extra_nodes` | `review_untracked_node` / "Review untracked node" | track as development node, remove from disk | The system should not silently delete or track this without confirmation. |
| Filesystem contains untracked git checkout | `comparison.dev_nodes_untracked` | `track_dev_node` / "Track development node" | remove from disk, ignore locally | Git checkout suggests intentional dev work; tracking should capture remote/branch/commit when possible. |
| Manifest and filesystem both contain node but version/commit differs | `comparison.version_mismatches` | `sync_node_version` / "Restore declared node version" | update manifest to current version, inspect diff | The primary action depends on whether manifest or filesystem is treated as desired state. Default should preserve manifest truth. |
| Node exists but is disabled on disk | `comparison.disabled_nodes` | `enable_or_remove_disabled_node` / "Review disabled node" | enable, remove, untrack | Disabled nodes are informational today but can explain runtime missing-node behavior. |
| Missing and extra dev/git nodes suggest rename | `comparison.potential_dev_rename` | `review_dev_node_rename` / "Review possible rename" | relink, track new checkout, remove stale manifest entry | Avoid treating this as independent missing plus extra drift without context. |

### CGLIFE-STATUS-07 [PARTIAL]: Workflow and model states have explicit actions
Validation: MIXED

| Scenario | Current signal source | Primary action | Secondary actions | Notes |
| --- | --- | --- | --- | --- |
| Workflow is new/modified/deleted in ComfyUI working files | workflow sync status | `review_workflow_changes` / "Review workflow changes" | commit once healthy, discard/restore | Workflow file changes are not the same as environment materialization drift. |
| Workflow has unresolved custom-node packages | workflow analysis | `resolve_workflow_nodes` / "Resolve workflow packages" | install package, mark optional, map manually | This may mutate manifest and then require sync/restart. |
| Workflow has uninstalled packages that are already tracked | workflow analysis `uninstalled_nodes` | `sync_missing_nodes` / "Install tracked packages" | inspect package list | This is materialization drift, not unknown workflow resolution. |
| Workflow has version-gated built-in nodes | workflow analysis `nodes_version_gated` | `upgrade_comfyui_or_change_workflow` / "Update ComfyUI or workflow" | show minimum version guidance | This should not be presented as a normal custom-node install. |
| Workflow has uninstallable/community-only mappings | workflow analysis `nodes_uninstallable` | `manual_node_resolution` / "Choose a community package" | mark optional, custom map | Current Manager wording maps this to "community packages". |
| Workflow has missing required model with known source | missing models and workflow analysis | `download_required_models` / "Download required models" | mark optional/flexible, add local model | Download mutates filesystem and workspace index, then manifest model entries. |
| Workflow has missing model without source | missing models/readiness | `add_model_source_or_select_local` / "Add model source or select local model" | mark optional/flexible, remove workflow dependency | Source proof and local availability are separate. |
| Workflow model path differs from indexed path | workflow analysis path sync | `sync_model_paths` / "Sync model paths" | inspect model location | Current CLI already prioritizes path sync before other workflow issues. |
| Model exists but category/folder is incompatible with loader | workflow analysis category mismatch | `move_or_redownload_model` / "Move model to expected folder" | adjust workflow, add compatible model | This is usually manual filesystem work, not a manifest-only repair. |
| Download intents are queued or failed | workflow analysis/download state | `complete_model_downloads` / "Complete downloads" | retry failed, edit source | Failed downloads should not be hidden behind "resolution complete". |

### CGLIFE-STATUS-08 [PARTIAL]: Runtime states are separate from manifest and filesystem states
Validation: MIXED

| Scenario | Current signal source | Primary action | Secondary actions | Notes |
| --- | --- | --- | --- | --- |
| Node install/update/remove completed while ComfyUI is running | operation result or Manager queue | `restart_comfyui` / "Restart ComfyUI to load changes" | continue editing, view logs | Do not label this "Apply Changes" unless apply means restart in context. |
| Runtime custom-node import failure after restart | Manager runtime import report today | `view_import_error` / "View import error" | run sync/repair, reinstall node, open logs | This is runtime health and should not block commit/export/source-state actions by itself. |
| ComfyUI process is not reachable | runtime readiness probe | `start_or_restart_comfyui` / "Start ComfyUI" | view supervisor logs | Endpoint readiness is runtime state, not manifest state. |
| Environment switch/restart is in progress | switch observer/operation state | `wait_or_view_logs` / "View progress" | cancel if supported | Avoid showing commit/sync/deploy as the primary CTA during active switching. |
| Runtime is stale relative to materialized state | operation result or runtime generation marker future | `restart_comfyui` / "Restart ComfyUI" | show changed resources | Current implementation has restart-required flags in some operation flows only. |

### CGLIFE-STATUS-09 [PARTIAL]: Snapshot and reproducibility states are separate from local health
Validation: MIXED

| Scenario | Current signal source | Primary action | Secondary actions | Notes |
| --- | --- | --- | --- | --- |
| Environment has uncommitted manifest/workflow/config changes and no blockers | `git.has_changes`, workflow sync status, commit safety | `commit_snapshot` / "Commit snapshot" | inspect diff, discard changes | Commit should be primary only after materialization/runtime blockers are acceptable. |
| Detached HEAD | `git.current_branch is None` | `create_branch` / "Create branch" | checkout existing branch | This should outrank normal commit prompts. |
| Pull/switch blocked by uncommitted changes | git preview/pull state | `commit_or_discard_before_pull` / "Commit or discard changes" | force with confirmation | This is snapshot safety, not materialization drift. |
| Export/deploy blocked by uncommitted changes | readiness blocking issues | `commit_snapshot` / "Commit before export" | allow only if policy permits | Readiness and commit safety should converge on the same source-state model. |
| Required node lacks portable provenance | readiness warnings/blockers | `add_node_source_info` / "Add node source info" | mark optional, remove node | A local install can be healthy while export/build readiness is not. |
| Model lacks manifest source proof | readiness warnings | `add_model_source` / "Add model source" | use workspace index source hint, mark optional | SQLite source hints may be repair candidates but should not silently become proof. |
| Build readiness is blocked | build readiness | `fix_build_readiness` / "Fix build blockers" | view proof details | Build readiness is target/handoff state, not necessarily local runtime failure. |

### CGLIFE-STATUS-10 [LIVE]: Operation CTAs use action IDs instead of free text
Validation: STATIC

The composed status should use stable action IDs so CLI and Manager can render
different labels without changing behavior. Initial action IDs should include:

- `setup_workspace`
- `create_environment`
- `import_existing_environment`
- `sync_environment`
- `repair_environment`
- `sync_missing_nodes`
- `review_untracked_node`
- `track_dev_node`
- `remove_untracked_node`
- `resolve_workflow_nodes`
- `sync_model_paths`
- `download_required_models`
- `add_model_source`
- `add_node_source_info`
- `restart_comfyui`
- `view_runtime_import_error`
- `commit_snapshot`
- `create_branch`
- `push_snapshot`
- `export_environment`
- `deploy_environment`
- `fix_build_readiness`
- `view_operation_logs`

Adapters should prefer these IDs over parsing display strings.

## Current Adapter Terminology Gaps

### CGLIFE-STATUS-11 [PARTIAL]: Current CTA language is inconsistent across adapters
Validation: LLM_REVIEW

Known current inconsistencies:

- CLI `status` says "Environment needs repair" for filesystem/manifest drift,
  while sync and repair commands also handle broader dependency/model work.
- Manager uses `Repair`, `Repair Environment`, and sync-like operations for
  different underlying actions.
- Missing-model repair and environment repair are both labeled "Repair" in some
  Manager surfaces.
- Node add output can say "added to pyproject.toml", "Installed", or "node
  packs needed for installation" depending on path.
- Workflow resolve can report "partial resolution", "resolution complete", and
  "queued for download" as separate messages without a single lifecycle layer.
- Runtime restart guidance is separate from status/readiness and can be missed
  after node operations.
- Export readiness warnings are surfaced from an export-shaped check rather
  than from the primary status object.

Future UI/CLI work should align wording to the layer model:

- `Sync` means reconcile manifest-declared state into filesystem/venv.
- `Repair` means run a reconciliation action for detected drift or damage.
- `Restart` means reload the ComfyUI runtime process.
- `Resolve` means decide how workflow dependencies map to nodes/models/sources.
- `Commit` means save desired state as a Git snapshot after local health is
  acceptable.
- `Export` or `Deploy` means hand off a committed/reproducible state.

## Non-Goals

### CGLIFE-NONGOAL-01 [LIVE]: Lifecycle status does not automatically mutate state
Validation: HUMAN_REVIEW

The lifecycle matrix recommends actions; it does not silently track, delete,
download, restart, commit, export, or deploy. Destructive actions and actions
that materially change manifest, filesystem, runtime, or snapshot state should
require caller/user intent.

### CGLIFE-NONGOAL-02 [LIVE]: Runtime health is not portable manifest truth
Validation: HUMAN_REVIEW

Runtime import failures, process readiness, restart requirements, and supervisor
logs are local runtime state. They may block a local "healthy" status and may
inform deploy readiness, but they should not be committed as portable manifest
truth.
