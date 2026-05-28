# Node Lifecycle And Resolution Truth Audit

Scope: `packages/core` and `packages/cli` behavior around custom-node lookup,
resolution, add/update/remove, development-node handling, dependency previews,
aliases/consensus mappings, criticality, and Manager-node special cases.

This is an audit scratch file only. It proposes truth-layer updates but does not
change normative contracts or specs.

## Current Behavior Summary

### Manifest Identity And Node Types

- Portable custom-node state is stored under `[tool.comfygit.nodes]` in
  `pyproject.toml`; the manifest key is the canonical package identifier used by
  workflow dependency lists.
- A `NodeInfo` carries `name`, `version`, `source`, `registry_id`, `repository`,
  `branch`, `pinned_commit`, `dependency_sources`, and `criticality`.
- Supported node sources in the manager path are:
  - `registry`: package from the ComfyUI Registry.
  - `git`: direct repository install when a GitHub URL is not resolved to a
    registry id.
  - `development`: local checkout/symlink tracked for authoring.
- Missing node criticality normalizes to `required`. New node records are written
  with explicit criticality through the `NodeInfo` model.
- Dependency groups are hash/stable-name generated from node identity, and the
  system uv floor is protected by `comfygit-system`.

### Add Node

- CLI `cg node add <node...>` calls `Environment.add_node()`, which is locked
  and delegates to `NodeManager.add_node()`.
- Identifiers can be registry ids, `id@version`, GitHub URLs, or development
  names with `--dev`.
- GitHub URLs are first resolved through node mappings to a registry id. If no
  registry match exists, the URL can still be installed as a git node.
- Existing installs are detected primarily by materialized node name. Adding an
  already-installed node without an explicit version is rejected and suggests
  `node update` or `node add <id>@<version>`.
- Adding the same version is rejected. Adding a different version replaces the
  old installation inside a transaction.
- Replacing a development node requires explicit force or confirmation.
- Filesystem conflicts are checked before install unless this is an expected
  replacement.
- Node contents are downloaded to cache, requirements are scanned, dependencies
  are probed unless `--no-test` is set, and the environment is synced after
  writing manifest changes.
- Default dependency behavior probes requirements and can apply discovered
  constraints. `--strict` preserves fail-fast dependency-conflict behavior.
- The transactional section snapshots `pyproject.toml`, moves the old node to
  `.disabled` during replacement, writes constraints/manifest state, copies the
  new node, syncs uv, and rolls back manifest/filesystem on failure.
- Batch add is CLI orchestration over repeated single-node installs. It reports
  per-node failures but does not currently provide an atomic all-or-nothing batch
  transaction.
- `--resolve-with-overlays` makes node install sync include all active overlays;
  default node install sync skips optional overlays and uses PyTorch/backend
  injection.

### Dependency Preview And Reviewed Apply

- `Environment.preview_add_node_dependency_changes()` and
  `NodeManager.preview_add_node_dependency_changes()` generate a typed preview
  without mutating the real environment.
- Preview downloads/scans the candidate node, builds a `NodePackage`, and calls
  `DependencyResolutionPreviewService.preview_node_package()`.
- Preview refuses already-installed nodes.
- `apply_reviewed_node_dependency_changes()` validates that the accepted preview
  matches current baseline/diff/proposed fingerprints before applying.
- Reviewed apply re-runs the preview under the environment lock, aborts stale
  accepts, then calls `add_node(..., allow_reviewed_dependency_changes=True,
  skip_optional_overlays=False)`.
- CLI has no first-class reviewed-apply command yet; Manager owns the current UI
  for that path.

### Development Nodes

- `cg node add --dev <identifier>` either tracks an existing directory in
  `custom_nodes/` or downloads a registry/GitHub node and marks it development.
- Development add captures git remote, branch, and commit when available.
- `cg node dev-link <identifier> --path <checkout>` is the stronger conversion
  path. It can preserve the existing manifest identifier while replacing a
  materialized registry/git checkout with a symlink to a developer-owned path.
- Dev-link archives a replaced materialized directory outside `custom_nodes`
  under `backups/custom_nodes/`, updates requirements and git provenance, and
  rolls back manifest/symlink/archive state on failure.
- If the target symlink already points to the requested source and manifest
  metadata/requirements are current, dev-link returns an idempotent no-op.
- Development node update re-scans the current checkout, refreshes version from
  the node's `pyproject.toml`, refreshes git remote/branch/commit, replaces the
  dependency group if requirements changed, and syncs uv only when dependency
  changes require it.
- Portable handoff for dev nodes depends on repository URL plus pinned commit;
  the local path itself is not portable.

### Remove, Prune, And Filesystem Sync

- `cg node remove` removes by manifest id or node directory name, case
  insensitive. If no tracked node exists, it can remove an untracked filesystem
  node or `.disabled` directory by name.
- `--untrack` removes manifest tracking without filesystem changes.
- Removing a tracked development node leaves filesystem contents untouched.
- Removing a tracked registry/git node deletes the materialized directory,
  removes manifest tracking, cleans workflow references to the removed id/name,
  cleans orphaned uv sources, and syncs uv.
- `sync_nodes_to_filesystem(remove_extra=False)` installs missing non-dev nodes,
  warns about untracked nodes, and reconstructs missing dev nodes from git
  metadata when possible.
- `remove_extra=True` aggressively deletes untracked custom-node directories
  except known ComfyUI builtins; callers are expected to confirm before invoking
  this mode.
- Prune computes unused nodes from workflow usage and custom-node maps, asks for
  confirmation in CLI unless `--yes`, then reuses the removal path.
- Optional custom-node map entries can make a node prunable; mapped required
  packages are preserved.

### Update Node

- `cg node update <id-or-name>` dispatches by stored source:
  - development: rescan checkout metadata and requirements.
  - registry: query registry for latest or target version, prepare install
    metadata before removing old state, then replace transactionally.
  - git: update from repository source/ref path.
- Registry update uses fresh registry API metadata instead of stale local cache.
- Registry update preserves the old node as `.disabled` during replacement and
  deletes it only after successful install/sync.
- The Manager node update path depends on this registry update behavior; it must
  not remove the running Manager dependency group before preparing replacement
  metadata.

### Workflow Node Resolution

- Workflow resolution deduplicates non-builtin node types, preferring instances
  with ComfyUI `properties.cnr_id`.
- Resolution priority is:
  1. workflow-local `custom_node_map`
  2. ComfyUI `properties.cnr_id` canonicalized through package aliases
  3. generated/global mapping table by exact input signature, then type-only
  4. unresolved/ambiguous/manual resolution
- `custom_node_map` values can be a package id or boolean optional marker.
- Exact, case-sensitive installed aliases are built from manifest id, node
  directory name, registry id, repository URL, and normalized repository URL.
  Ambiguous aliases are removed from the alias map.
- Workflow `nodes` lists are persisted as canonical manifest ids, not aliases.
- A workflow-local custom map can be supplemented by consensus mappings from
  other workflows only when all existing mappings for a node type agree and the
  package is installed.
- Cache context hashes include workflow-local custom maps and consensus mappings
  so stale resolver state is invalidated when mapping context changes.
- Manager-only/uninstallable mappings are treated separately from installable
  candidates; version-gated builtins can produce guidance instead of install
  candidates.

### Manager Node Special Cases

- `Environment.get_manager_status()` checks headless mode first, then a tracked
  `comfygit-manager` node, then legacy symlink installation, then registry
  latest version.
- `Environment.update_manager()` can install, migrate from legacy symlink, or
  update a tracked Manager node. It also ensures PyTorch backend config exists,
  clears the headless marker on install/update, cleans legacy
  `dependency-groups.system-nodes`, and bumps workspace schema during legacy
  migration.
- Manager update accepts a specific version target internally, but current CLI
  parser should be checked: `manager_update()` reads `args.version`, while the
  parser may not expose a version argument.
- The Manager node is still ultimately a registry node as far as
  `NodeManager.update_node()` is concerned, but it has a stricter operational
  requirement: prepare replacement metadata before mutating the currently
  running node/core dependency state.

## Key Code Paths

- Core node lifecycle:
  - `packages/core/src/comfygit_core/managers/node_manager.py`
  - `packages/core/src/comfygit_core/core/environment.py`
  - `packages/core/src/comfygit_core/managers/pyproject_manager.py`
  - `packages/core/src/comfygit_core/models/shared.py`
- Lookup, registry, git, and cache:
  - `packages/core/src/comfygit_core/services/node_lookup_service.py`
  - `packages/core/src/comfygit_core/clients/registry_client.py`
  - `packages/core/src/comfygit_core/repositories/node_mappings_repository.py`
  - `packages/core/src/comfygit_core/analyzers/node_git_analyzer.py`
  - `packages/core/src/comfygit_core/caching/custom_node_cache.py`
- Resolution:
  - `packages/core/src/comfygit_core/services/workflow_resolution_service.py`
  - `packages/core/src/comfygit_core/resolvers/global_node_resolver.py`
  - `packages/core/src/comfygit_core/models/workflow.py`
  - `packages/core/src/comfygit_core/utils/node_identity.py`
  - `packages/core/src/comfygit_core/caching/workflow_cache.py`
- Dependency preview:
  - `packages/core/src/comfygit_core/services/dependency_resolution_preview.py`
  - `packages/core/src/comfygit_core/models/dependency_resolution.py`
- CLI:
  - `packages/cli/comfygit_cli/cli.py`
  - `packages/cli/comfygit_cli/env_commands.py`
  - `packages/cli/comfygit_cli/formatters/error_formatter.py`

## Key Tests

- Lifecycle/add/update/remove:
  - `packages/core/tests/unit/managers/test_node_manager.py`
  - `packages/core/tests/integration/test_node_version_replacement.py`
  - `packages/core/tests/integration/test_registry_node_update_empty_download_url.py`
  - `packages/core/tests/integration/test_dependency_group_removal.py`
  - `packages/core/tests/integration/test_repair_node_removal.py`
  - `packages/core/tests/integration/test_status_uninstalled_nodes.py`
  - `packages/core/tests/unit/core/test_sync_node_dependency_provisioning.py`
- Development nodes:
  - `packages/core/tests/integration/test_dev_node_git_references.py`
  - `packages/core/tests/integration/test_dev_node_improvements.py`
  - `packages/core/tests/unit/test_dev_node_rename_detection.py`
  - `packages/core/tests/integration/test_custom_node_path_preservation.py`
- Resolution/aliases/consensus:
  - `packages/core/tests/unit/utils/test_node_identity.py`
  - `packages/core/tests/unit/test_node_resolution_context.py`
  - `packages/core/tests/unit/managers/test_workflow_manager.py`
  - `packages/core/tests/caching/test_workflow_cache_context_hash.py`
  - `packages/core/tests/integration/test_context_aware_node_resolution.py`
  - `packages/core/tests/unit/resolvers/test_global_node_resolver_v2.py`
  - `packages/core/tests/unit/services/test_workflow_resolution_service.py`
- Criticality/prune/readiness:
  - `packages/core/tests/integration/test_node_prune.py`
  - `packages/core/tests/unit/managers/test_pyproject_manager.py`
  - `packages/core/tests/integration/test_per_environment_manager.py`
- Dependency preview:
  - `packages/core/tests/unit/services/test_dependency_resolution_preview.py`
  - `packages/cli/tests/test_conflict_resolver.py`
- CLI:
  - `packages/cli/tests/test_batch_node_add.py`
  - `packages/cli/tests/test_batch_node_remove.py`
  - `packages/cli/tests/test_manager_commands.py`
  - `packages/cli/tests/test_status_displays_uninstalled_nodes.py`
  - `packages/cli/tests/test_status_disabled_nodes_display.py`

## Existing Clause Coverage

- `CGCORE-LIB-01` / `CGCORE-LIB-02`: Covers core UI-agnostic boundary. Mostly
  upheld by strategies/callbacks, but `NodeManager` still contains some policy
  details that are close to UX semantics through exception contexts.
- `CGCORE-LIB-03`: Covers public entry through `Workspace`/`Environment`.
  Node lifecycle follows this at CLI boundary.
- `CGCORE-DEP-04`, `CGCRIT-NODE-01`, `CGCRIT-NODE-02`,
  `CGSPEC-NODE-03`, `CGSPEC-NODE-04`: Cover custom-node criticality.
- `CGCORE-DEP-05`, `CGCRIT-NODE-03`: Cover graph usage not mutating
  package-level criticality.
- `CGSPEC-NODE-01`: Covers manifest-visible installed nodes.
- `CGSPEC-NODE-02`: Covers registry/git/development cases at a high level.
- `CGSPEC-NODE-02A`: Covers portable git provenance for development nodes.
- `CGSPEC-NODE-02B`, `CGCORE-SYNC-03D`: Cover canonical workflow node ids,
  exact installed aliases, and consensus custom-node mappings.
- `CGSYNC-LIFE-06`: Covers dependency preview/apply semantics and current CLI
  parity gap.
- `CGSYNC-LIFE-07`, `CGCORE-DEP-01`: Cover uv/system resolver normalization,
  which affects node dependency groups.
- `CGSYNC-READY-04`, `CGCORE-DEP-05A`: Cover the boundary between portable
  node provenance/readiness and live ComfyUI import health.

## Gaps And Mismatches

1. **Node add/update/remove lifecycle is underspecified.**
   Existing clauses say nodes are manifest-visible and have source types, but
   they do not promise transactional add/update behavior, duplicate/replacement
   rules, `.disabled` rollback, or remove/untrack filesystem semantics.

2. **Development-node conversion behavior is richer than current truth.**
   `CGSPEC-NODE-02A` covers portable git provenance, but not dev-link
   conversion preserving manifest ids, archiving old materialized checkouts
   outside `custom_nodes`, idempotent relink behavior, or local path
   non-portability during sync/materialization.

3. **Manager special cases are not clearly contracted.**
   Recent Manager self-update failures show this path deserves explicit truth.
   The code now prepares replacement metadata before removing old Manager state,
   but no clause names that as a required invariant.

4. **CLI surface is only indirectly covered.**
   Current truth docs focus on core. CLI flags such as `--strict`,
   `--resolve-with-overlays`, `--extra`, `--all-extras`, `--untrack`,
   `dev-link`, batch add/remove, and Manager status/update behavior are not
   covered except as callers of core.

5. **Batch semantics are easy to misread.**
   Batch add/remove is sequential with per-item failures, not atomic. That should
   be stated to avoid future assumptions.

6. **Dependency preview status should probably move closer to LIVE for core.**
   `CGSYNC-LIFE-06` is marked `PARTIAL` because CLI parity remains future work.
   The body already says core has typed previews and guarded apply. Consider
   splitting core preview/apply as `LIVE` and CLI reviewed-apply parity as
   `PARTIAL`/`PLANNED`.

7. **Node lookup freshness/version semantics are underdocumented.**
   Tests assert update uses fresh registry API metadata and versioned add uses
   requested API version rather than stale cache. This is important release
   behavior and should be promised.

8. **Untracked-node repair/removal semantics are not first-class.**
   Status/repair can warn on untracked nodes, `remove_node()` can delete
   untracked filesystem nodes, and `sync_nodes_to_filesystem(remove_extra=True)`
   can aggressively delete extras. Truth docs should distinguish warn-only sync,
   explicit remove, and confirmed repair cleanup.

9. **Criticality implementation may be ahead of status wording.**
   Several clauses still say centralized readiness/build behavior is follow-on.
   Core readiness appears to cover required custom-node provenance gaps and
   optional-node exclusions for local handoff. Build/deploy consumption may still
   be partial, but local core readiness should be called out as implemented.

10. **Potential CLI mismatch: Manager update version target.**
    `Environment.update_manager(version=...)` and `manager_update()` support a
    version parameter, but the parser surface should be checked before promising
    user-visible `cg manager update --version` or positional version support.

## Proposed Clause Updates

These are proposed IDs and statuses for the integration pass. Exact placement is
probably `docs/specs/environment-sync-lifecycle.md`,
`docs/specs/environment-manifest-model.md`, and `docs/contracts/core/CONTRACT.md`.

### CGSPEC-NODE-05 [LIVE]: Node install and update mutate manifest, filesystem, and uv as one lifecycle

Validation: TEST

Adding or updating a registry/git custom node should prepare lookup metadata,
cached source contents, requirement metadata, manifest changes, filesystem
changes, and uv sync as one guarded operation. On install/update failure, core
should restore the previous manifest state and best-effort restore the previous
materialized node directory.

Suggested evidence:
- `packages/core/tests/integration/test_node_version_replacement.py`
- `packages/core/tests/integration/test_registry_node_update_empty_download_url.py`
- targeted rollback tests in `packages/core/tests/unit/managers/test_node_manager.py`

### CGSPEC-NODE-06 [LIVE]: Node replacement is explicit and version-aware

Validation: TEST

Adding an already installed node without an explicit version should not silently
upgrade or replace it. Same-version adds fail as already installed. Different
version adds may replace regular nodes, while replacing development nodes
requires explicit force or caller confirmation.

Suggested evidence:
- `packages/core/tests/integration/test_node_version_replacement.py`
- `packages/cli/tests/test_batch_node_add.py`

### CGSPEC-NODE-07 [LIVE]: Node removal has distinct untrack, development, tracked, and untracked filesystem modes

Validation: TEST

Removing a node should distinguish manifest untracking from filesystem removal.
Development nodes are untracked without deleting developer-owned files. Tracked
registry/git nodes remove the materialized directory and clean manifest workflow
references and orphaned uv sources. Explicit removal of an untracked filesystem
node may delete that directory, but normal sync without confirmed cleanup should
warn rather than delete untracked nodes.

Suggested evidence:
- `packages/core/tests/integration/test_repair_node_removal.py`
- `packages/core/tests/integration/test_status_uninstalled_nodes.py`
- `packages/cli/tests/test_batch_node_remove.py`

### CGSPEC-NODE-08 [LIVE]: Development node links preserve portable manifest identity

Validation: TEST

Converting a tracked registry/git node to a local development checkout should
preserve the existing manifest node identifier so workflow references remain
valid. The materialized checkout may be replaced by a symlink to a
developer-owned path, and any archived previous copy must live outside
`custom_nodes` so status/sync do not classify it as an active untracked node.

Suggested evidence:
- `packages/core/tests/integration/test_custom_node_path_preservation.py`
- `packages/core/tests/integration/test_dev_node_improvements.py`
- `packages/core/tests/integration/test_dev_node_git_references.py`

### CGSPEC-NODE-09 [LIVE]: Batch node operations are sequential and per-item, not atomic

Validation: TEST

CLI batch add/remove should report per-node success and failure while preserving
the already-completed operations. A batch failure must not imply an automatic
rollback of earlier successful node operations.

Suggested evidence:
- `packages/cli/tests/test_batch_node_add.py`
- `packages/cli/tests/test_batch_node_remove.py`

### CGSYNC-LIFE-06A [LIVE]: Core reviewed dependency apply is fingerprint-guarded

Validation: TEST

Applying a reviewed node dependency change must regenerate the preview under the
environment operation lock and verify the accepted baseline, diff, and proposed
fingerprints before mutating the environment. Stale accepted previews must fail
instead of applying to a changed environment.

Suggested evidence:
- `packages/core/tests/unit/services/test_dependency_resolution_preview.py`
- add/confirm tests for `Environment.apply_reviewed_node_dependency_changes()`
  and `NodeManager.apply_reviewed_dependency_changes()`.

### CGSYNC-LIFE-06B [PARTIAL]: CLI reviewed dependency apply remains future work

Validation: HUMAN_REVIEW

Core and Manager support reviewed dependency apply. CLI may detect and display
dependency conflicts and dependency previews, but it does not yet expose the same
first-class reviewed apply flow.

Suggested evidence:
- `packages/cli/tests/test_conflict_resolver.py`
- existing CLI parser/handler review.

### CGSPEC-NODE-10 [LIVE]: Node lookup for update uses fresh registry metadata

Validation: TEST

Updating a registry node should query the registry for current version/install
metadata instead of relying only on local cache. Version-specific add/update
should use the requested registry version metadata when available.

Suggested evidence:
- `packages/core/tests/integration/test_node_version_replacement.py`
- `packages/core/tests/unit/services/test_node_lookup_api_first.py`
- `packages/core/tests/unit/services/test_node_lookup_version_fallback.py`

### CGCORE-NODE-01 [LIVE]: Manager self-update prepares replacement metadata before mutating current Manager state

Validation: TEST

Because the Manager custom node depends on the running ComfyGit core package,
Manager update must not remove the currently tracked Manager node or its
dependency group before replacement metadata and cached install contents have
been resolved. Manager install/update may use the generic node lifecycle, but it
has this additional ordering invariant.

Suggested evidence:
- `packages/core/tests/integration/test_per_environment_manager.py`
- `packages/cli/tests/test_manager_commands.py`
- add a regression test that failed update preparation leaves the old Manager
  manifest entry and dependency group intact.

### CGSPEC-NODE-11 [LIVE]: Node resolution treats manager-only and version-gated mappings as non-installable guidance

Validation: TEST

Workflow node resolution should distinguish installable package candidates from
manager-only/uninstallable mappings and ComfyUI-version-gated builtin nodes.
Uninstallable matches should produce guidance or version-gated status rather
than being persisted as installable custom-node dependencies.

Suggested evidence:
- `packages/core/tests/unit/resolvers/test_global_node_resolver_v2.py`
- `packages/core/tests/unit/services/test_workflow_resolution_service.py`
- `packages/core/tests/integration/test_context_aware_node_resolution.py`

### CGSPEC-NODE-12 [LIVE]: Workflow resolution cache keys include custom-map and consensus context

Validation: TEST

Workflow resolution cache validity must include workflow-local custom-node maps
and consensus custom mappings derived from other tracked workflows, because those
inputs can change node resolution without changing the workflow JSON itself.

Suggested evidence:
- `packages/core/tests/caching/test_workflow_cache_context_hash.py`

## Tests That Should Reference Clauses

High-value existing tests should add clause comments or docstring references
when next touched:

- `test_node_version_replacement.py`: `CGSPEC-NODE-05`,
  `CGSPEC-NODE-06`, `CGSPEC-NODE-10`.
- `test_registry_node_update_empty_download_url.py`: `CGSPEC-NODE-05`,
  `CGSPEC-NODE-10`.
- `test_dev_node_improvements.py`, `test_dev_node_git_references.py`,
  `test_custom_node_path_preservation.py`: `CGSPEC-NODE-08`,
  `CGSPEC-NODE-02A`.
- `test_batch_node_add.py`, `test_batch_node_remove.py`: `CGSPEC-NODE-09`.
- `test_node_identity.py`, `test_node_resolution_context.py`,
  `test_workflow_manager.py`, `test_workflow_cache_context_hash.py`:
  `CGSPEC-NODE-02B`, `CGCORE-SYNC-03D`, `CGSPEC-NODE-12`.
- `test_dependency_resolution_preview.py`: `CGSYNC-LIFE-06A`.
- `test_per_environment_manager.py`, `test_manager_commands.py`: `CGCORE-NODE-01`.
- `test_node_prune.py`: `CGSPEC-NODE-07`, `CGCRIT-NODE-03`.

## Integration Recommendation

For final truth-layer edits, avoid one large node spec rewrite. The safer pass is:

1. Split the currently broad `CGSYNC-LIFE-06` into core preview/apply `LIVE`
   behavior and caller parity gaps.
2. Add a compact "Custom Node Lifecycle" section to
   `environment-sync-lifecycle.md` for add/update/remove/dev-link semantics.
3. Keep identity, aliases, criticality, and source types in
   `environment-manifest-model.md`.
4. Add one core contract clause for Manager self-update ordering because it is a
   cross-package operational invariant, not just a node lifecycle detail.
5. Add clause IDs to the most relevant tests opportunistically, starting with
   node replacement/update and Manager update regression tests.
