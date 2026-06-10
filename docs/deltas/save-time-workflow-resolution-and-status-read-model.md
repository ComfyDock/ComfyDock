# Delta Dossier: Save-Time Workflow Resolution And Status Read Model

## Clauses

- CGSPEC-MAN-03
- CGSPEC-MAN-08
- CGSPEC-MODEL-04
- CGSPEC-MODEL-04A
- CGSYNC-WF-01
- CGSYNC-WF-02
- CGSYNC-GIT-01
- CGLIFE-STATUS-02
- CGLIFE-STATUS-03
- CGLIFE-STATUS-05
- CGLIFE-STATUS-07
- CGLIFE-CAPTURE-01
- CGLIFE-NONGOAL-01

## Motivation

ComfyGit has two workflow resolution paths today:

- transient preview resolution for browser-provided workflow JSON, used by the
  Manager missing-dependencies popup before a workflow is saved
- saved-workflow resolution for status, resolve, sync, and commit flows

The save-time capture path currently copies a saved ComfyUI workflow into
`.cec/workflows` and ensures a manifest workflow entry, but it does not make the
working manifest fully describe the workflow's model and node dependencies.
That creates a confusing intermediate state: a workflow can look synced at the
file layer while its manifest dependency metadata is missing or stale.

This matters for user trust and for downstream build/deploy consumers. If a
user saves a workflow and sees it as part of the environment, the uncommitted
working snapshot should already describe the workflow as completely as ComfyGit
can infer. Git commit should record that state, not be the first domain
operation that discovers dependencies.

## Current Evidence

- Manager transient preview endpoint:
  - `comfygit-manager/server/api/v2/workflows.py`
  - `/v2/comfygit/workflow/analyze-json`
- Manager save-time capture endpoint:
  - `comfygit-manager/server/api/v2/workflows.py`
  - `/v2/comfygit/workflow/capture`
- Core capture and status paths:
  - `packages/core/src/comfygit_core/core/environment.py`
  - `packages/core/src/comfygit_core/managers/workflow_manager.py`
  - `packages/core/src/comfygit_core/services/workflow_analysis_cache.py`
  - `packages/core/src/comfygit_core/services/workflow_manifest_reconciler.py`
- Existing tests:
  - `packages/core/tests/integration/test_workflow_commit_flow.py`
  - `packages/core/tests/integration/test_workflow_subgraph_resolution.py`
  - `comfygit-manager/testing/integration/panel/test_workflow_endpoints.py`

## Gap

The current lifecycle has a mismatch between user intent and durable manifest
state:

1. User drops or loads a workflow.
2. Manager analyzes the unsaved workflow JSON and can display missing nodes or
   models.
3. User saves the workflow.
4. Manager captures the workflow file into `.cec/workflows`.
5. The manifest may contain only a workflow path, not the dependency projection.
6. Status may re-resolve the workflow and report issues, but that work is
   mostly read-only.
7. Commit currently needs a defensive reconciliation pass to avoid producing a
   snapshot whose manifest is missing dependency metadata.

That ordering makes status do too much repeated work and makes sync/commit
semantics harder to explain. It also made subgraph workflows risky: model
loaders inside `definitions.subgraphs` can be correctly resolved by the analysis
engine, but the result may not be written to manifest state until commit-time
reconciliation.

## Target Lifecycle

The intended lifecycle should be:

```text
drop/load workflow -> transient preview resolution, no manifest write
save workflow      -> capture + best-effort dependency reconciliation
status             -> report/validate current state
resolve            -> user-guided dependency repair
commit             -> defensive reconciliation + Git snapshot
```

Save-time capture should be the point where a workflow becomes part of the
ComfyGit working snapshot. At that point core should:

- copy/update `.cec/workflows/<workflow>.json`
- upsert the manifest workflow entry/path
- run best-effort dependency analysis and resolution
- write resolved and unresolved model dependencies into workflow manifest state
- write resolved global model entries when local indexed models are matched
- write resolved custom-node package references where resolver confidence and
  policy permit
- preserve unresolved nodes, ambiguous nodes/models, download intents, source
  hints, criticality, manual model dependencies, and model path/category issues
- invalidate or refresh workflow analysis caches for that workflow
- leave the environment repository dirty for the user to review and commit

Commit should remain a final idempotent safety pass:

- rerun or validate dependency reconciliation for affected workflows
- avoid relying only on file sync state
- refuse unsafe commits unless the caller explicitly allows issues
- record the current `.cec/pyproject.toml`, workflow files, contracts, and
  related artifacts as a Git snapshot

## Phase 1: Save-Time Resolution/Reconciliation

Implement this before status performance work.

### Desired API Shape

Prefer a core-level mutation surface such as one of:

```python
env.capture_workflow("name")
env.capture_workflow("name", reconcile_dependencies=True)
env.capture_workflow_snapshot("name")
```

The exact name can follow existing API style, but the public behavior should be
clear: capture is a mutation that promotes a saved ComfyUI workflow into the
working ComfyGit snapshot. It may analyze and write manifest dependency
metadata. It must not commit.

The method should return either the tracked workflow path as today or a small
typed result that can grow without breaking callers, for example:

```python
WorkflowCaptureResult(
    workflow_name="video_ltx2_3_flf2v",
    tracked_path=Path(".cec/workflows/video_ltx2_3_flf2v.json"),
    manifest_changed=True,
    dependency_metadata_changed=True,
    has_blockers=True,
)
```

If a typed result is too broad for the first slice, keep the existing return
value and add the typed result in a later API cleanup.

### Implementation Notes

- The save-time path should reuse `WorkflowManifestReconciler`; do not create a
  second workflow-to-manifest writer.
- The path should reuse the same dependency parser and resolution service as
  status/resolve so subgraphs, generated ComfyUI model-loader metadata, manual
  declarations, and download-intent semantics stay consistent.
- If dependencies cannot be fully resolved, persist what is known rather than
  treating the capture as failed. Unknowns should become lifecycle issues and
  resolver UI work, not lost state.
- The operation should run under the environment operation lock when invoked
  through public `Environment` APIs.
- The Manager capture endpoint should not need to know manifest internals; it
  should call the public environment capture method and render the returned
  result or refreshed status.
- Commit-time reconciliation should remain after this phase as a guardrail for
  stale states, old environments, and missed save events.

### Tests

Add or update tests proving:

- saving/capturing a new workflow writes the workflow file and manifest entry
- saving/capturing a workflow with a resolved local model writes workflow model
  metadata and the global model table before commit
- saving/capturing a subgraph workflow writes models discovered inside
  `definitions.subgraphs`
- saving/capturing a workflow with missing models records unresolved/download
  intent metadata when source hints are present
- saving/capturing a workflow with missing custom nodes records node dependency
  intent when resolver output is trusted
- capture leaves the Git repository dirty and does not commit
- commit after capture is idempotent and does not produce additional manifest
  churn when dependency metadata is already fresh
- sync does not delete a saved workflow merely because it was uncommitted

## Phase 2: Status Read Model And Performance

Do this only after Phase 1 is correct.

The current status path can continue to analyze workflows for correctness, but
the target shape is a cheaper read model:

```text
status
  -> read workflow file sync state
  -> read manifest dependency projection
  -> read installed node/materialization state
  -> read model index availability
  -> read runtime import state
  -> read git dirty state
  -> re-analyze only workflows whose semantic inputs are stale
```

Status should not blindly trust manifest metadata. It should use freshness
checks such as:

- workflow JSON content hash/signature changed
- `.cec/workflows` differs from ComfyUI working workflow file
- manifest dependency metadata is absent or stale relative to the workflow file
- model index generation or scanned models changed
- installed node set changed
- registry/node mapping data changed
- generated ComfyUI model-loader metadata changed
- ComfyUI version or model folder mapping changed
- resolver policy version changed

The freshness data can live in local cache state rather than portable manifest
truth. The manifest should describe environment intent; cache keys should
describe whether a local analysis result can be reused.

### Tests

Add or update tests proving:

- unchanged workflows do not require full re-resolution for basic status
- changed workflow JSON invalidates only that workflow's analysis
- changed model index invalidates model-resolution status
- changed installed node set invalidates node materialization status
- generated model-loader metadata changes invalidate workflows that depend on
  loader detection
- status reports stale/missing dependency metadata as an actionable capture or
  reconciliation issue rather than silently producing green state

## Phase 3: Adapter UX Wiring

After save-time capture and status read-model behavior are stable, Manager and
CLI should align their wording:

- Preview resolution: "This unsaved workflow needs dependencies."
- Save-time capture: "Workflow saved to working snapshot."
- Dependency blockers: "Resolve workflow nodes" or "Resolve models."
- Snapshot state: "Commit snapshot."
- Materialization drift: "Sync missing nodes" or "Sync environment."
- Runtime stale: "Restart ComfyUI."

The Manager status page should continue to show one top-level recommended
action plus lifecycle tiles. The tiles should draw from composed lifecycle state,
not duplicate ad hoc resolver checks.

## Non-Goals

- Do not make workflow load/drop mutate manifest state.
- Do not commit automatically on save.
- Do not silently delete uncommitted workflows during sync.
- Do not invent node-specific compatibility hacks in core.
- Do not make status faster by trusting stale manifest metadata.
- Do not move Manager UI policy into core. Core should return typed state and
  stable action IDs; adapters render UX.

## Validation Plan

For Phase 1:

```bash
uv run pytest packages/core/tests/integration/test_workflow_subgraph_resolution.py -q
uv run pytest packages/core/tests/integration/test_workflow_commit_flow.py -q
uv run pytest packages/core/tests/integration/test_pyproject_batch_writes.py -q
uv run pytest packages/core/tests/unit/core/test_environment_sync.py -q
```

For Manager capture wiring:

```bash
cd ../comfygit-manager
uv run pytest testing/integration/panel/test_workflow_endpoints.py -q
npm test -- StatusSection
```

For live smoke testing:

1. Start a Manager dev environment with editable core overlay.
2. Drop an unsaved workflow with missing nodes/models and confirm the preview
   popup appears without manifest mutation.
3. Save the workflow and confirm `.cec/workflows` and `.cec/pyproject.toml`
   both change.
4. Confirm status shows workflow/model/node blockers from manifest-backed
   dependency state.
5. Resolve blockers, sync, restart, and commit.
6. Checkout/materialize the commit and confirm model/node dependency metadata is
   present without relying on local-only cache state.

## Suggested Work Breakdown

1. Add save-time capture tests in core, initially failing.
2. Change core capture to call the manifest reconciler after copying the
   workflow.
3. Keep commit-time reconciliation as idempotent fallback and prove it no longer
   churns after fresh capture.
4. Update Manager capture endpoint tests to expect dependency metadata to exist
   after save/capture.
5. Run live Manager smoke tests on Linux.
6. Run one Windows smoke test for save/capture/commit parity.
7. Only then start the status read-model optimization.
