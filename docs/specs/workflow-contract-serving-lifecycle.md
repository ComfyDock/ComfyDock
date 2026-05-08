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

For media/file contract inputs backed by ComfyUI loader nodes, Studio uploads
file bytes to the serve upload endpoint first, receives an opaque `file_ref`,
and submits that ref in the contract run request. The run handler resolves refs
for `image`, `audio`, `video`, and `file` contract inputs to the
ComfyUI-accessible input filename before patching the captured API prompt. Plain
string values are still treated as already-accessible ComfyUI input filenames
for callers that deliberately manage their own input files.

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
ComfyUI HTTP API with a generated ComfyUI `client_id`, waits for history when
requested, and normalizes ComfyUI outputs back into contract output payloads.
The generated `client_id` keeps ComfyUI's execution context populated for
progress and preview-aware nodes even when the run is initiated by the headless
serve API instead of the ComfyUI frontend. Request routing, sessions, upload
refs, run records, gallery state, and output delivery remain owned by the serve
runtime. Executor selection is not yet exposed as a user-facing configuration
surface, and proxy execution is not implemented.

### CGSERVE-RUN-05A [PLANNED]: Contract runs should be asynchronous by default
Validation: MIXED

The public contract run API should treat submission and completion as separate
phases. A default Studio or API run request should validate inputs, build the
captured API prompt, submit it to the selected executor, record a serve-owned
run row after the executor returns a `prompt_id` or equivalent provider run
identifier, and then return a `run_id` quickly instead of holding the HTTP
request open until ComfyUI history is complete.

The synchronous wait path may remain as an explicit compatibility mode for API
callers that pass `wait: true`, but it should not be the Studio default. Long
image, video, and audio runs should not depend on a hidden request timeout to
eventually appear in the gallery. Timeouts in the async path should describe
watcher, cleanup, or provider-lifetime policy rather than whether a browser
request stayed open long enough.

### CGSERVE-RUN-05B [PARTIAL]: Runs should expose recoverable output slots
Validation: MIXED

A run may produce zero, one, or many artifacts across one or more declared
contract outputs. Serve should model the pending UI as output slots associated
with a run, not as a single pending gallery item per run. On submission, serve
should derive expected slots from the contract output declarations and return
enough slot metadata for Studio to render pending cards immediately.

Each output slot should have a stable `slot_id`, `run_id`, declared output name,
media type when known, status, presentation metadata fallback, and timestamps.
When execution completes, a slot may resolve to no gallery items, one gallery
item, or multiple gallery items if a single output node produced multiple
artifacts. Gallery items should retain `run_id`, `slot_id`, declared output
name, and artifact index so refresh/recovery, deletion, details panels, and
future sharing policy can reason about multi-output runs without guessing from
filenames.

Current implementation: serve creates one deterministic output slot per
declared contract output when a run is submitted, persists those slots in the
serve state adapter, links gallery items with `slot_id`, and exposes run detail
state through `GET /runs/{run_id}`. Pending Studio cards are now returned from
serve-owned slot metadata instead of a single client-guessed placeholder.
Completion updates each slot to `done`, `empty`, or `error` based on the
normalized executor result. If ComfyUI returns a history entry whose status
reports execution failure, the local executor must treat the run as failed
rather than as a completed run with empty artifacts. This is still partial
because slots are not yet backed by a first-class event stream, artifact-index
metadata is only implicit in generated gallery rows, and progress semantics are
still future slices.

### CGSERVE-RUN-05C [PARTIAL]: Studio should recover active runs after refresh
Validation: MIXED

Studio should be able to reconstruct in-progress generations after a browser
refresh by asking serve for active runs and their output slots. In local durable
state mode, those active run and slot records should survive browser refreshes
and `cg serve` restarts. On serve restart, the local executor should perform a
best-effort recovery pass by checking ComfyUI history for active prompt IDs and
recording completed outputs or failed runs when enough information is
available.

In ephemeral mode, active runs may remain recoverable only while the same
`cg serve` process is alive. Browser localStorage may remember anonymous session
identity or UI preferences, but it must not be the source of truth for run
completion, output extraction, cancellation, or gallery records.

Current implementation: serve records submitted/running runs and pending gallery
items, exposes active runs through `/runs?active=true`, and schedules
best-effort completion watchers for active runs at startup and when gallery/run
state is queried. In local persistent state mode, a restarted `cg serve` process
can resume polling ComfyUI history by persisted `prompt_id` and update the
stored run/gallery rows when the prompt completes or fails. Recovery still uses
one pending gallery item per run; declared output slots and lifecycle events are
separate planned slices.

### CGSERVE-RUN-05D [PLANNED]: Serve should stream run lifecycle events
Validation: MIXED

Serve should expose a run event stream for Studio and API clients. The first
useful transport may be Server-Sent Events because it fits browser clients and
one-way progress updates, while future deployments may add websocket or proxy
bridging when richer bidirectional behavior is needed.

Useful event types include `run_started`, `run_progress`,
`run_output_completed`, `run_completed`, `run_failed`, and `run_cancelled`.
Progress may initially be coarse status text or elapsed time while the local
executor polls ComfyUI history. Later, the local or proxy executor may bridge
ComfyUI websocket progress into the same serve event shape.

### CGSERVE-RUN-05E [PARTIAL]: Serve should own cancellation semantics
Validation: MIXED

Studio should allow users to cancel in-progress runs through a single run-level
control near the Generate action, not through per-output pending tiles. The
public cancellation shape should be run-scoped, for example
`POST /runs/{run_id}/cancel`, even if the first local executor maps that to
ComfyUI's global interrupt behavior.

The first local implementation may document that cancellation interrupts the
active ComfyUI execution for the served instance and is therefore best suited to
single-user local Studio sessions. Shared or multi-user deployments must make
cancellation ownership and blast radius explicit before exposing it broadly.

Current implementation: serve exposes `POST /runs/{run_id}/cancel`, resolves
the run through the caller's gallery/session scope, asks the local executor to
delete the queued ComfyUI prompt and interrupt the matching prompt id, and marks
the run and output slots as `cancelled` while removing pending gallery rows so
the output grid returns to its pre-run state. Studio keeps Generate disabled and
loading while a pending run exists, and exposes a single run-level cancel
control under the Generate button once the run has a `run_id`. This is partial
because cancellation is still polling-observed rather than event-streamed, the
local executor relies on ComfyUI's prompt-id interrupt semantics, and shared
multi-user cancellation policy is not yet configurable.

### CGSERVE-RUN-06 [PARTIAL]: Proxy execution is an optional executor mode
Validation: HUMAN_REVIEW

Future serve deployments may execute contracts through a Comfy runtime proxy
instead of talking to ComfyUI directly. In that shape, the executor remains
inside the user-facing `cg serve` process as a strategy object, while the proxy
is a separate process that runs near ComfyUI and manages runtime-local data
staging:

```text
browser or API client
  -> always-on cg serve
      -> ProxyComfyExecutor
          -> local or remote Comfy runtime proxy
              -> ComfyUI
```

For serverless GPU deployments, `cg serve` can run on a cheap always-on host
while the proxy and ComfyUI run inside or beside the ephemeral GPU worker. The
front-door `cg serve` remains the public contract API and Studio host. It owns
contract discovery, sessions, SQLite/local state, gallery rows, run rows, upload
refs, and local artifact refs. The runtime proxy should stage input refs into the
form ComfyUI expects, submit prompts, collect outputs, and report progress and
final status back to the front door. The long-term proxy runtime should be a
worker that can shut down after the front door has received the terminal result
and persisted the artifacts or artifact refs.

The first proxy experiment should use two `cg serve` roles rather than changing
`cg run` semantics:

```text
# Front door on the user machine or cheap always-on host.
cg serve --executor proxy --proxy-url <runtime-proxy-url> --proxy-token <token>

# Runtime proxy beside ComfyUI in the GPU container.
cg run --listen 0.0.0.0 --port 8188
cg serve --role proxy --comfy-url http://127.0.0.1:8188 --proxy-token <token>
```

`cg run --with-proxy` or similar launch sugar may be added later, but the first
implementation should keep ComfyUI launch and proxy serving independently
testable.

Current implementation: `cg serve` supports a studio front-door role with
`--executor proxy --proxy-url <runtime-proxy-url>` and a compute-only runtime
role with `--role proxy`. The front door keeps the public contract API, Studio,
run rows, gallery rows, sessions, uploads, and localized artifact cache. The
runtime proxy talks to its configured local ComfyUI instance and exposes only
the proxy execution API. This remains partial because progress streaming,
remote object storage, deployment auth policy beyond a shared bearer token, and
launch sugar are not implemented.

### CGSERVE-RUN-06A [PARTIAL]: Runtime proxy mode is compute-only
Validation: HUMAN_REVIEW

Runtime proxy mode should not expose the public Studio surface, contract browser,
gallery endpoints, local session state, or SQLite persistence. It should expose
only internal execution endpoints needed by `ProxyComfyExecutor`, guarded by
deployment authentication such as a bearer token in the first implementation.

The minimal proxy API should be:

```text
GET  /proxy/health
POST /proxy/runs
GET  /proxy/runs/{run_id}
POST /proxy/runs/{run_id}/cancel
GET  /proxy/artifacts/{artifact_id}
```

The proxy may reuse local ComfyUI execution helpers internally, but its HTTP API
is not ComfyUI's raw API and is not the user-facing ComfyGit contract API.

Current implementation: `cg serve --role proxy` exposes the minimal proxy API,
does not mount the Studio static app or public gallery/contract endpoints, and
can require a bearer token shared with the front-door proxy executor.

### CGSERVE-RUN-06B [PARTIAL]: Proxy executor preserves the public run model
Validation: MIXED

`ProxyComfyExecutor` should conform to the same `RunExecutor` boundary as
`LocalComfyExecutor`. It should accept the prepared ComfyUI API prompt, declared
contract outputs, cache token, timeout settings, and staged upload metadata from
the front-door serve runtime. It should return the same normalized
`RunExecutionResult` shape consumed by serve run records, output slots, gallery
records, and Studio.

Front-door serve should not persist remote provider-specific run shape directly
as gallery truth. Provider ids, proxy ids, and remote artifact ids may be stored
in `raw_result` for debugging, but public recovery and gallery behavior should
continue to use serve-owned `run_id`, `slot_id`, and artifact refs.

Current implementation: `ProxyComfyExecutor` implements the `RunExecutor`
boundary, submits prepared prompts and staged upload metadata to the proxy
runtime, polls the proxy run status, maps completed proxy outputs back into the
existing `RunExecutionResult` shape, and localizes proxy artifacts before serve
records gallery state. Provider-specific ids remain debug metadata in raw
results.

### CGSERVE-RUN-06C [PARTIAL]: Local proxy mode is the first validation target
Validation: TEST

The first implementation should be testable without Modal, RunPod, S3, or R2 by
running two local serve processes against one local ComfyUI:

```text
Studio/browser
  -> front-door cg serve --executor proxy
      -> local runtime cg serve --role proxy
          -> local ComfyUI
```

Current validation: the first implementation has focused tests for the proxy
executor, proxy runtime app, CLI wiring, and upload staging. It has also been
manually validated against the local `comfygit-workflow-corpus-dev` environment
with a front-door serve process on `8791`, a runtime proxy serve process on
`8792`, and ComfyUI on `8190`.

This local proxy mode should validate the execution contract, staged uploads,
remote artifact handoff, cancellation request shape, and error normalization
before provider-specific serverless packaging is introduced.

### CGSERVE-RUN-06D [PARTIAL]: Proxy health exposes environment refs without enforcement
Validation: MIXED

Front-door serve and runtime proxy serve should make their environment identity
visible in health responses before enforcing any deployment compatibility rule.
The first visibility layer should report enough metadata for operators and
future CI/CD checks to compare whether the front door and proxy are serving the
same contract surface, such as environment name, `.cec` git commit when
available, dirty-state visibility when available, and a digest of the served
contract inputs.

This layer must not reject generation requests. It is a diagnostic signal for
humans, Studio, and future deployment automation. Enforcement, blocking UI
states, and provider-specific rollout policy belong to later slices after the
health shape is stable.

Current implementation: public `/health` returns a local `environment_ref`.
When configured with `--executor proxy`, public `/health` also includes the
proxy runtime health payload and a nullable `proxy_environment_ref_match`
boolean based on the reported contract digest. Runtime `/proxy/health` returns
its own `environment_ref`. A missing or mismatched ref is visible but does not
block proxy execution.

### CGSERVE-RUN-06E [PLANNED]: Front-door serve is the proxy coordinator
Validation: MIXED

For remote or serverless proxy execution, front-door serve should be the durable
run coordinator. It should create and own the public `run_id`, output slots,
session-scoped gallery rows, upload refs, artifact refs, and terminal run state.
The runtime proxy or provider worker should not write directly to the
front-door state store or become the durable source of truth for Studio/API
history.

The runtime proxy worker may own temporary provider ids, local ComfyUI prompt
ids, staged input paths, process-local task handles, and runtime-local output
paths while a job is executing. Those values may be returned as debug metadata,
but they should be treated as ephemeral worker state. Once the worker reports a
terminal result to the front door and the front door persists that result, the
worker may shut down without breaking gallery recovery.

Current implementation: front-door serve already owns public run rows,
output-slot rows, gallery rows, sessions, browser uploads, and localized
artifacts. The current proxy runtime still stores proxy run status and proxy
artifact ids in process memory while the front door polls it, so the callback
coordinator protocol remains planned.

### CGSERVE-RUN-06F [PLANNED]: Proxy workers report status through authenticated callbacks
Validation: MIXED

The serverless-ready proxy protocol should allow the front door to submit a
prepared run to a worker with a callback URL, front-door `run_id`, declared
outputs, staged input refs or bytes, and a scoped callback token. The worker
should use that callback channel to report meaningful lifecycle updates such as
accepted, running, heartbeat/progress, completed, failed, and cancelled.

The terminal callback should be idempotent from the front-door perspective.
Duplicate terminal callbacks for the same `run_id` should not create duplicate
gallery items or output slots. A callback that fails authentication should be
rejected without mutating run state.

Progress and heartbeat callbacks are advisory. They improve observability and
allow the front door to mark stale workers as failed, but they are not portable
manifest truth and must not replace the final terminal callback.

Current implementation: proxy execution uses front-door polling against
`GET /proxy/runs/{prompt_id}`. Authenticated worker-to-front-door callbacks,
heartbeat handling, and terminal callback idempotency are planned.

### CGSERVE-RUN-06G [PLANNED]: Worker completion uploads artifacts to the front door first
Validation: MIXED

The first serverless worker completion path should let the runtime proxy upload
generated artifact bytes directly to the front door as part of, or immediately
before, the terminal completion callback. This mirrors browser input upload
semantics: untrusted clients and remote workers pass bytes or opaque refs to the
front door, and the front door stores artifacts under its own serve-owned
storage before recording durable gallery state.

The terminal payload should carry normalized output metadata, declared output
names/selectors, artifact content type, filename, dimensions when available, and
enough raw provider/ComfyUI metadata for debugging. The front door should be the
only component that decides the final public artifact URL or gallery record.

Remote object storage remains a later adapter. A future worker may upload to
S3, R2, Modal volume/object storage, or another storage backend and report
scoped artifact refs instead of uploading bytes directly to the front door, but
the public Studio/API model should stay front-door-owned.

Current implementation: the front door downloads completed artifacts from the
runtime proxy's `/proxy/artifacts/{artifact_id}` endpoint after polling reports
completion. Worker-pushed artifact upload and object-storage artifact refs are
planned.

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

The current Studio media path uses this shape for `image`, `audio`, `video`, and
generic `file` inputs and no longer sends base64/data URL payloads inside
contract run JSON. This remains partial because masks, archives, richer
per-input constraints, and non-Studio client compatibility tests still need
broader typed upload coverage.

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

### CGSERVE-IN-05 [PARTIAL]: Proxy execution stages uploads without exposing local paths
Validation: MIXED

For proxy execution, front-door serve should continue to own browser upload
slots. Studio and API clients upload files to front-door serve and submit opaque
`file_ref` values. Front-door serve resolves those refs into server-side staged
upload records and patches the ComfyUI prompt with the filename that should exist
in the runtime proxy's ComfyUI input directory.

The first proxy transport may send staged upload bytes from front-door serve to
the runtime proxy as multipart data with the prepared run request. The runtime
proxy should write those files into its local ComfyUI input directory under the
requested generated filenames before submitting the prompt. Browser clients must
not receive trusted local paths from either side of the proxy boundary.

Object storage-backed input staging remains a later adapter: the same staged
upload record may eventually point to an S3/R2/Modal object ref instead of local
bytes, but the public contract run payload should remain based on opaque file
refs.

Current implementation: front-door serve resolves browser `file_ref` values into
server-side upload records, patches the workflow prompt with the generated
ComfyUI filename, and sends matching staged file bytes to the runtime proxy as
multipart fields on run submission. The runtime proxy writes those bytes into
its configured ComfyUI input directory before queueing the prompt.

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
and gallery rows persist local output references. Image and video outputs are
rendered as media in Studio, audio outputs render with an audio player, and
unknown output shapes fall back to structured output display. Image artifact
dimensions are resolved by the serve adapter from the generated artifact bytes
and video artifact dimensions are resolved by the serve adapter from generated
video metadata when local runtime tooling such as `ffprobe` is available. Those
dimensions are stored with gallery rows so refreshed Studio sessions can render
the masonry grid without client-side probing. If metadata probing is unavailable,
serve keeps the neutral 1:1 fallback rather than failing the generation.

### CGSERVE-OUT-02 [DEFERRED]: Object storage delivery is an adapter concern
Validation: MIXED

S3/R2/provider bucket uploads, signed URLs, retention policy, and large artifact
delivery should be handled by serve/deployment adapters. Core may define output
metadata types, but it should not depend on a specific storage provider.

Serve should eventually treat outputs symmetrically with inputs: ComfyUI writes
local output artifacts, serve turns those into scoped artifact refs or signed
download URLs, and the hosted Studio consumes those refs rather than assuming
direct filesystem or raw ComfyUI output access.

### CGSERVE-OUT-03 [PARTIAL]: Proxy outputs are localized before gallery persistence
Validation: MIXED

When `ProxyComfyExecutor` completes a run, front-door serve should copy or stream
the produced artifacts from the runtime proxy into front-door serve-owned output
storage before recording durable gallery items. The first implementation may use
a local artifact cache under serve metadata, for example
`.metadata/serve/artifacts/<run_id>/...`, and then expose those cached artifacts
through the existing front-door `/outputs/view` style delivery path or a
serve-owned artifact-ref endpoint.

This keeps Studio history usable after a serverless worker shuts down. Gallery
rows should point at front-door serve-owned artifact refs, not directly at
ephemeral proxy URLs. Runtime proxy artifact ids and remote URLs may be retained
inside raw result metadata for debugging, but they should not be the primary
persisted gallery source of truth.

Current implementation: the runtime proxy exposes generated artifact bytes under
opaque `/proxy/artifacts/{artifact_id}` ids. The front-door proxy executor
downloads those artifacts on completion, stores them under
`.metadata/serve/artifacts/<prompt_id>/...`, rewrites artifact URLs to
front-door `/outputs/view?serve_artifact=...`, and persists those localized refs
in run, output-slot, and gallery records.

Future direction: serverless workers should be able to push completed artifact
bytes directly to authenticated front-door callback/upload endpoints instead of
requiring the front door to fetch from a still-running proxy process. Object
storage-backed workers may later return scoped storage refs, but durable gallery
state should continue to point at front-door-owned refs after the front door has
accepted and persisted the artifact metadata.
