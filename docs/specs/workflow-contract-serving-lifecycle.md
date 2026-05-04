# Workflow Contract Serving Lifecycle

This spec describes the intended path from a tracked ComfyGit workflow contract
to a runtime API that can execute the workflow through ComfyUI. It captures the
shared semantics for executing Manager-authored contracts from committed
environment state.

## Core Execution Semantics

### CGSERVE-CORE-01 [PARTIAL]: Contracts are tracked environment truth
Validation: TEST

Workflow execution contracts are stored in the environment manifest under the
named workflow entry. They are part of the committed environment state and should
travel with the workflow JSON and captured API prompt artifact when an
environment is exported, pushed, materialized, or built.

Core currently persists and reads workflow execution contracts. Runtime execution
services for those contracts are still planned.

### CGSERVE-CORE-02 [PLANNED]: Contract authoring captures the API prompt artifact
Validation: TEST

The supported contract-authoring path runs inside ComfyUI with the ComfyGit
Manager installed. When the user saves an I/O mapping contract, Manager should
capture the same API-format prompt that ComfyUI's frontend would submit/export
for the loaded workflow graph and store that JSON as a tracked environment
artifact.

The UI-format workflow JSON remains the editable workflow artifact. The captured
API prompt is the executable contract artifact for the mapped workflow state.
It should only be refreshed by an explicit contract save/update action, because
later edits to the UI workflow may make the saved mapping stale without
invalidating the previously captured executable prompt.

### CGSERVE-CORE-02A [PLANNED]: Stored API prompts are required for contract execution
Validation: TEST

Contract runtime paths should load the captured API prompt artifact referenced
by the manifest contract metadata. They must not attempt to regenerate a ComfyUI
API prompt from UI-format workflow JSON at runtime.

If a workflow contract lacks a captured API prompt artifact, runtime callers
should report the contract as incomplete and ask the user to re-save the
contract in Manager. Missing artifacts should not fall back to server-side
workflow conversion.

### CGSERVE-CORE-02B [RETIRED]: Core performs UI-workflow-to-API-prompt conversion
Validation: HUMAN_REVIEW

The prior direction of maintaining a core-side converter from ComfyUI UI-format
workflow JSON to API-format prompt JSON is retired. Core does not have the same
graph, LiteGraph, widget, subgraph, bypass, and frontend-version context as
ComfyUI's native export path. Keeping a parallel converter creates a high-risk
second source of execution truth that can silently drift from ComfyUI behavior.

The converter should be removed from supported runtime and authoring paths
rather than kept as a fallback.

### CGSERVE-CORE-03 [PARTIAL]: Core extracts declared outputs from ComfyUI history
Validation: TEST

Core should expose a service that accepts a workflow execution contract and a
ComfyUI history entry, then returns the declared output metadata for the
contract. Output extraction should be based on contract output bindings rather
than ad hoc endpoint-specific assumptions.

Core now exposes a first output extraction helper that accepts declared contract
outputs and a ComfyUI history entry, then returns typed output results with
artifact references. The current implementation handles local history artifact
references such as image filenames, subfolders, and output types. Selector-slot
filtering and richer history validation remain planned.

### CGSERVE-CORE-04 [PARTIAL]: Core validates contract artifacts before execution
Validation: MIXED

Core should be able to report contract execution issues such as missing captured
API prompt artifacts, missing referenced workflow entries, invalid contract
input bindings, outputs pointing to unavailable history data, or incompatible
stored prompt metadata before or during execution. Callers should receive typed
errors or result objects instead of scraping string messages.

Core now reports typed prompt-build issues for unknown inputs, missing required
inputs, missing nodes, missing widget bindings, type coercion failures, enum
validation, and numeric bounds validation in the legacy build path. These checks
must be re-centered on stored API prompt artifacts as the conversion path is
removed.

## Runtime Adapter Boundary

### CGSERVE-RUN-01 [PARTIAL]: `cg serve` fronts ComfyUI with contract-shaped endpoints
Validation: MIXED

A serve runtime should expose HTTP endpoints shaped around ComfyGit workflow
contracts while communicating with a local ComfyUI server through ComfyUI's
normal API. External callers should send contract inputs to ComfyGit; ComfyGit
should translate those inputs into a ComfyUI prompt and map the resulting
artifacts back to contract outputs.

The CLI now provides a first `cg serve` adapter that resolves the active or
`-e <env>` environment, serves contract metadata, converts contract-shaped run
requests through legacy core prompt-building logic, submits prompts to a
configured ComfyUI API URL, optionally waits for history, and returns local
output references. This adapter does not launch ComfyUI.

This adapter should move to loading stored Manager-captured API prompt artifacts
before the contract runtime path is considered stable.

### CGSERVE-RUN-02 [PLANNED]: Serve can run without the Manager custom node after authoring
Validation: MIXED

Contract serving must not require the ComfyGit Manager node to be installed in a
materialized runtime environment after the contract has been authored. Manager is
the supported authoring path for creating or updating contracts because it can
capture ComfyUI-native API prompts from the loaded frontend graph.

Serve should operate from committed manifest state and captured API prompt
artifacts. CLI-only environments may run existing contracts but are not a
supported path for authoring new API-prompt-backed contracts.

### CGSERVE-RUN-03 [PLANNED]: Serve owns transport and lifecycle concerns
Validation: MIXED

The serve runtime may own HTTP routing, async run records, ComfyUI request
submission, history polling, progress streams, websocket/progress proxying,
artifact retrieval, cancellation, and output delivery adapters. These concerns
should stay outside core while still using core for contract interpretation.

### CGSERVE-RUN-04 [PLANNED]: Deployed containers should expose serve, not raw ComfyUI
Validation: HUMAN_REVIEW

For production-style deployments, the externally exposed API should be the
ComfyGit serve endpoint. ComfyUI may run locally inside the same container or
runtime, but callers should not need direct access to the ComfyUI UI/API to
execute a declared contract.

## Output Delivery

### CGSERVE-OUT-01 [PLANNED]: Local output refs are the first output delivery mode
Validation: TEST

The first serve implementation may return structured local ComfyUI output
references and metadata. This is enough for local Docker and development
validation without introducing external storage policy too early.

### CGSERVE-OUT-02 [DEFERRED]: Object storage delivery is an adapter concern
Validation: MIXED

S3/R2/provider bucket uploads, signed URLs, retention policy, and large artifact
delivery should be handled by serve/deployment adapters. Core may define output
metadata types, but it should not depend on a specific storage provider.
