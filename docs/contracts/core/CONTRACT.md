# ComfyGit Core Contract

ComfyGit Core owns environment state, dependency metadata, local runtime
materialization, and library APIs used by the CLI, manager, deploy tooling, and
future runtime adapters.

## Library Boundary

### CGCORE-LIB-01 [LIVE]: Core stays UI-agnostic
Validation: STATIC

Core library code must not depend on a specific frontend, terminal UI, or ComfyUI
panel implementation. User interaction belongs behind callback protocols,
strategies, or callers in CLI/manager/deploy packages.

### CGCORE-LIB-02 [LIVE]: Core should avoid direct print/input interaction
Validation: STATIC

Core code should not use `print()` or `input()` for normal behavior. Callers own
rendering, prompting, progress display, and cancellation UX.

### CGCORE-LIB-03 [LIVE]: Workspace and Environment are the primary public API
Validation: MIXED

Callers should enter core behavior through Workspace and Environment APIs rather
than directly orchestrating manager internals. Manager classes may be used for
internal composition, tests, and advanced package-local behavior.

### CGCORE-LIB-04 [PARTIAL]: Core owns reusable readiness and provenance policy
Validation: MIXED

Environment readiness, portable provenance classification, and dependency source
candidate discovery should live in core services. CLI, manager UI, deploy
tooling, and runtime planners should adapt those results for presentation
instead of carrying parallel policy implementations.

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

### CGCORE-EXEC-02 [PLANNED]: Core contract execution stays transport-agnostic
Validation: STATIC

Core should not own HTTP routing, websocket proxying, ComfyUI process
supervision, deployment provider APIs, run persistence, session persistence,
auth, file upload transport, or object storage delivery. Those responsibilities
belong to caller packages such as manager, CLI/serve, deploy, or external
runtime adapters. Core should expose deterministic library functions and typed
results that those packages can adapt to their transports. Browser UI assets
for `cg serve` are also adapter-owned; core must not depend on React, Vite,
`aiohttp`, SQLite runtime state, or any hosted studio runtime.

### CGCORE-EXEC-03 [PLANNED]: `cg serve` is a runtime adapter over stored contract semantics
Validation: MIXED

A future ComfyGit serve runtime should expose contract-shaped workflow endpoints
for a ComfyGit environment by loading manifest state, captured API prompt
artifacts, calling core contract execution services, and communicating with a
local ComfyUI server or another serve-owned execution adapter. The serve
runtime may provide HTTP endpoints, progress streams, upload-slot endpoints,
output retrieval, static browser UI assets, state/session adapters, storage
adapters, and `RunExecutor` strategies, but it must not redefine the manifest
or contract semantics. The CLI serve adapter may depend on concrete runtime
tooling such as `aiohttp` for HTTP, SQLite for local serve state, and React/Vite
for packaged browser assets; core must not depend on or expose those transport,
persistence, execution-host, or presentation stacks.

Direct local ComfyUI execution, local proxy execution, remote proxy execution,
and serverless-provider execution are serve/deployment adapter choices. Core
should remain limited to preparing contract prompts and interpreting typed
execution results in a transport-agnostic way.

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

### CGCORE-DEP-06 [PLANNED]: Model source candidate discovery is reusable core logic
Validation: MIXED

Scanning workflow files for embedded model URLs, classifying provider links,
scoring candidate source matches, deduplicating candidates, and filtering already
known model sources are dependency-domain behavior. Core should expose this as
UI-agnostic source-candidate services so manager, CLI, and build planning
can share the same logic.

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

### CGCORE-SYNC-04 [PLANNED]: Build/runtime materialization fails on sync errors by default
Validation: TEST

Interactive import flows may surface recoverable warnings and let users repair an
environment later. Headless build/runtime materialization should treat dependency
sync failures, missing required acquisition metadata, and invalid manifest state
as command failures unless the caller explicitly opts into a weaker mode.
