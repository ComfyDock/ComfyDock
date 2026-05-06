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

For a Manager-authored contract, the portable execution unit is the manifest
contract metadata plus the referenced `workflow_api/*.api.json` file. Export
bundles, directory materialization sources, and git-pushed environment commits
must preserve those API prompt JSON files alongside `workflows/*.json`.

Core currently persists and reads workflow execution contracts. Runtime execution
now depends on captured API prompt artifacts, while full handoff validation is
still being tightened across export, materialize, and push paths.

### CGSERVE-CORE-02 [PARTIAL]: Contract authoring captures the API prompt artifact
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

Core and Manager now support the first save-time artifact path: Manager submits
the captured API prompt on contract save, core writes it under `workflow_api/`,
and the manifest execution contract records artifact provenance. Broader
compatibility checks against ComfyUI frontend versions remain future work.

`workflow_api/` is tracked portable state, not derived runtime state. It should
not be filtered out by export packaging, directory-source materialization, or
git commit/push flows when the files are referenced by workflow contracts.

### CGSERVE-CORE-02A [PARTIAL]: Stored API prompts are required for contract execution
Validation: TEST

Contract runtime paths should load the captured API prompt artifact referenced
by the manifest contract metadata. They must not attempt to regenerate a ComfyUI
API prompt from UI-format workflow JSON at runtime.

If a workflow contract lacks a captured API prompt artifact, runtime callers
should report the contract as incomplete and ask the user to re-save the
contract in Manager. Missing artifacts should not fall back to server-side
workflow conversion.

Core runtime prompt preparation now loads the manifest-referenced API prompt
artifact and errors when the artifact reference or file is missing. Existing
serve adapters still need broader end-to-end validation against captured
artifacts.

Export, push-readiness, and build/materialize planning should report a workflow
contract with a missing referenced API prompt artifact as a blocking issue. A
portable environment that advertises a runnable contract but lacks its
`workflow_api/*.api.json` file is incomplete.

### CGSERVE-CORE-02C [PLANNED]: Runtime patches concrete API bindings captured by Manager
Validation: TEST

Manager-authored inputs may store both UI/provenance bindings and concrete API
prompt bindings. Runtime prompt preparation should patch `api_node_id` plus
`api_field_key` when present, falling back to `node_id` plus `field_key` only
for older or non-subgraph bindings.

This is required for ComfyUI subgraph promoted widgets. The visible subgraph
node selected by the user may not exist in the captured API prompt; the prompt
contains scoped inner node IDs such as `170:151`. Manager is responsible for
capturing that binding from the loaded frontend graph during contract save.
Core must not infer scoped subgraph IDs heuristically from prompt contents.

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

The first supported authoring path should bind outputs to existing
artifact-producing ComfyUI output nodes such as `SaveImage` or `PreviewImage`.
Arbitrary graph slots and virtual subgraph output slots are not supported
contract outputs until the runtime has an explicit sink-injection or artifact
delivery model for intermediate graph values.

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
output references. The adapter is implemented as an `aiohttp` runtime in the
CLI package so it can grow into static UI serving, progress streams, websocket
bridging, and output delivery without moving transport concerns into core. This
adapter does not launch ComfyUI.

For `image` contract inputs backed by ComfyUI `LoadImage`, `cg serve` accepts a
data URL or `{ data_url, filename, mime_type }` payload, uploads it to ComfyUI's
image upload endpoint as an input file, then patches the captured API prompt
with the returned filename before submitting the prompt. Plain string values are
still treated as already-accessible ComfyUI input filenames. Because this first
Studio upload path sends image bytes inline in JSON, the serve adapter must
accept large contract request bodies and expose a request-size cap for local
operators.

This adapter should move to loading stored Manager-captured API prompt artifacts
before the contract runtime path is considered stable.

### CGSERVE-RUN-01A [PLANNED]: `cg serve` root hosts the contract studio UI
Validation: MIXED

The `cg serve` root path should render a browser UI for the served environment,
not a blank or API-only landing. This hosted contract studio is a thin client
over the same contract metadata and run endpoints that external callers use. It
must not introduce a second execution path or workflow-specific graph builder.

The first studio slice should list available contracts as cards, open a
contract-specific generation view, render controls from contract input schema,
submit generation requests to the matching contract run endpoint, and display
image outputs returned by the same API response. Unsupported input or output
types should degrade to plain fields or raw JSON instead of blocking the whole
contract.

### CGSERVE-RUN-01B [PLANNED]: Studio frontend is a packaged static asset
Validation: STATIC

The contract studio source should live in the CLI package as a normal
React/Vite frontend project for local development ergonomics. Release builds
should emit static assets into the Python package so `cg serve` can serve them
without requiring Node.js at runtime. The packaged UI may use design patterns
inspired by J AI Studio, but ComfyGit's UI remains contract-driven rather than
model/profile-driven.

During local development, the frontend may be built independently and served by
the CLI `aiohttp` adapter from its emitted asset directory. The serve adapter
owns static file routing, SPA fallback, and output proxy URLs; core continues to
own only contract interpretation and prompt/output semantics.

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
static hosted UI assets, artifact retrieval, cancellation, and output delivery
adapters. These concerns should stay outside core while still using core for
contract interpretation.

The hosted studio should call the same serve endpoints that scripts and
machines call. It is a presentation layer for contracts, not a privileged
runtime path.

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
