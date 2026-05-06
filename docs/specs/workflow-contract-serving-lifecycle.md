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

For `image` contract inputs backed by ComfyUI `LoadImage`, Studio uploads file
bytes to the serve upload endpoint first, receives an opaque `file_ref`, and
submits that ref in the contract run request. The run handler resolves the ref
to the ComfyUI-accessible input filename before patching the captured API
prompt. Plain string values are still treated as already-accessible ComfyUI
input filenames for callers that deliberately manage their own input files.

Inline base64/data URL uploads are retired from the Studio execution path.
Contract run requests should stay small JSON control-plane messages; callers
with binary media must upload first and submit an upload reference.

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

### CGSERVE-RUN-05 [PARTIAL]: Contract execution is selected through a serve-owned executor strategy
Validation: MIXED

`cg serve` should treat contract execution as a serve-owned strategy boundary.
The HTTP API, hosted Studio, sessions, run records, upload refs, output refs,
and gallery state belong to the serve process. The actual execution path should
be selected by configuration through a conceptual `RunExecutor` interface
rather than being hard-coded into request handlers.

The first executor should remain a direct local ComfyUI executor because that
matches the current `cg run` and local development model:

```text
browser or API client
  -> cg serve
      -> LocalComfyExecutor
          -> local ComfyUI HTTP API
```

This executor may resolve local upload refs into ComfyUI input filenames,
submit prompts to the configured ComfyUI URL, poll or stream progress, and map
ComfyUI history/output data back into contract-shaped results. This is an
implementation detail of the local executor; the public serve API should expose
file refs, run refs, artifact refs, and contract result objects rather than
local filesystem paths or raw ComfyUI assumptions.

Current implementation: `cg serve` has a serve-owned `RunExecutor` seam and a
`LocalComfyExecutor` that submits prepared contract prompts to the configured
ComfyUI HTTP API, waits for history when requested, and normalizes ComfyUI
outputs back into contract output payloads. Request routing, sessions, upload
refs, run records, gallery state, and output delivery remain owned by the serve
runtime. Executor selection is not yet exposed as a user-facing configuration
surface, and proxy execution is not implemented.

### CGSERVE-RUN-06 [PLANNED]: Proxy execution is an optional future executor mode
Validation: HUMAN_REVIEW

Future serve deployments may execute contracts through a Comfy runtime proxy
instead of talking to ComfyUI directly. In that shape, the executor remains
inside the `cg serve` process as a strategy object, while the proxy is a
separate process that runs near ComfyUI and manages runtime-local data staging:

```text
browser or API client
  -> always-on cg serve
      -> ProxyComfyExecutor
          -> local or remote Comfy runtime proxy
              -> ComfyUI
```

For serverless GPU deployments, `cg serve` can run on a cheap always-on host
while the proxy and ComfyUI run inside or beside the ephemeral GPU worker. The
proxy should stage input refs into the form ComfyUI expects, submit prompts,
collect outputs, upload or register output artifacts, report progress and final
status, and then allow the worker to shut down. The proxy is not the public
contract API; it is an execution adapter behind `cg serve`.

Local proxy mode may be introduced later, for example through a `cg run` option
or a dedicated proxy command, but it is not required for the first direct local
executor slice.

## Runtime State And Gallery Persistence

### CGSERVE-STATE-01 [PARTIAL]: Serve state is adapter-owned runtime state
Validation: MIXED

`cg serve` may persist runtime state such as sessions, runs, gallery items,
upload refs, output artifact refs, progress snapshots, and contract snapshots.
This state is not portable environment source truth and must not be written into
the committed manifest or treated as part of reproducible environment metadata.

Core owns contract interpretation and prompt/output semantics. Serve owns the
runtime state adapter that records what happened while users interact with a
served environment.

Current implementation: `cg serve` has serve-owned ephemeral and SQLite state
stores for anonymous sessions, run records, and gallery item records. Upload
refs remain in process memory for this slice, and broader progress snapshots and
contract snapshots are still planned adapter responsibilities.

### CGSERVE-STATE-02 [PARTIAL]: Local SQLite is the first durable state adapter
Validation: TEST

The first durable serve implementation should use SQLite as the local state
adapter so a LAN or developer-machine Studio can survive browser refreshes and
`cg serve` restarts without requiring an external service.

The default database location should live under workspace/runtime metadata,
for example:

```text
<workspace>/.metadata/serve/serve.sqlite
```

The SQLite state store should be optional. `cg serve` should keep an ephemeral
mode for demos and tests where run/gallery state is held in memory and discarded
on process exit.

Current implementation: `cg serve --state local` enables a SQLite state store,
with `--state-db` available to override the default path. The default mode
remains `--state ephemeral` until durable local persistence is explicitly
requested.

### CGSERVE-STATE-03 [PARTIAL]: Gallery history is user/session scoped by policy
Validation: MIXED

Studio gallery history should be persisted independently from any single
contract view. If a user runs multiple workflow contracts, successful outputs
should appear in that user's unified gallery unless the serve policy says the
gallery is shared.

The first useful modes should be explicit:

```text
--state ephemeral
--state local
--gallery private
--gallery shared
```

`private` may initially mean an anonymous browser session cookie. `shared` means
all Studio clients see the same gallery for the served environment. Later auth
adapters may bind gallery state to authenticated user IDs.

Current implementation: the Studio gallery is loaded from `GET /gallery`, scoped
by an anonymous browser cookie in `private` mode or by a shared scope key in
`shared` mode. Gallery item deletion is scoped to the same policy.

### CGSERVE-STATE-04 [PARTIAL]: Serve state records stable artifact references, not large blobs
Validation: TEST

Persisted run and gallery records should store metadata and references, not
inline media bytes. A gallery item should record enough information to render
and debug the generation without embedding upload or output payloads directly in
the database row.

Useful first fields include workflow name, contract name, submitted display
inputs, prompt id, run status, created/updated timestamps, declared output name,
artifact refs, local or signed artifact URLs, and a contract/API-prompt
snapshot identifier when available.

Current implementation: persisted run and gallery rows store display inputs,
prompt ids, run status, output metadata, local output URLs, error payloads, and
raw API result metadata as JSON. Media bytes remain in ComfyUI input/output
locations and are not embedded in SQLite rows.

### CGSERVE-STATE-05 [DEFERRED]: Remote state and auth are adapter concerns
Validation: MIXED

Future deployments may replace local SQLite with a remote state adapter such as
Postgres/Supabase and may replace anonymous sessions with shared-token, OIDC,
reverse-proxy, or application-specific auth. Those adapters should use the same
conceptual serve interfaces as the local implementation:

```text
StateStore
StorageStore
AuthProvider
RunExecutor
```

The open-source local serve path should remain usable without a remote database
or auth provider, while leaving a clean extension point for users who want to
turn a served Studio into a multi-user or SaaS-style application.

## Input Transfer

### CGSERVE-IN-01 [PARTIAL]: Large contract inputs use upload references instead of inline bytes
Validation: MIXED

Contract run payloads should remain small JSON control-plane requests. Large
binary or media inputs such as images, audio, video, masks, and archives should
be uploaded before the run request and referenced by opaque file refs in the
contract input payload.

The preferred run input shape is an adapter-owned reference, not a local path or
base64 blob:

```json
{
  "kind": "file_ref",
  "ref": "upload_abc123",
  "filename": "input.png",
  "mime_type": "image/png"
}
```

The current Studio image path uses this shape and no longer sends base64/data
URL image payloads inside contract run JSON. This remains partial because audio,
video, masks, archives, and non-Studio clients still need broader typed upload
coverage and compatibility tests.

### CGSERVE-IN-02 [PARTIAL]: Serve owns an upload-slot endpoint
Validation: TEST

`cg serve` should expose an upload-slot flow before contract execution. A
client asks for an upload slot, uploads bytes to the returned URL, then submits
the returned file reference in the contract run request.

The first local implementation may use serve-managed URLs:

```text
POST /uploads/prepare
PUT  /uploads/{upload_id}?token=...
GET  /uploads/{upload_id}/status
```

The prepare response should include an opaque upload id/ref, upload URL, HTTP
method, required headers if any, expiry, accepted content constraints, and the
intended destination class such as `input`.

The first implementation exposes `POST /uploads/prepare`,
`PUT /uploads/{upload_id}?token=...`, and
`GET /uploads/{upload_id}/status`. It returns a `file_ref` for the contract run
payload and keeps local paths server-side.

### CGSERVE-IN-03 [PARTIAL]: Local disk is the first upload storage adapter
Validation: TEST

The first storage adapter should write uploads into the active environment's
ComfyUI input directory, which may itself be a symlink to the ComfyGit workspace
input area. The browser must not receive or submit trusted local filesystem
paths. It should only receive opaque upload refs and display-safe filenames.

The local adapter should generate safe filenames, reject path traversal, enforce
per-input size and MIME/extension limits, and return the ComfyUI-accessible
input filename needed to patch the captured API prompt.

The current adapter writes into the active environment's `ComfyUI/input`
directory using generated upload-prefixed filenames and enforces the configured
serve request-size limit. MIME/extension policy remains permissive until the
contract input schema exposes richer per-input media constraints.

### CGSERVE-IN-04 [DEFERRED]: Remote object storage is an upload adapter concern
Validation: MIXED

Future serve deployments may map upload refs to S3, R2, or another object
storage backend using presigned URLs. In that mode, serve is responsible for
resolving a file ref into the local file or URL form ComfyUI needs before
queueing the prompt. That may require downloading a remote object into the
ComfyUI input directory or teaching a deployment-specific runtime how to stage
inputs.

Object storage provider selection, presigned URL details, retention policy,
multi-user isolation, and remote cache cleanup belong to serve/deployment
adapters, not to core prompt-patching semantics.

## Output Delivery

### CGSERVE-OUT-01 [PARTIAL]: Local output refs are the first output delivery mode
Validation: TEST

The first serve implementation may return structured local ComfyUI output
references and metadata. This is enough for local Docker and development
validation without introducing external storage policy too early.

The serve adapter should normalize artifact presentation metadata as part of
output delivery. For image outputs, this includes recording the real artifact
width and height after the output exists. Studio and API clients should not
infer final output dimensions from contract input field names such as `width`
or `height`; pending outputs may use a neutral square placeholder until
artifact metadata is available.

Current implementation: local output URLs are returned through `/outputs/view`
and gallery rows persist local output references. Image artifact dimensions are
resolved by the serve adapter from the generated artifact bytes and stored with
gallery rows so refreshed Studio sessions can render the masonry grid without
client-side probing.

### CGSERVE-OUT-02 [DEFERRED]: Object storage delivery is an adapter concern
Validation: MIXED

S3/R2/provider bucket uploads, signed URLs, retention policy, and large artifact
delivery should be handled by serve/deployment adapters. Core may define output
metadata types, but it should not depend on a specific storage provider.

Serve should eventually treat outputs symmetrically with inputs: ComfyUI writes
local output artifacts, serve turns those into scoped artifact refs or signed
download URLs, and the hosted Studio consumes those refs rather than assuming
direct filesystem or raw ComfyUI output access.
