# ComfyGit Core Contract

ComfyGit Core owns environment state, dependency metadata, local runtime
materialization, and library APIs used by the CLI, manager, Cloud, and future
runtime adapters.

## Library Boundary

### CGCORE-LIB-01 [LIVE]: Core stays UI-agnostic
Validation: STATIC

Core library code must not depend on a specific frontend, terminal UI, or ComfyUI
panel implementation. User interaction belongs behind callback protocols,
strategies, or callers in CLI/manager/Cloud surfaces.

### CGCORE-LIB-02 [LIVE]: Core should avoid direct print/input interaction
Validation: STATIC

Core code should not use `print()` or `input()` for normal behavior. Callers own
rendering, prompting, progress display, and cancellation UX.

### CGCORE-LIB-02A [RETIRED]: Legacy core migration notice exception
Validation: STATIC

The previous temporary exception that allowed a legacy schema migration path to
print directly to stderr from core is retired. Core migration paths should log or
return structured state; callers decide whether and how to render that state.

### CGCORE-LIB-03 [LIVE]: Workspace and Environment are the primary public API
Validation: MIXED

Callers should enter core behavior through Workspace and Environment APIs rather
than directly orchestrating manager internals. Manager classes may be used for
internal composition, tests, and advanced package-local behavior.

Public workspace discovery and creation should be exposed as Workspace
classmethods such as `Workspace.open()`, `Workspace.create()`, and
`Workspace.open_or_create()`. Consumers should not need to import
WorkspaceFactory for normal setup flows.

### CGCORE-LIB-03A [LIVE]: Public API is defined by documented facade exports
Validation: STATIC

The stable import surface is defined by `comfygit_core`, `comfygit_core.models`,
and other deliberately documented facade modules such as readiness, workflow,
runtime, assets, and git. Importable implementation packages such as managers,
repositories, analyzers, resolvers, integrations, configs, caching, and generic
utils are internal unless they are re-exported through a public facade.

Model files may contain both public and internal dataclasses. A model type is
public only when it is exported from `comfygit_core.models` or another documented
public facade. Adapter packages should not depend on deep model-module imports
for stable contracts.

Git facade helpers should return typed public models for stable domain shapes
such as remote ref discovery, and adapters should serialize those models only at
JSON/API boundaries.

Workspace model-index facade helpers such as `get_model_details()`,
`get_model_locations()`, `get_model_sources()`, and `get_model_stats()` should
return typed public model objects for stable index shapes. Repositories may keep
raw database row dictionaries internally, but adapters should not depend on
those row shapes.

### CGCORE-LIB-03B [PARTIAL]: Adapters should not reach through facade objects into managers
Validation: MIXED

CLI, Manager, Cloud, and future runtime adapters should call Workspace and
Environment methods for reusable behavior instead of touching cached manager,
repository, or utility attributes such as `env.pyproject`,
`env.workflow_manager`, `env.git_manager`, `env.uv_manager`, or
`workspace.workspace_config_manager`. Existing adapters still contain legacy
reach-throughs; new adapter needs should be served by typed facade methods and
public result models.

Environment command adapters now use facade methods for local PyTorch backend
selection, overlays, runtime Python lookup, manifest display, dependency group
mutation, and workflow model dependency edits. Workspace-level config/download
configuration now uses Workspace facade methods for Civitai, Hugging Face,
GitHub, and external UV cache settings. Provider-specific deployment
credentials such as retired RunPod keys are not part of core workspace
configuration. Workspace model-index adapter calls now use Workspace facade
methods for indexed source management, source lookup, hash completion, indexed
model lookup, and model-location deletion. Manager workflow APIs now use
Environment facades for workflow file lookup, cache invalidation, manifest model
mutation, custom-node mapping edits, saved and unsaved workflow analysis,
resolution fixing, model-path sync, package/model search, and post-download
manifest finalization. Serve-runtime adapter reach-throughs and specialized
workflow download streaming remain follow-on work.

### CGCORE-LIB-04 [PARTIAL]: Core owns reusable readiness and provenance policy
Validation: MIXED

Environment readiness, portable provenance classification, and dependency source
candidate discovery should live in core services. CLI, manager UI, Cloud, and
runtime planners should adapt those results for presentation instead of carrying
parallel policy implementations.

Core now exposes a first reusable readiness service for local handoff flows. It
classifies model source gaps, required custom-node provenance gaps, and optional
custom-node exclusions without Manager- or CLI-specific UI decisions. Workflow
source candidate discovery and deploy/build integration remain follow-on
work.

## Portable Environment Contract

### CGCORE-MAN-01 [LIVE]: Environment manifests are the portable source of truth
Validation: TEST

An environment repository's tracked `pyproject.toml` carries the portable recipe
for recreating the environment: ComfyUI/Python intent, Python dependencies,
custom nodes, workflows, workflow contracts, and model metadata.

### CGCORE-MAN-02 [LIVE]: Machine-local configuration is not committed as manifest truth
Validation: TEST

Machine-specific sync inputs such as PyTorch backend selection and local UV source
overrides belong in gitignored environment-local files, then get injected during
sync/run. They must not become required tracked manifest state.

### CGCORE-MAN-02A [PLANNED]: Machine-local dependency injection is crash-safe
Validation: TEST

Core should not mutate the tracked manifest file when applying machine-local
dependency configuration for uv resolution. Overlay and PyTorch backend data
should be applied to a disposable project copy or equivalent transaction target
so process crashes, host reboots, or hard kills cannot leave local-only state in
the environment repository's `pyproject.toml`.

Only explicit portable user edits, such as adding a declared Python dependency
or changing tracked custom-node metadata, should be written to the tracked
manifest. Generated resolution state such as `uv.lock` may be copied back only
when it is runtime-local or otherwise covered by manifest rules.

### CGCORE-MAN-03 [PARTIAL]: Runtime directories are derived materialization
Validation: MIXED

The ComfyUI checkout, virtual environment, installed custom nodes, symlinks, and
model links are materialized from tracked manifest state plus machine-local
configuration. Sync/repair should be able to recreate them instead of treating
their current disk contents as authoritative.

### CGCORE-MAN-04 [LIVE]: Git commits are environment snapshots
Validation: TEST

Environment changes meant to be shared or used by external runtimes should be
recorded in git. Core git operations should preserve the environment repository
as the auditable history of manifest and workflow changes.

### CGCORE-MAN-05 [LIVE]: Materialization is a headless runtime hydration path
Validation: MIXED

Core exposes a reusable materialization API that turns a portable
environment source into a runnable local environment without interactive prompts
or authoring-oriented side effects. Materialization reuses import/sync
machinery, and callers can select build/runtime defaults such as
skipping model downloads, omitting Manager registration, using an explicit
workspace, and failing hard on dependency sync errors.

### CGCORE-MAN-06 [LIVE]: Directory materialization copies only portable source files
Validation: TEST

When a plain directory is used as an environment source, core should copy only
portable environment recipe files into the target environment repository.
Runtime artifacts such as virtual environments, caches, local overlays, ComfyUI
checkouts, generated databases, logs, and model bytes are not portable source
truth and should not be copied by directory materialization.

## Workflow Contract Execution

### CGCORE-EXEC-01 [PARTIAL]: Core owns stored workflow contract execution semantics
Validation: MIXED

Core should provide UI-agnostic services for loading a tracked workflow
execution contract, applying caller inputs to its captured ComfyUI API prompt
artifact, and interpreting ComfyUI execution history back into declared contract
outputs. Manager, CLI, deploy/serve tooling, and other runtime adapters should
share these semantics rather than implementing parallel contract execution
mappers.

Core already stores workflow execution contracts in the manifest and exposes
read/write APIs through Environment. The legacy core-side UI-workflow conversion
path is no longer a supported contract authoring or runtime dependency; runtime
execution should consume Manager-captured API prompt artifacts.

### CGCORE-EXEC-02 [LIVE]: Core contract execution stays transport-agnostic
Validation: STATIC

Core should not own HTTP routing, websocket proxying, ComfyUI process
supervision, deployment provider APIs, run persistence, session persistence,
auth, file upload transport, or object storage delivery. Those responsibilities
belong to caller packages such as manager, CLI/serve, deploy, or external
runtime adapters. Core should expose deterministic library functions and typed
results that those packages can adapt to their transports. Browser UI assets
for `cg serve` are also adapter-owned; core must not depend on React, Vite,
`aiohttp`, SQLite runtime state, or any hosted studio runtime.

### CGCORE-EXEC-03 [PARTIAL]: `cg serve` is a runtime adapter over stored contract semantics
Validation: MIXED

The CLI serve runtime exposes contract-shaped workflow endpoints for a ComfyGit
environment by loading manifest state, using captured API prompt artifacts where
available, and communicating with a local ComfyUI server or another serve-owned
execution adapter. The serve runtime may provide HTTP endpoints, upload-slot
endpoints, output retrieval, static browser UI assets, state/session adapters,
storage adapters, and `RunExecutor` strategies, but it must not redefine the
manifest or contract semantics. The CLI serve adapter may depend on concrete
runtime tooling such as `aiohttp` for HTTP, SQLite for local serve state, and
React/Vite for packaged browser assets; core must not depend on or expose those
transport, persistence, execution-host, or presentation stacks.

Direct local ComfyUI execution, local proxy execution, remote proxy execution,
and serverless-provider execution are serve/deployment adapter choices. Core
should remain limited to preparing contract prompts and interpreting typed
execution results in a transport-agnostic way. This remains partial until all
runtime paths consume the same stable typed core execution services.

### CGCORE-EXEC-04 [PARTIAL]: API prompts are captured execution artifacts
Validation: TEST

The committed source of truth for workflow contract execution is the manifest
workflow contract plus a captured ComfyUI API-format prompt artifact produced
during Manager-based contract authoring. The UI-format workflow JSON remains the
editable source workflow, but runtime contract execution should use the captured
API prompt artifact that corresponds to the saved I/O mapping.

Core should not regenerate API prompts from UI-format workflow JSON. If the
captured API prompt artifact is missing, the contract should be treated as
incomplete and repaired by re-saving the contract through Manager.

Core now persists Manager-submitted API prompt artifacts and runtime prompt
preparation loads the stored artifact instead of converting the UI workflow.
The artifact path recorded in the manifest is a contract boundary: core export,
import/materialize, and push-readiness paths must preserve or validate the
referenced `workflow_api/*.api.json` file instead of treating it as optional
derived state. Additional runtime validation remains follow-on work.

### CGCORE-EXEC-05 [RETIRED]: Core converts UI workflows into API prompts
Validation: HUMAN_REVIEW

Core-side UI-workflow-to-API-prompt conversion is retired. ComfyUI frontend
behavior changes too quickly, and the backend lacks the loaded LiteGraph,
frontend widget, subgraph, mute/bypass, and native export context needed to keep
a parallel converter trustworthy. The converter should be removed from supported
paths rather than retained as a fallback.

## Dependency Reproducibility

### CGCORE-DEP-01 [LIVE]: Python package state is resolved through uv
Validation: TEST

ComfyGit-managed environments use uv to resolve and sync Python dependencies.
Manual package installs into the environment virtualenv are not durable unless
captured in manifest dependency state or machine-local injection config.
The `comfygit-system` dependency group owns uv as a ComfyGit-managed resolver
tool and must keep it on a version new enough to support the manifest features
ComfyGit writes, including dependency exclusions. Transitive packages may not
force uv below that floor; core records a matching uv override when seeding or
repairing the system group.

### CGCORE-DEP-02 [LIVE]: Models are external assets, not image/package payloads
Validation: MIXED

Model files are tracked by metadata such as filename, category, relative path,
hash, sources, and workflow references. The model bytes themselves stay external
to the Python package and environment manifest.

### CGCORE-DEP-02A [PARTIAL]: Workflows may declare indexed models without graph references
Validation: TEST

Core should let callers attach an already-indexed local model to a workflow even
when workflow graph analysis cannot identify a model-loading widget. This manual
workflow dependency must record the content hash and expected model-relative path
and must not invent a fake workflow node reference. Resolver, cache, readiness,
and missing-model checks should preserve and evaluate these entries alongside
graph-derived model dependencies.

The initial supported flow is local-first: the model must already exist in the
workspace model index before it can be attached to a workflow. Declaring a
missing model by URL and target path remains future download-intent behavior.

### CGCORE-DEP-02B [PARTIAL]: Built-in model-loader detection uses generated ComfyUI metadata
Validation: MIXED

Core should not rely only on a hand-maintained list of built-in ComfyUI model
loader node types. When a materialized environment has an installed ComfyUI
checkout, core should be able to derive model-loader metadata from that checkout
and use it during workflow dependency analysis.

Generated loader metadata should describe the node type, model widget name, model
widget index when derivable, and ComfyUI model directory or directories used by
the loader. Extraction should support both classic `INPUT_TYPES` definitions and
newer schema-style definitions that expose `folder_paths.get_filename_list(...)`
or equivalent folder-backed combo inputs.

Generated metadata is local derived state, not portable manifest truth. If
generation is unavailable or a loader is too dynamic to classify safely, core may
fall back to conservative static mappings and manual workflow model declarations.
Manual declarations remain the required escape hatch for custom nodes and opaque
runtime behavior. The current implementation extracts and consumes conservative
local metadata for folder-backed built-in loaders, but broad dynamic loader
coverage remains partial.

### CGCORE-DEP-03 [LIVE]: Model criticality affects reproducibility gates
Validation: TEST

Model references can be required, flexible, or optional. Required unresolved
models must be surfaced as blockers during export/import/build-readiness flows;
optional unresolved models may be treated as warnings.

### CGCORE-DEP-04 [PARTIAL]: Custom node criticality is manifest-declared
Validation: MIXED

Custom nodes should support an explicit `criticality = "required" | "optional"`
field in manifest metadata. Missing criticality defaults to required. Required
nodes without a reproducible acquisition path must be reported by readiness
checks. Optional nodes remain tracked as local environment state but should not be
treated as required portable build inputs. Core manifest storage and local
readiness enforcement exist; deploy/build consumption is still future work.

### CGCORE-DEP-05 [LIVE]: Workflow graph usage is advisory for custom node criticality
Validation: HUMAN_REVIEW

The presence or absence of custom node types in workflow JSON is not authoritative
proof that an installed custom node package is safe to omit. Side effects,
extensions, and runtime hooks mean graph analysis must not mutate package-level
criticality. Only explicit user action may mark an installed custom node
optional.

### CGCORE-DEP-05A [LIVE]: Live custom-node import health is runtime-owned
Validation: HUMAN_REVIEW

Core readiness describes portable environment state: manifest dependency
metadata, acquisition paths, git handoff state, and reproducibility inputs. It
must not claim that a custom node imported successfully inside a specific live
ComfyUI process, because that evidence depends on the active runtime's loader,
Python process, logs, and startup order.

Manager, serve, or provider runtimes may surface live import failures as
runtime health warnings. Those warnings may use core manifest identity and
workflow-usage metadata, but the live import signal itself is not core portable
state and must not mutate custom-node criticality.

### CGCORE-NODE-01 [LIVE]: Manager self-update prepares replacement metadata before mutating current Manager state
Validation: TEST

Because the Manager custom node depends on the running ComfyGit core package,
Manager install/update may use the generic node lifecycle but has an additional
ordering invariant: it must resolve replacement metadata and cached install
contents before removing the currently tracked Manager node or its dependency
group. Failed update preparation should leave the existing Manager manifest
entry and dependency group intact so users can recover by retrying or manually
updating the node.

### CGCORE-DEP-06 [PLANNED]: Model source candidate discovery is reusable core logic
Validation: MIXED

Scanning workflow files for embedded model URLs, classifying provider links,
scoring candidate source matches, deduplicating candidates, and filtering already
known model sources are dependency-domain behavior. Core should expose this as
UI-agnostic source-candidate services so manager, CLI, and build planning
can share the same logic.

Source candidate discovery should consume the same workflow model dependency
surface used by graph parsing, generated ComfyUI loader metadata, and manual
workflow model declarations. It should not invent a separate model identity model
for source enrichment.

### CGCORE-DEP-07 [LIVE]: Sync may repair ComfyGit-managed tool floors
Validation: TEST

Current ComfyGit code is allowed to normalize older environment manifests during
create, sync, repair, run, materialization, or node-install paths when the
manifest contains stale ComfyGit-managed tool constraints. In practice this means
core may rewrite the `comfygit-system` uv dependency and matching
`[tool.uv].override-dependencies` entry so tracked manifest features such as
`exclude-dependencies` are actually enforced by the resolver.

This policy intentionally favors keeping pre-customer environments runnable over
preserving historical tool versions exactly. The resulting manifest diff is a
real environment change and should be visible to callers that report dirty
environment state.

### CGCORE-DEP-08 [DEFERRED]: User-owned history should separate runtime minimums from materialized tool versions
Validation: HUMAN_REVIEW

Once ComfyGit environments are user-owned compatibility artifacts, the system
should distinguish between the minimum tool version required by the current
ComfyGit runtime and the exact tool version used when a historical environment
commit was last materialized. At that point, checkout of an older commit should
avoid silent toolchain migration where practical and should instead surface an
explicit repair or migration action when current ComfyGit cannot safely operate
with the recorded toolchain.

## Resolution And Sync

### CGCORE-SYNC-01 [LIVE]: Sync reconciles toward declared state
Validation: TEST

Sync should reconcile installed packages, custom nodes, workflows, models, and
derived configuration toward the manifest plus active local configuration instead
of only appending missing pieces.

### CGCORE-SYNC-02 [PARTIAL]: Readiness checks should fail before destructive or expensive work
Validation: MIXED

When core can detect missing required sources, unresolved dependencies, invalid
manifest state, or unavailable required models before a push/export/build-like
operation, it should report those issues before doing expensive or surprising
work.

### CGCORE-SYNC-03 [LIVE]: Development overrides are local by default
Validation: TEST

Editable local package and node paths are development conveniences. They should be
kept in local configuration unless explicitly converted into portable manifest
source metadata.

### CGCORE-SYNC-03A [LIVE]: Portable development nodes hydrate from pinned git refs
Validation: TEST

When a development custom node has portable git metadata, core sync and
materialization should be able to reconstruct a missing local node by cloning its
repository. If both branch and pinned commit metadata are present, core should
prefer the pinned commit for exact reconstruction. Branch metadata is advisory
for development context unless a caller explicitly requests branch-tracking
behavior.

### CGCORE-SYNC-03B [LIVE]: Git acquisition auth is local runtime configuration
Validation: TEST

Core may use local workspace credentials or runtime environment variables to
authenticate GitHub API calls and git clone/fetch operations for private
repositories. Those credentials must not be stored in environment manifests,
export bundles, or committed provider-neutral provenance metadata.

### CGCORE-SYNC-03C [LIVE]: Dev-link conversion preserves workflow package identity
Validation: TEST

When a tracked registry or git custom node is converted to a local development
checkout, core must preserve the existing manifest node identifier so workflow
`nodes` references remain valid. The conversion may replace the materialized
custom node directory with a symlink to a developer-owned checkout, but any
backup of the prior materialized node must live outside `custom_nodes` so sync
and status do not classify the backup as an untracked custom node.

### CGCORE-SYNC-03D [LIVE]: Installed custom-node aliases are exact and local
Validation: TEST

Core may use installed custom-node metadata to interpret workflow resolver output
or existing workflow references, but only as an environment-local aid. Alias
matching must be exact and case-sensitive, and an alias is usable only when it
points to one installed manifest node identifier. Registry ids, display names,
repository names, and materialized directory names must remain distinct portable
identity fields. Ambiguous aliases must not be normalized.

When one workflow has a user-confirmed `custom_node_map`, core may reuse that
mapping for another workflow only if all other tracked workflows agree for that
node type and the target package is installed in the manifest. The copied
workflow should still persist canonical manifest package ids in `nodes` rather
than display names or materialized directory names.

### CGCORE-SYNC-04 [PLANNED]: Build/runtime materialization fails on sync errors by default
Validation: TEST

Interactive import flows may surface recoverable warnings and let users repair an
environment later. Headless build/runtime materialization should treat dependency
sync failures, missing required acquisition metadata, and invalid manifest state
as command failures unless the caller explicitly opts into a weaker mode.
