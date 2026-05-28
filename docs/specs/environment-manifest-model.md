# Environment Manifest Model

This spec describes the tracked environment data shape that core, manager, CLI,
deploy, and serve/runtime adapters should agree on.

## Manifest Authority

### CGSPEC-MAN-01 [LIVE]: `pyproject.toml` is the tracked manifest file
Validation: TEST

ComfyGit environment repositories store the portable manifest in `pyproject.toml`.
Core may use helper files and databases for cache/runtime state, but portable
environment intent belongs in the manifest.

### CGSPEC-MAN-01A [LIVE]: Manifest APIs are pyproject-backed and UV-aware
Validation: MIXED

ComfyGit's manifest abstraction hides TOML syntax, TOMLKit document mechanics,
table ordering, and nested `[tool.comfygit]` storage details from normal callers.
It does not hide that the portable manifest is `pyproject.toml`, or that uv
dependency groups, sources, indexes, Python version, lock behavior, and
materialization semantics are part of the environment contract.

Core should provide typed manifest projections and domain edit affordances for
ComfyGit concepts such as nodes, workflows, models, headless materialization,
workflow contracts, and dependency intent. It should not introduce a generic
storage-agnostic manifest backend unless ComfyGit actually gains a second
portable manifest substrate.

### CGSPEC-MAN-02 [LIVE]: `[tool.comfygit]` owns ComfyGit-specific metadata
Validation: TEST

ComfyGit-specific environment metadata belongs under `[tool.comfygit]` tables.
Standard Python project metadata and dependency groups should continue to use
standard `pyproject.toml` locations where possible.

### CGSPEC-MAN-03 [LIVE]: Workflows are named manifest entries
Validation: TEST

Tracked workflows should have stable names in the manifest and should reference
their required node packages, model metadata, and execution contract metadata
where available.

### CGSPEC-MAN-04 [PARTIAL]: Workflow contracts are deployable API metadata
Validation: MIXED

Workflow input/output contracts should be stored in tracked environment state so
future build/deploy systems can expose a stable execution API for a workflow at a
specific commit.

### CGSPEC-MAN-05 [PLANNED]: Workflow contracts should be executable without Manager after authoring
Validation: MIXED

Workflow execution contracts are portable environment metadata, not ComfyGit
Manager UI state. After a contract has been authored and saved by Manager, a
materialized runtime should be able to serve contract-shaped workflow requests
without the Manager frontend installed when it has the manifest contract, the
captured API prompt artifact, and a reachable ComfyUI server.

CLI-only environments are not a supported path for authoring new contracts in
the local-first slice because they cannot capture ComfyUI's native frontend API
prompt export from the loaded graph.

### CGSPEC-MAN-06 [PARTIAL]: API workflow prompts are tracked contract artifacts
Validation: MIXED

Environment repositories should track ComfyUI API-format prompt JSON for
workflow contracts that have been saved through Manager. The UI workflow remains
the editable, reviewable, user-authored artifact; the captured API prompt is the
executable artifact for the saved I/O mapping and should be used by runtime
contract execution.

The manifest contract should reference the API prompt artifact path and record
basic provenance such as capture source and tool versions when available. The
recommended tracked location is `.cec/workflow_api/<workflow>.api.json`, kept
adjacent to `.cec/workflows/` without embedding large API prompt JSON directly
inside `pyproject.toml`.

Core now writes Manager-submitted API prompt artifacts to `workflow_api/` and
records their relative path plus basic provenance in `pyproject.toml`. More
complete provenance fields and compatibility checks remain follow-on work.

Because the manifest stores only a relative artifact pointer, the pointed-to
API prompt JSON is part of the environment manifest payload. Export tarballs
and directory-source materialization must include `workflow_api/` files, and git
handoff flows must require those files to be committed when referenced by a
workflow execution contract. Losing the file while preserving the manifest
contract leaves the contract non-executable.

When a workflow entry or execution contract is removed during commit-time
reconciliation, any `workflow_api/*.json` artifact that is no longer referenced
by a remaining execution contract should be pruned from tracked environment
state.

### CGSPEC-MAN-07 [LIVE]: Workflow contract numeric metadata must remain TOML-safe
Validation: TEST

Workflow contract inputs may mirror ComfyUI widget metadata whose numeric values
exceed TOML's signed 64-bit integer range, especially unsigned seed bounds. Core
must serialize out-of-range integers as strings in `pyproject.toml` and convert
them back to numeric values when loading typed workflow contract models. This
keeps the manifest parseable by strict TOML readers without losing numeric
precision for runtime and UI consumers.

### CGSPEC-MAN-07A [LIVE]: String contract input presentation is explicit metadata
Validation: TEST

Workflow contract inputs with `type = "string"` may store `ui_control` as
`"textarea"` or `"input"` to tell Studio-like consumers whether to render a
multiline or single-line text control. This field is presentation metadata for
contract clients; it must not change runtime coercion, API prompt patching, or
the portable value type, which remains `string`.

When `ui_control` is absent on a string input, Studio-like consumers should
prefer the less restrictive multiline control. They should not infer multiline
behavior from input names such as `prompt`, `text`, or `description`.

### CGSPEC-MAN-07B [LIVE]: Numeric contract input step is optional presentation metadata
Validation: TEST

Workflow contract inputs with `type = "integer"` or `type = "number"` may store
`step` as a positive numeric increment. This field is a control hint for
Studio-like consumers and authoring UIs; it must not replace `min`/`max`
validation or change runtime numeric coercion.

When `step` is absent, clients should choose conservative defaults such as `1`
for integer controls and a small decimal increment for floating-point controls.

### CGSPEC-MAN-08 [LIVE]: Core exposes a typed read-only manifest snapshot
Validation: TEST

Core should expose a typed read-only projection of the current manifest that is
derived from the same freshness-aware `pyproject.toml` load path as existing
handlers. The snapshot is a consumer-facing read model for services such as
readiness, build planning, and serve/runtime adapters. It must not replace the
`pyproject.toml` file as the persisted authority, and callers should request a
new snapshot after manifest mutations.

### CGSPEC-MAN-08A [PARTIAL]: Manifest writes use domain edits over raw TOML mutation
Validation: MIXED

Portable manifest mutations should flow through pyproject-backed domain methods
or edit transactions instead of scattered direct mutation of nested TOML tables.
Domain edit methods may expose UV-shaped concepts where those concepts are the
real contract, such as dependency groups and source/index configuration.

Storage-level code such as TOML I/O, merge/diff analysis, migration, and import
inspection may remain explicitly pyproject-aware. Adapter code and higher-level
core services should prefer typed snapshots and domain edit affordances.

### CGSPEC-MAN-09 [PLANNED]: Materialization consumes manifest truth, not runtime state
Validation: TEST

Headless materialization should hydrate ComfyUI, uv, workflows, custom nodes, and
model links from the portable manifest repository plus machine-local
configuration. It should not treat existing virtualenvs, local ComfyUI checkout
contents, caches, generated databases, or model bytes as portable manifest input.
Plain directory materialization should copy only recipe files needed to recreate
the environment.

## Custom Nodes

### CGSPEC-NODE-01 [LIVE]: Installed node packages are manifest-visible
Validation: TEST

Custom node packages that are part of the portable environment should appear in
manifest node metadata with enough identity to install or inspect them.

### CGSPEC-NODE-02 [LIVE]: Registry, Git URL, and local development nodes are distinct cases
Validation: MIXED

Core should preserve whether a node came from a registry entry, a Git/source URL,
or a local development path. Local development paths are not portable by
themselves.

### CGSPEC-NODE-02A [LIVE]: Development nodes become portable through git provenance
Validation: TEST

Development custom nodes may remain marked as `source = "development"` while
recording portable git provenance. A development node intended for handoff should
record its repository URL and pinned commit in the manifest. Branch metadata may
describe the author's current development branch, but exact import,
materialization, and deployment should prefer the pinned commit when available.

### CGSPEC-NODE-02B [LIVE]: Workflow node references use canonical manifest ids
Validation: TEST

Workflow `nodes` entries should reference the canonical package identifier used
under `[tool.comfygit.nodes]`. Resolver and status code may accept exact,
case-sensitive aliases from installed node metadata, including the materialized
custom-node directory name, registry id, or repository URL, but those aliases are
not portable workflow package identities. If an alias matches more than one
installed node, core must leave it unresolved rather than guessing.

Per-workflow `custom_node_map` entries are workflow-local resolution hints. Core
may derive a consensus fallback from other tracked workflows when all existing
mappings for a node type agree and resolve to an installed node. That fallback is
used for resolution and cache invalidation, but persisted workflow dependencies
remain canonical manifest node ids.

### CGSPEC-NODE-03 [LIVE]: Node criticality defaults to required
Validation: TEST

When a custom node manifest entry omits criticality, readers should treat it as
`required`. This keeps existing manifests conservative while allowing users to
mark intentionally non-deployable or experimental nodes as `optional`.

### CGSPEC-NODE-04 [PARTIAL]: Optional nodes may remain installed locally without blocking builds
Validation: MIXED

An optional custom node can be present in a local authoring environment without
being required for build readiness. The manifest should still make this intent
explicit so build planners do not have to infer it from workflow JSON. Workflow
graph analysis must not set this field automatically. Core and manager can now
persist this intent; centralized core readiness and build planner consumption are
still in progress.

### CGSPEC-NODE-05 [LIVE]: Node replacement is explicit and version-aware
Validation: TEST

Adding an already installed node without an explicit version should not silently
upgrade or replace it. Same-version adds fail as already installed. Different
version adds may replace regular nodes, while replacing development nodes
requires explicit force or caller confirmation.

### CGSPEC-NODE-06 [LIVE]: Node removal distinguishes untrack, development, tracked, and untracked filesystem modes
Validation: TEST

Removing a node should distinguish manifest untracking from filesystem removal.
Development nodes are untracked without deleting developer-owned files. Tracked
registry/git nodes remove the materialized directory and clean manifest workflow
references and orphaned uv sources. Explicit removal of an untracked filesystem
node may delete that directory, but normal sync without confirmed cleanup should
warn rather than delete untracked nodes.

### CGSPEC-NODE-07 [LIVE]: Development node links preserve portable manifest identity
Validation: TEST

Converting a tracked registry/git node to a local development checkout should
preserve the existing manifest node identifier so workflow references remain
valid. The materialized checkout may be replaced by a symlink to a
developer-owned path, and any archived previous copy should live outside
`custom_nodes` so status/sync do not classify it as an active untracked node.

### CGSPEC-NODE-08 [LIVE]: Batch node operations are sequential and per-item
Validation: TEST

CLI batch add/remove operations report per-node success and failure while
preserving already-completed operations. A batch failure does not imply an
automatic rollback of earlier successful node operations.

## Models

### CGSPEC-MODEL-01 [LIVE]: Models use content-oriented metadata
Validation: TEST

Model metadata should include enough information to identify the file, expected
location, category, source URLs when known, and content hash when available.

### CGSPEC-MODEL-02 [LIVE]: Required models without source proof are blockers
Validation: TEST

A required model that lacks a usable source and cannot be matched by known hash
is not reproducible. Export, import, push-readiness, or build-readiness
flows should surface that as a blocking issue.

### CGSPEC-MODEL-03 [LIVE]: Optional model gaps are warnings
Validation: TEST

Optional models may be unresolved without blocking every operation. Callers should
still surface the missing metadata clearly so the user understands the environment
may behave differently.

### CGSPEC-MODEL-03A [PARTIAL]: Model categories follow active ComfyUI folder paths
Validation: MIXED

Model category classification should be environment-aware. When an environment's
active ComfyUI checkout declares model folders such as `frame_interpolation`,
`optical_flow`, `background_removal`, or future built-in directories, scanner and
manifest presentation code should treat those folders as first-class categories
instead of collapsing them to `unknown` only because they are absent from an older
static list.

Static category tables remain a conservative fallback for bootstrapping,
materialization without a ComfyUI checkout, and folders that ComfyUI or user
configuration does not declare. Unknown/custom categories remain valid, but they
should mean "not known to the active environment" rather than "not in a stale
ComfyGit table." This remains partial while all model index presentation and
query paths are not yet consistently environment-aware.

### CGSPEC-MODEL-04 [LIVE]: Workflow model dependencies may be manually declared
Validation: TEST

Workflow model entries are not limited to references discovered from workflow
JSON widgets. A workflow may include a user-declared model dependency with an
empty `nodes` list when a custom node loads the model through behavior core
cannot infer from the graph. Such entries should be treated as workflow
dependencies, not as global model inventory.

Manual workflow model dependencies should initially be created only from models
that already exist in the current workspace model index. The manifest entry
should store the model hash, filename, category, criticality, resolved status,
and expected `relative_path` under the configured models directory. The relative
path remains meaningful for resolved manual dependencies because custom node
loaders may require the file to exist at a specific location.

### CGSPEC-MODEL-04A [PARTIAL]: Built-in model-loader discovery is generated from the active ComfyUI checkout
Validation: MIXED

Workflow dependency analysis should use generated model-loader metadata from the
environment's installed ComfyUI checkout when available. The generated metadata
should identify ComfyUI built-in nodes that select files from `folder_paths`
model directories, including newer loader forms such as frame interpolation,
optical flow, background removal, latent upscale, and model patch loaders.

Generated loader metadata should record enough structure for callers to resolve a
workflow widget value without guessing from display names alone: node type, widget
name, widget index when derivable, and one or more expected model directories.
The parser should prefer explicit `properties.models` source metadata when it is
present, then use generated folder-backed widget metadata, then fall back to
manual workflow declarations for loaders core cannot infer safely.

Static multi-model widget configuration should become a fallback and review aid,
not the only source of truth for built-in model loaders. Structurally discovered
loaders may still need classification when a node reads a model folder for
training, hook construction, optional enhancement, or another behavior that is
not a required runtime model dependency.

### CGSPEC-MODEL-05 [PLANNED]: Missing manual model declarations become download intents
Validation: MIXED

Future tooling may let users declare a required workflow model by target path and
source URL before the model exists locally. That flow should reuse workflow model
download-intent semantics, but it is not part of the initial local-first manual
dependency workflow.

### CGSPEC-MODEL-06 [LIVE]: The model index is local derived state
Validation: TEST

The workspace model index is machine-local runtime state, not portable manifest
truth. It may record multiple locations for one model hash, filter queries to
the configured current models directory by default, and keep download/source
hints that help repair manifest state without satisfying portable source proof
by themselves.

### CGSPEC-MODEL-07 [LIVE]: Model scan errors are per-file and nonfatal
Validation: TEST

Scanning a models directory should continue when an individual candidate file
cannot be inspected or hashed. Processing-time errors should be counted and
surfaced in scan results; the unreadable file must not be indexed as a valid
model.

### CGSPEC-MODEL-08 [LIVE]: Manifest sources are source proof; index sources are repair hints
Validation: TEST

Readiness and handoff checks should treat source URLs recorded in the manifest
global model table as portable source proof. Source URLs found only in the local
model index may be presented as repair candidates, but should not by themselves
satisfy manifest source readiness.

### CGSPEC-MODEL-09 [PARTIAL]: Download intents preserve target path and source until resolution
Validation: TEST

Workflow model entries may represent pending downloads with `status =
"unresolved"`, `sources`, and `relative_path`. Resolution should resume existing
intents without reprompting, batch downloads when requested, and convert
successful downloads into resolved hash-backed workflow/global model entries.
Failed downloads should leave the intent available for retry. This remains
partial because declaring missing manual models by URL is still planned.

### CGSPEC-MODEL-10 [LIVE]: Workflow path sync mutates only known built-in loader widgets
Validation: TEST

When syncing resolved model paths back into workflow JSON, core should update
only known built-in model-loader widget values. It should strip the built-in base
directory prefix expected by ComfyUI loaders, preserve subdirectories, normalize
path separators, and skip custom or unknown node widgets.

### CGSPEC-MODEL-11 [LIVE]: Category mismatch is a functional workflow issue for known loaders
Validation: TEST

For known built-in loaders, a resolved model whose indexed locations do not
include one of the loader's expected directories should be reported as a
functional category mismatch. Custom nodes should be skipped because core does
not know their model search paths.

## Local Configuration

### CGSPEC-LOCAL-01 [LIVE]: PyTorch backend selection is machine-local
Validation: TEST

The selected PyTorch backend and exact wheel pins are stored in local environment
configuration and injected during sync/run. They are not portable manifest truth.

### CGSPEC-LOCAL-02 [LIVE]: Local UV sources are machine-local
Validation: TEST

Local editable source paths and private local indexes belong in gitignored local
configuration. They should be injected into uv resolution when active, but not
committed as the portable environment recipe.

### CGSPEC-LOCAL-02A [LIVE]: Git credentials are machine-local acquisition config
Validation: TEST

GitHub or other git host credentials used to resolve private environment
repositories, git custom nodes, or development node repositories belong to the
machine, runtime, or calling user performing the acquisition. They may be
supplied by runtime environment variables, process-local credential helpers, or
adapter-scoped request credentials such as a browser-held Manager token. They
must not be written into the portable environment manifest. Manifest entries
should store repository URLs and refs; each machine, browser user, or deployment
provider supplies its own credentials.

### CGSPEC-LOCAL-02B [LIVE]: Provider API credentials are workspace-local and permission-hardened
Validation: TEST

CivitAI, Hugging Face, and future model/download provider API credentials may be
workspace-local acquisition configuration when backend model search or download
work needs durable machine-local access. They may be stored in the workspace
configuration file or supplied by environment variables, but they must not be
written into environment manifests, export bundles, model source metadata, or
workflow artifacts. Workspace credential files should be created with
owner-only permissions where the platform supports them, and UI surfaces should
describe that storage honestly instead of claiming server-side credentials are
never persisted. Git remote personal access tokens are governed by
`CGSPEC-LOCAL-02A` because they represent the calling user's git identity rather
than shared model-provider acquisition configuration.

### CGSPEC-LOCAL-03 [LIVE]: ComfyGit-managed resolver floors are tracked policy
Validation: TEST

The minimum uv resolver version required by current ComfyGit behavior is tracked
in the environment manifest because resolver capability changes the meaning of
portable fields such as `exclude-dependencies`. Core may maintain this policy
through the `comfygit-system` dependency group and a matching
`[tool.uv].override-dependencies` entry. Machine-local uv source paths and
editable package locations remain local configuration, but the resolver floor
needed to interpret the manifest is portable ComfyGit policy.

Recording the exact uv version used by a historical materialization is deferred.
That future field should describe reproducibility of a past run without blocking
current ComfyGit from declaring the minimum resolver capability it needs.
