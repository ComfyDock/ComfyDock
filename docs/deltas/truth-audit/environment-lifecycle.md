# Environment Lifecycle Truth Audit

Scope: `packages/core` and `packages/cli` environment lifecycle behavior:
create, sync, run, repair, materialize, import/export, git handoff, workspace
and environment APIs, overlays/local UV sources, PyTorch backend local config,
switch observer/restart lifecycle, and readiness.

This is a scratch audit only. It proposes truth-layer updates but does not edit
normative contracts/specs.

## Current Behavior Summary

- `Workspace` is the top-level core API for listing, loading, creating,
  importing, materializing, deleting, and activating environments. Environment
  names are validated before creation/import/materialization and partial
  environments are hidden from `list_environments()` until a completion marker
  exists.
- `Environment` is the main per-environment core API. It composes managers for
  `pyproject.toml`, uv, nodes, models, workflows, git, overlays, PyTorch backend
  config, model symlinks, and user-content symlinks.
- Creation initializes `.cec`, pins Python, probes/writes `.pytorch-backend`,
  clones or restores ComfyUI, extracts local derived ComfyUI metadata, creates
  symlinks, creates `pyproject.toml` and `package_config.toml`, syncs uv, installs
  Manager unless headless, initializes git, creates model links, and marks the
  environment complete.
- Import and materialization share `Environment.finalize_import()`. Import is
  authoring-oriented by default; materialization sets runtime-oriented switches:
  no Manager by default, no import commit, fail on sync errors, and model
  downloads skipped unless requested.
- Sync is guarded by an environment operation lock. It migrates old PyTorch
  manifest config to local config, ensures gitignore entries for generated/local
  files, ensures package config and ComfyGit-managed uv resolver floor, injects
  overlays/PyTorch configuration temporarily during uv sync, reconciles nodes,
  restores workflows, updates model links, and can resolve/download model intents
  according to strategy.
- CLI `run` syncs before starting ComfyUI unless `--no-sync` is passed, reads or
  probes the environment-local PyTorch backend, accepts one-time backend and
  overlay overrides, and supervises restart/switch exit codes. Restart exit code
  `42` causes another sync/run loop. Switch exit code `43` consumes a switch
  request, syncs the target environment, starts target ComfyUI, waits for HTTP
  readiness, writes switch status/logs, and only reports completion after the
  target server is reachable.
- CLI `repair` is status-preview driven. It displays planned deltas and then
  delegates to `env.sync()` to reconcile derived state from manifest/local config.
- Git operations delegate to `EnvironmentGitOrchestrator`. Checkout, hard reset,
  switch, merge, and revert snapshot old node state, perform git, reset
  `pyproject` handlers, reconcile nodes, uv-sync with PyTorch injection, and
  restore workflows. Branch switching can preserve uncommitted workflows when the
  target branch would not overwrite them.
- Push requires a clean `.cec` git tree and blocks if referenced workflow API
  prompt artifacts are missing or invalid. Export uses reusable readiness to
  block uncommitted workflow/git state and unresolved workflow issues unless
  explicitly allowed.
- Overlays have three relevant sources: `overlays/.local.toml` is always active
  and local, `.overlay-config.toml` activates shared/stock overlays locally,
  and CLI `--overlay` adds one-time overlays. Collection order is deterministic:
  local, active overlays sorted by canonical name, CLI extras, then generated
  PyTorch overlay. Injection is temporary and restores `pyproject.toml` after uv.
- Legacy `.local-uv-config` is migrated to `overlays/.local.toml` during overlay
  manager construction. Export/import and directory materialization copy shared
  overlays but exclude local overlay and local activation state.
- Core readiness is a typed handoff result. It separates source-state blockers
  from reproducibility warnings, checks model source gaps, required node
  provenance gaps, uncommitted workflow/git state, unresolved workflow issues,
  and workflow API prompt artifact availability.

## Key Code Paths

- Workspace lifecycle: `packages/core/src/comfygit_core/core/workspace.py`
  - `_validate_environment_name()`
  - `list_environments()`
  - `get_environment()`
  - `create_environment()`
  - `import_environment()`
  - `import_from_git()`
  - `materialize_environment()`
  - `set_active_environment()`
- Environment creation/import/finalization:
  `packages/core/src/comfygit_core/factories/environment_factory.py`,
  `packages/core/src/comfygit_core/core/environment.py`
  - `EnvironmentFactory.create()`
  - `EnvironmentFactory.import_from_bundle()`
  - `EnvironmentFactory.import_from_git()`
  - `EnvironmentFactory.import_from_directory()`
  - `Environment.finalize_import()`
- Sync and git handoff:
  `packages/core/src/comfygit_core/core/environment.py`,
  `packages/core/src/comfygit_core/managers/environment_git_orchestrator.py`
  - `Environment.sync()`
  - `Environment.pull_and_repair()`
  - `Environment.push_commits()`
  - `Environment.checkout()`, `reset()`, `switch_branch()`, `merge_branch()`
  - `EnvironmentGitOrchestrator._sync_environment_after_git()`
- Local config and overlays:
  - `packages/core/src/comfygit_core/managers/pytorch_backend_manager.py`
  - `packages/core/src/comfygit_core/managers/overlay_manager.py`
  - `packages/core/src/comfygit_core/managers/uv_project_manager.py`
- Readiness:
  - `packages/core/src/comfygit_core/services/environment_readiness.py`
  - `packages/core/src/comfygit_core/models/readiness.py`
- Run/switch/restart supervision:
  - `packages/cli/comfygit_cli/env_commands.py`
  - `packages/core/src/comfygit_core/lifecycle/switch_observer.py`
  - `packages/core/src/comfygit_core/lifecycle/comfyui_readiness.py`
- CLI adapters:
  - `packages/cli/comfygit_cli/global_commands.py`
  - `packages/cli/comfygit_cli/env_commands.py`

## Key Tests And Evidence

- Create/basic workspace:
  - `packages/core/tests/integration/test_environment_basic.py`
  - `packages/core/tests/integration/test_environment_create_progress.py`
  - `packages/core/tests/unit/core/test_reserved_environment_names.py`
- Materialization:
  - `packages/core/tests/unit/test_materialization.py`
  - `packages/cli/tests/test_materialize_command.py`
- Import/export/git:
  - `packages/core/tests/integration/test_export_import.py`
  - `packages/core/tests/integration/test_git_import.py`
  - `packages/core/tests/integration/test_git_subdirectory_import.py`
  - `packages/core/tests/integration/test_import_auto_remote.py`
  - `packages/core/tests/integration/test_git_pull_push.py`
  - `packages/core/tests/integration/test_branch_workflow_preservation.py`
  - `packages/cli/tests/test_branch_commands.py`
- Sync/repair/runtime:
  - `packages/core/tests/integration/test_repair_completion_marker.py`
  - `packages/core/tests/integration/test_repair_node_removal.py`
  - `packages/core/tests/integration/test_repair_workflow.py`
  - `packages/core/tests/integration/test_runtime_restart_workflow_preservation.py`
  - `packages/core/tests/unit/core/test_environment_operation_locking.py`
- PyTorch backend/local config:
  - `packages/cli/tests/test_torch_backend_cli.py`
  - `packages/core/tests/unit/managers/test_pytorch_backend_manager.py`
  - `packages/core/tests/unit/managers/test_pytorch_injection.py`
  - `packages/core/tests/unit/managers/test_pytorch_stripping.py`
  - `packages/core/tests/integration/test_pytorch_reconfiguration.py`
- Overlays/local UV sources:
  - `packages/core/tests/unit/managers/test_overlay_manager.py`
  - `packages/core/tests/unit/managers/test_overlay_injection.py`
  - `packages/core/tests/integration/test_overlay_e2e.py`
  - `packages/core/tests/integration/test_overlay_git_integration.py`
  - `packages/core/tests/integration/test_overlay_system_integration.py`
- Readiness/switch observer:
  - `packages/core/tests/unit/services/test_environment_readiness.py`
  - `packages/cli/tests/test_supervisor_control.py`
  - `packages/core/tests/unit/lifecycle/test_comfyui_readiness.py`

## Existing Clause Coverage

Strong existing coverage:

- `CGCORE-LIB-03`: Workspace and Environment are primary public APIs.
- `CGCORE-MAN-01` through `CGCORE-MAN-06`: portable manifest, local config
  exclusion, derived runtime directories, git snapshots, materialization, and
  directory materialization file selection.
- `CGCORE-DEP-01`: uv-owned dependency resolution and managed resolver floor.
- `CGSYNC-LIFE-01` through `CGSYNC-LIFE-09`: create/sync/run/repair basics,
  dependency review, resolver normalization, migration deferral, and switch
  observer primitives.
- `CGSYNC-GIT-01` through `CGSYNC-GIT-03`: commit/push-readiness/pull-checkout
  reconciliation at a high level.
- `CGSYNC-READY-01` through `CGSYNC-READY-04`: structured readiness,
  provenance semantics, source candidate future work, and exclusion of live
  import health from core readiness.
- `CGMAT-*`: materialize command shape, runtime defaults, source handling,
  typed API, shared finalization, failure semantics, and non-goals.
- `CGSPEC-LOCAL-01` through `CGSPEC-LOCAL-03`: PyTorch backend, local UV
  sources, git credentials, and resolver floor semantics.

Partial or overly broad existing coverage:

- `CGSYNC-LIFE-04` says repair restores derived state, but current CLI repair
  behavior is preview-driven and mostly `status -> sync`; this is not explicitly
  promised.
- `CGSYNC-LIFE-09` covers shared switch observer primitives, but not the CLI
  supervisor's current restart/switch state machine and readiness-before-complete
  guarantee.
- `CGSYNC-GIT-03` says pull/checkout should be followed by reconciliation, but
  does not spell out branch switching, hard reset, merge, revert, node
  reconciliation, or workflow preservation behavior.
- `CGSPEC-LOCAL-02` says local UV sources are machine-local, but overlays are now
  the implementation model. The clause does not describe local/shared/stock
  overlays, activation state, deterministic merge order, platform requirements,
  or temporary injection/restore.
- `CGCORE-MAN-03` covers derived runtime state generally, but completion markers
  and partial-environment cleanup/list filtering are important implemented
  lifecycle invariants not represented directly.

## Gaps And Mismatches

1. **Operation locking is implemented but barely specified.**
   Most mutating `Environment` methods are wrapped by `_requires_env_lock`, and
   there is direct unit coverage for at least `revert_commit()`. The truth layer
   should say environment mutations are serialized under an environment-local
   lock, especially because Manager, CLI, and future Cloud/runtime adapters share
   the same environment state.

2. **Completion marker and partial cleanup are core lifecycle behavior.**
   Create/import/materialize cleanup partial directories if `.cec/.complete` is
   not present, and `list_environments()` excludes incomplete envs. This is a
   concrete safety promise that is only implied by create/materialize clauses.

3. **Import authoring behavior lacks its own concise lifecycle clause.**
   Materialization is well specified, but normal import deserves an explicit
   contrast: it preserves git remotes for git imports, initializes git for bundle
   imports, installs/registers Manager unless `--no-manager`, may create import
   commits, and defaults to authoring-friendly model strategy.

4. **Overlays are under-specified relative to current implementation.**
   The old "local UV sources" concept has become an overlay system. Current
   behavior includes shared overlays, local overlays, stock overlays, activation
   config, platform requirement filtering, deterministic order, and temporary uv
   injection. This should be promoted into a dedicated local-configuration spec
   section.

5. **PyTorch CLI operation semantics are better tested than documented.**
   Creation/import/materialize default to auto-detecting a backend and writing
   `.pytorch-backend`; operation commands default to reading/probing the file;
   `--torch-backend` on sync/run/pull is a one-time override that does not
   persist. Existing clauses say PyTorch is machine-local but not this command
   split.

6. **Git handoff reconciliation is implemented more specifically than specified.**
   Checkout/reset/switch/merge/revert preserve or discard workflow changes based
   on operation semantics, reconcile node package state before uv sync, and
   restore workflows from tracked `.cec` after git changes. Current clauses only
   say reconciliation should happen.

7. **Run/restart/switch lifecycle deserves a CLI spec slice.**
   `cg run` is more than `env.run()`: it supervises sync, restart exit code 42,
   switch exit code 43, switch request consumption, status/log writing, and
   readiness validation before reporting switch completion. The shared observer
   primitive clause is good, but a user-facing lifecycle clause would prevent
   regressions.

8. **Readiness result is typed but still scoped narrowly.**
   Existing clauses correctly mark readiness partial. Current implementation is
   local handoff readiness, not full runtime/build readiness. The truth layer
   should preserve that boundary and add test references to the current typed
   guarantees.

9. **Core still has a small contract exception around `_ensure_schema_migrated()`.**
   `Environment._ensure_schema_migrated()` prints a migration notice to stderr
   from core. This conflicts somewhat with `CGCORE-LIB-02` ("Core should avoid
   direct print/input interaction") and should either be carved out as a legacy
   migration exception or moved up to CLI/manager presentation in future work.

## Proposed New Or Changed Clauses

### CGSYNC-LIFE-10 [LIVE]: Environment mutations are serialized by an environment-local operation lock
Validation: TEST

Mutating environment operations should run under the environment operation lock
so concurrent CLI, Manager, or runtime calls do not interleave writes to
manifest, lockfiles, node checkouts, workflow copies, symlinks, and git state.
The lock should cover sync, manager update, model/node/workflow mutations, git
handoff operations, import finalization where practical, and destructive
operations that reconcile runtime state.

Suggested evidence:

- `packages/core/tests/unit/core/test_environment_operation_locking.py`
- Additional clause refs in targeted tests for `sync`, `checkout`, `pull`, and
  node/model mutation wrappers.

### CGSYNC-LIFE-11 [LIVE]: Incomplete environments are hidden and cleaned up
Validation: TEST

Create, import, and materialization should mark an environment complete only
after tracked source state and derived runtime state are sufficiently initialized.
Workspace listing should exclude environments without the completion marker.
Failure paths should attempt to remove incomplete environment directories while
preserving completed environments and user data deletion semantics.

Suggested evidence:

- `packages/core/tests/integration/test_environment_basic.py`
- `packages/core/tests/integration/test_repair_completion_marker.py`
- Add explicit tests for create/import/materialize partial cleanup if not already
  covered.

### CGSYNC-IMPORT-01 [LIVE]: Import is an authoring setup flow, materialization is a runtime hydration flow
Validation: MIXED

Normal import should prepare an editable local environment for a human user:
preserve git identity/remotes for git imports, initialize a new repository for
bundle imports, restore workflows into ComfyUI, install/register Manager unless
headless mode is requested, and permit import-specific commits and softer sync
failure handling. Materialization should continue to use runtime-safe defaults
documented under `CGMAT-*`.

Suggested evidence:

- `packages/core/tests/integration/test_git_import.py`
- `packages/core/tests/integration/test_import_auto_remote.py`
- `packages/core/tests/unit/core/test_import_no_manager.py`
- `packages/cli/tests/test_no_manager_flags.py`

### CGSYNC-LOCAL-01 [LIVE]: Overlay injection is temporary local dependency configuration
Validation: TEST

Local/shared/stock overlays and PyTorch backend configuration may temporarily
inject dependencies, sources, indexes, constraints, and uv settings during uv
resolution. Injection must restore the tracked `pyproject.toml` afterward.
`overlays/.local.toml` and `.overlay-config.toml` are machine-local activation
state; shared non-local overlays may be portable source files.

Suggested evidence:

- `packages/core/tests/integration/test_overlay_e2e.py`
- `packages/core/tests/unit/managers/test_overlay_injection.py`
- `packages/core/tests/unit/managers/test_overlay_manager.py`

### CGSYNC-LOCAL-02 [LIVE]: Overlay collection order is deterministic and PyTorch wins last
Validation: TEST

Overlay collection should apply in deterministic order: local overlay first,
active overlays sorted canonically, CLI one-time overlays, then generated
PyTorch overlay. Platform-incompatible overlays should be skipped rather than
forcing invalid local dependency state.

Suggested evidence:

- `packages/core/tests/unit/managers/test_overlay_manager.py`
- `packages/core/tests/integration/test_overlay_e2e.py`

### CGSYNC-LOCAL-03 [LIVE]: Operation commands do not persist PyTorch backend overrides
Validation: TEST

Create/import/materialize may auto-detect and save a backend in
`.pytorch-backend`. Runtime operation commands such as sync, run, and pull
should read or auto-probe the environment-local backend when no override is
given. A `--torch-backend` override on those commands is a one-time sync input
and should not rewrite the saved backend file.

Suggested evidence:

- `packages/cli/tests/test_torch_backend_cli.py`
- `packages/core/tests/unit/managers/test_pytorch_backend_manager.py`
- `packages/core/tests/integration/test_pytorch_reconfiguration.py`

### CGSYNC-GIT-04 [LIVE]: Git handoff operations reconcile node, package, and workflow state after tree changes
Validation: TEST

Checkout, hard reset, branch switch, merge, revert, and pull should reconcile
derived environment state after changing tracked `.cec` state. Reconciliation
should reset manifest readers, reconcile custom-node filesystem state, sync uv
with local PyTorch/overlay injection, and restore tracked workflows into ComfyUI.
Branch switch may preserve uncommitted workflow edits only when the target branch
does not overwrite them.

Suggested evidence:

- `packages/core/tests/integration/test_branch_workflow_preservation.py`
- `packages/core/tests/integration/test_git_pull_push.py`
- `packages/core/tests/integration/test_pytorch_reconfiguration.py`
- `packages/cli/tests/test_branch_commands.py`

### CGSYNC-RUN-01 [LIVE]: `cg run` supervises sync, restart, and environment switch lifecycle
Validation: MIXED

`cg run` should sync before launching ComfyUI unless explicitly bypassed,
forward ComfyUI arguments, set ComfyGit runtime environment variables, and honor
well-known child exit codes for restart and environment switch. Restart should
force a fresh sync before relaunch. Environment switch should consume the target
request, sync the target environment, start target ComfyUI, and update shared
switch status/logs.

Suggested evidence:

- `packages/cli/comfygit_cli/env_commands.py`
- Add focused CLI tests for restart code `42`, switch code `43`, and `--no-sync`
  interactions if they are not already covered.

### CGSYNC-RUN-02 [LIVE]: Environment switch completion requires ComfyUI HTTP readiness
Validation: TEST

During supervisor-managed environment switching, the observer must not report
`complete` merely because the target process was started. It should move through
startup/validation states and only publish `complete` after the target ComfyUI
HTTP endpoint responds, mapping wildcard listen addresses to a local readiness
probe host.

Suggested evidence:

- `packages/cli/tests/test_supervisor_control.py`
- `packages/core/tests/unit/lifecycle/test_comfyui_readiness.py`
- Add a focused unit test around `_run_switched_comfyui()` with a fake process or
  injectable readiness function if feasible.

### CGSYNC-READY-05 [LIVE]: Handoff readiness blocks invalid or missing workflow API prompt artifacts
Validation: TEST

If a workflow execution contract references a `workflow_api/*.api.json` artifact,
export and push-readiness flows must treat missing or invalid artifact paths as
handoff blockers. Relative artifact paths must resolve inside the manifest
directory; absolute paths or path traversal should be invalid.

Suggested evidence:

- `packages/core/tests/unit/services/test_environment_readiness.py`
- `packages/core/src/comfygit_core/core/environment.py` push/export checks.

### CGCORE-LIB-02A [PARTIAL]: Legacy core migration notices are temporary presentation exceptions
Validation: HUMAN_REVIEW

Core should avoid normal `print()`/`input()` interaction, but existing legacy
schema migration currently emits a stderr notice from core while migrating old
PyTorch manifest config. This should be treated as a temporary exception and
eventually moved behind caller-owned presentation callbacks or structured
migration results.

Suggested evidence:

- Static review of `Environment._ensure_schema_migrated()`.

## Clauses To Reclassify Or Tighten

- `CGSYNC-LIFE-04 [PARTIAL]`: keep `PARTIAL`, but add detail that current repair
  is status-preview plus `sync()` reconciliation. Future work remains broader
  repair coverage and clearer failure recovery.
- `CGSYNC-GIT-03 [LIVE]`: keep `LIVE`, but either expand it or add
  `CGSYNC-GIT-04` so git operation specifics are not hidden behind a broad
  sentence.
- `CGSPEC-LOCAL-02 [LIVE]`: update wording from "Local UV sources" to overlays
  plus local UV/source injection, or make it the umbrella clause and add
  `CGSYNC-LOCAL-*` lifecycle clauses.
- `CGMAT-API-04 [PLANNED]`: current create/import/finalize paths now extract
  folder paths and model loader metadata. Consider reclassifying to `PARTIAL` or
  `LIVE` if the model-loader audit confirms workflow analysis consumes it as
  intended.
- `CGCORE-LIB-02 [LIVE]`: either accept the migration-print exception in a
  subclause or convert the direct print to structured/callback output before
  relying on this as a strict static rule.

## Test Traceability Updates

High-value existing tests that should include clause references as comments,
docstrings, or assertion messages when next touched:

- `packages/core/tests/unit/test_materialization.py`
  - `CGMAT-SRC-02`, `CGMAT-API-02`, `CGMAT-API-03`, `CGMAT-CMD-02`
- `packages/cli/tests/test_materialize_command.py`
  - `CGMAT-CMD-01`, `CGMAT-CMD-02`
- `packages/cli/tests/test_torch_backend_cli.py`
  - `CGSPEC-LOCAL-01`, proposed `CGSYNC-LOCAL-03`
- `packages/core/tests/integration/test_overlay_e2e.py`
  - `CGSPEC-LOCAL-02`, proposed `CGSYNC-LOCAL-01`, `CGSYNC-LOCAL-02`
- `packages/core/tests/unit/services/test_environment_readiness.py`
  - `CGSYNC-READY-01`, `CGSYNC-READY-02`, proposed `CGSYNC-READY-05`
- `packages/cli/tests/test_supervisor_control.py`
  - `CGSYNC-LIFE-09`, proposed `CGSYNC-RUN-01`, `CGSYNC-RUN-02`
- `packages/core/tests/unit/lifecycle/test_comfyui_readiness.py`
  - proposed `CGSYNC-RUN-02`
- `packages/core/tests/unit/core/test_environment_operation_locking.py`
  - proposed `CGSYNC-LIFE-10`
- `packages/core/tests/integration/test_branch_workflow_preservation.py`
  - `CGSYNC-GIT-03`, proposed `CGSYNC-GIT-04`

## Suggested Integration Plan

1. Add a small `Local Configuration And Overlays` section to
   `docs/specs/environment-sync-lifecycle.md` or create
   `docs/specs/environment-local-configuration.md` if the team wants overlays to
   be independently discoverable.
2. Add git/run/readiness lifecycle clauses to
   `docs/specs/environment-sync-lifecycle.md`; keep materialization-specific
   behavior in `environment-materialization-lifecycle.md`.
3. Add a concise import-authoring clause either to
   `environment-sync-lifecycle.md` or a future import/export lifecycle spec.
4. Add the temporary core migration-print exception or fix the print before
   tightening `CGCORE-LIB-02`.
5. Add clause references to the tests above opportunistically, not as a broad
   mechanical churn pass.
