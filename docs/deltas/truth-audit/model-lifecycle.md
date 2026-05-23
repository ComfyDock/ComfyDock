# Model Lifecycle Truth-Layer Audit

Scope: `packages/core` and `packages/cli` model lifecycle behavior, including
model index scanning, source management, downloads/intents, workflow model
parsing/resolution, manual workflow model dependencies, dynamic categories and
model-loader metadata, and unreadable file behavior.

This is a scratch audit. It proposes truth-layer updates but does not edit
normative contracts/specs.

## Current Behavior Summary

ComfyGit currently has three separate model state surfaces:

- The workspace SQLite model index records discovered files by short content
  hash, file size, locations, optional full hashes, and download sources.
- The environment manifest global model table records resolved model metadata
  by hash under `[tool.comfygit.models]`.
- Each workflow manifest entry records graph-derived or user-declared workflow
  model dependencies under `[tool.comfygit.workflows.<name>.models]`.

Model scanning is workspace-local. `Workspace.set_models_directory()` stores the
configured model directory, sets the repository's current directory, scans the
directory, and then asks every environment to update manifest model paths.
`Workspace.sync_model_directory()` rescans the configured directory, updates the
sync timestamp only when there are model index changes, and also refreshes
environment model paths.

The scanner recursively walks the configured models directory, skips hidden
paths, symlinks, directories, very small files, and obvious non-model
extensions. Standard directories use configured extension allowlists.
Non-standard directories are permissive after obvious exclusions, so custom
model folders can still be indexed.

Model identity uses `xxh3_128_sample_v1`: file size plus sampled file chunks
from the beginning, and for large files the middle and end, truncated to a
16-character hex hash. Full BLAKE3/SHA256 fields exist as optional metadata, but
the short hash is the primary index key and manifest identity.

Unreadable files do not abort a full scan. Discovery-time filesystem errors are
skipped. Processing-time failures such as permission denied during hashing are
logged, included in `ScanResult.errors`, and counted in `error_count`. The file
is not indexed, but later files continue.

Workflow model parsing prefers `node.properties.models` because those entries
can carry source URLs and target directories. It then uses model-loader widget
metadata from `ModelConfig`, which merges static mappings with local generated
metadata from `.cec/comfyui_model_loaders.json` and directory aliases from
`.cec/comfyui_folder_paths.json`. Static widget-index fallback remains for older
or less-informative workflows.

Model resolution checks existing manifest context first, then exact path,
reconstructed built-in loader paths, case-insensitive path, filename-only match,
and finally `properties.models` source URLs as download intents. Ambiguous
filename/path matches are returned as candidates. Existing unresolved manifest
entries with sources resume as download intents without reprompting.

Manual workflow dependencies are local-first. `WorkflowManager.add_existing_model_to_workflow()`
requires an already indexed local model identified by hash or relative path.
The workflow entry has `nodes = []`, `declared_by = "manual"`, `status =
"resolved"`, `relative_path`, hash, category, and criticality. The global model
entry is also created or updated, including source URLs already known in the
workspace index. Removal only removes manually declared entries, not graph
derived entries.

Download intents are already implemented for graph-derived models. They are
stored as unresolved workflow model entries with `sources` and `relative_path`.
Batch download execution downloads each intent, indexes the file, adds the
source URL to the index, then updates the workflow model with the real hash and
creates the global manifest model. Failed downloads leave the intent unresolved.

Source management is split across manifest truth and index hints. `model
add-source` / `EnvironmentModelManager.add_model_source()` update the global
manifest model first and also add the source to SQLite when the model exists
locally. Readiness treats manifest model sources as satisfying source proof;
SQLite sources are surfaced as repair candidates but do not by themselves
satisfy manifest readiness.

Dynamic ComfyUI metadata is implemented as local derived state. Environment
creation/import/refresh can extract `.cec/comfyui_folder_paths.json` and
`.cec/comfyui_model_loaders.json`. These files are gitignored. `ModelConfig`
loads and merges them when a `cec_path` is provided. This supports new built-in
folder-backed loaders such as `FrameInterpolationModelLoader`.

Dynamic category behavior is only partial. Static config now includes some newer
directories, and generated folder mappings expand loader directories, but
`ModelWithLocation.category` still calls `get_model_category()` without an
environment-aware `ModelConfig`. As a result, general model index display is not
fully environment-aware for arbitrary active ComfyUI folder paths, although
manual workflow model declarations compensate by using the indexed relative
path's first directory when the static category is `unknown`.

## Key Code Paths

- Model scanning and per-file error handling:
  `packages/core/src/comfygit_core/analyzers/model_scanner.py`
- SQLite model index schema, short hash, locations, sources, cleanup, search:
  `packages/core/src/comfygit_core/repositories/model_repository.py`
- Workspace model index operations and delete flow:
  `packages/core/src/comfygit_core/core/workspace.py`
- Manifest model and workflow model data shapes:
  `packages/core/src/comfygit_core/models/manifest.py`
- Source management and missing-model/import-intent preparation:
  `packages/core/src/comfygit_core/managers/environment_model_manager.py`
- Download service and structured provider/download errors:
  `packages/core/src/comfygit_core/services/model_downloader.py`
- Workflow model parsing:
  `packages/core/src/comfygit_core/analyzers/workflow_dependency_parser.py`
- Model resolution:
  `packages/core/src/comfygit_core/resolvers/model_resolver.py`
- Workflow model manifest writes, manual dependencies, path sync, category
  mismatch, and pending downloads:
  `packages/core/src/comfygit_core/managers/workflow_manager.py`
- Dynamic folder/model-loader extraction:
  `packages/core/src/comfygit_core/utils/folder_paths_extractor.py`
  and `packages/core/src/comfygit_core/utils/model_loader_extractor.py`
- Dynamic config merge:
  `packages/core/src/comfygit_core/configs/model_config.py`
- Source lookup/enrichment:
  `packages/core/src/comfygit_core/services/model_source_lookup.py`
  and `packages/core/src/comfygit_core/services/workflow_analysis_service.py`
- Readiness source warnings:
  `packages/core/src/comfygit_core/services/environment_readiness.py`
- CLI model index/download/source commands:
  `packages/cli/comfygit_cli/global_commands.py`
- CLI workflow model add/list/remove/importance commands:
  `packages/cli/comfygit_cli/env_commands.py`
  and `packages/cli/comfygit_cli/cli.py`

## Key Tests

- Short hash algorithm:
  `packages/core/tests/unit/managers/test_model_short_hash.py`
- Model config dynamic folder/model-loader merge:
  `packages/core/tests/unit/test_model_config_dynamic_loading.py`
- Model loader extraction:
  `packages/core/tests/unit/test_model_loader_extractor.py`
- Generated model-loader workflow parsing:
  `packages/core/tests/unit/analyzers/test_workflow_dependency_parser.py`
- Manual workflow model dependencies:
  `packages/core/tests/unit/managers/test_workflow_manager.py`
  and `packages/cli/tests/test_workflow_model_importance.py`
- Model source management:
  `packages/core/tests/integration/test_model_source_management.py`,
  `test_model_source_preservation.py`, and `test_model_source_removal.py`
- Download intents:
  `packages/core/tests/integration/test_deferred_model_downloads.py`,
  `test_deleted_model_download_intent.py`, and
  `test_download_intent_cache_invalidation.py`
- Category mismatch/path sync:
  `packages/core/tests/integration/test_model_category_mismatch_detection.py`,
  `test_model_path_sync_detection.py`,
  `test_model_resolution_stale_directory.py`, and
  `packages/cli/tests/test_update_workflow_model_paths.py`
- Readiness model source warnings:
  `packages/core/tests/unit/services/test_environment_readiness.py`
- Model delete/index cleanup:
  `packages/cli/tests/test_model_delete_command.py` and
  `packages/core/tests/unit/test_model_repository_cleanup.py`

## Existing Clause Coverage

- `CGCORE-DEP-02 [LIVE]` covers models as external assets tracked by metadata.
- `CGCORE-DEP-02A [PARTIAL]` covers local-first manual workflow model
  dependencies.
- `CGCORE-DEP-02B [PLANNED]` covers generated ComfyUI model-loader metadata.
- `CGCORE-DEP-03 [LIVE]` and `CGCRIT-DEP-*` cover model criticality.
- `CGCORE-DEP-06 [PLANNED]` and `CGSYNC-READY-03 [PLANNED]` cover future
  reusable source-candidate discovery.
- `CGSPEC-MODEL-01 [LIVE]` covers content-oriented model metadata.
- `CGSPEC-MODEL-02 [LIVE]` and `CGSPEC-MODEL-03 [LIVE]` cover required vs
  optional source gaps.
- `CGSPEC-MODEL-03A [PLANNED]` covers dynamic model categories.
- `CGSPEC-MODEL-04 [PARTIAL]` covers manual workflow dependencies.
- `CGSPEC-MODEL-04A [PLANNED]` covers generated built-in model-loader
  discovery.
- `CGSPEC-MODEL-05 [PLANNED]` covers future manual missing-model declarations
  as download intents.
- `CGMAT-API-04 [PLANNED]` covers generated built-in extraction during
  materialization/create/import/repair.
- `CGMAT-FAIL-02 [PARTIAL]` covers explicit materialization model downloads.
- `CGSYNC-GIT-02 [PARTIAL]`, `CGSYNC-READY-01 [PARTIAL]`, and
  `CGSYNC-READY-02 [PARTIAL]` cover source/readiness warnings.

## Gaps And Mismatches

1. Generated model-loader metadata is more implemented than the truth layer says.
   The current code extracts loader metadata, stores it as local derived state,
   loads it through `ModelConfig`, and uses it in workflow parsing. The planned
   clauses should likely move to `PARTIAL` or split into implemented local
   behavior vs future completeness.

2. Dynamic model categories are still partial. Folder path extraction and
   config merge exist, but the general model index model object computes
   category through static config only. The truth layer should not mark this
   `LIVE` until index display/query/category presentation consistently receives
   environment-aware config.

3. The SQLite model index has no direct lifecycle clause. Current docs describe
   model manifest metadata but not the runtime index contract: current-directory
   filtering, multiple locations per hash, location cleanup, source side table,
   short hash algorithm, and scan continuation on per-file errors.

4. Source truth vs source hints should be explicit. Readiness currently treats
   manifest sources as proof and SQLite sources as repair candidates. That is an
   important behavioral boundary that is only indirectly expressed.

5. Download intents are more implemented than `CGSPEC-MODEL-05` implies, but the
   implemented part is graph/property/import based, not manual missing-model
   declaration. The clause should be split so current download intent behavior
   can be `LIVE` or `PARTIAL` while missing manual declaration remains planned.

6. Manual workflow dependencies have real CLI/core support and targeted tests.
   `CGCORE-DEP-02A` and `CGSPEC-MODEL-04` can likely move from `PARTIAL` to
   `LIVE` for the local-first flow if readiness/path checks are accepted as
   complete enough. If build planner consumption is still required, keep
   `PARTIAL` but add a separate `LIVE` clause for core/CLI local behavior.

7. Unreadable model file behavior is not specified. Permission-denied files
   caused user-visible scan errors recently; the intended contract should say
   whether scans continue, whether errors are surfaced, and whether unreadable
   files may be silently skipped. Current behavior is continue-and-count-error
   for processing failures.

8. Model path sync and category mismatch behavior is under-covered. The code
   intentionally updates widget values only for known built-in loaders, skips
   custom nodes, strips built-in base directory prefixes, and reports category
   mismatches as functional workflow issues. These are important reproducibility
   promises and should be explicit.

9. Model downloads are served by `ModelDownloader` and workspace/environment
   facades. The older manager-layer download implementation was intentionally
   removed so future refactors do not preserve unused semantics by accident.

10. Online source lookup is implemented as provider lookup by hash/filename, but
    broader source-candidate discovery from saved workflow text remains planned.
    Existing planned clauses are broadly correct but should mention the current
    narrower service.

## Proposed Clause Updates

### CGSPEC-MODEL-06 [LIVE]: The model index is local derived state
Validation: TEST

The workspace model index should be treated as machine-local runtime state, not
portable manifest truth. It may record multiple locations for one model hash,
filter queries to the configured current models directory by default, and keep
download/source hints that help repair manifest state without satisfying
portable source proof by themselves.

Suggested evidence:
`test_model_directory_switch.py`, `test_model_repository_cleanup.py`,
`test_model_delete_command.py`, and `test_environment_readiness.py`.

### CGSPEC-MODEL-07 [LIVE]: Model scan errors are per-file and nonfatal
Validation: TEST

Scanning a models directory should continue when an individual candidate file
cannot be inspected or hashed. Processing-time errors should be counted and
surfaced in `ScanResult.errors`; the unreadable file must not be indexed as a
valid model.

Suggested evidence:
add/extend a scanner unit test that creates an unreadable file or mocks
`calculate_short_hash()` to raise `PermissionError`, then asserts `error_count`
and continued scanning.

### CGSPEC-MODEL-08 [LIVE]: Short hashes are sampled content identities
Validation: TEST

ComfyGit's primary local model identity is the configured short hash algorithm,
currently `xxh3_128_sample_v1`, which incorporates file size plus sampled file
content and returns a 16-character hex value. Full BLAKE3/SHA256 hashes are
optional verification metadata and should not replace the local primary key
without an explicit migration.

Suggested evidence:
`packages/core/tests/unit/managers/test_model_short_hash.py`.

### CGSPEC-MODEL-09 [LIVE]: Manifest sources are source proof; index sources are repair hints
Validation: TEST

Readiness and handoff checks should treat source URLs recorded in
`[tool.comfygit.models]` as the portable source proof. Source URLs found only in
the local model index may be presented as repair candidates, but should not by
themselves satisfy manifest source readiness.

Suggested evidence:
`packages/core/tests/unit/services/test_environment_readiness.py` and
`packages/core/tests/integration/test_model_source_management.py`.

### CGSPEC-MODEL-10 [PARTIAL]: Download intents preserve target path and source until resolution
Validation: TEST

Workflow model entries may represent pending downloads with `status =
"unresolved"`, `sources`, and `relative_path`. Resolution should resume existing
intents without reprompting, batch downloads when requested, and convert
successful downloads into resolved hash-backed workflow/global model entries.
Failed downloads should leave the intent available for retry.

Current status is `PARTIAL` because several deferred-download tests are still
skipped and manual missing-model declaration by URL remains future work.

Suggested evidence:
`test_deferred_model_downloads.py`, `test_deleted_model_download_intent.py`,
`test_download_intent_cache_invalidation.py`, and
`test_import_download_failures.py`.

### CGSPEC-MODEL-11 [LIVE]: Manual workflow model dependencies are indexed-local first
Validation: TEST

Core and CLI should only create manual workflow model dependencies from a model
already present in the current model index. The dependency should record hash,
filename, category, criticality, resolved status, expected model-relative path,
and `declared_by = "manual"` without inventing graph node references.

This can either replace the local-first portion of `CGSPEC-MODEL-04` or be
added as a narrower live clause while `CGSPEC-MODEL-04` remains a broader
partial clause.

Suggested evidence:
`test_workflow_manager.py::test_add_existing_model_to_workflow_records_manual_dependency`,
`test_add_existing_model_to_workflow_rejects_path_hash_mismatch`, and
CLI manual model command tests.

### CGSPEC-MODEL-12 [PARTIAL]: Dynamic model categories are environment-aware where config is available
Validation: MIXED

When an environment has extracted active ComfyUI folder metadata, model-loader
resolution and workflow category validation should use those directories. General
model index presentation should also become environment-aware, but remains
partial while `ModelWithLocation.category` uses static category lookup.

Suggested evidence:
`test_model_config_dynamic_loading.py`,
`test_model_category_mismatch_detection.py`, and a new test covering model index
display/category for a folder present only in generated folder metadata.

### CGSPEC-MODEL-13 [PARTIAL]: Built-in model-loader metadata is generated local state with static fallback
Validation: MIXED

Create/import/refresh paths should attempt to extract built-in model-loader
metadata from the active ComfyUI checkout into `.cec/comfyui_model_loaders.json`.
Workflow parsing should prefer `properties.models`, then generated loader widget
metadata, then static fallback mappings. The extracted metadata is local derived
state and must not be committed as manifest truth.

Current status is `PARTIAL` rather than `LIVE` because extraction is AST-based
and conservative, and some dynamic loaders may still require manual workflow
declarations.

Suggested evidence:
`test_model_loader_extractor.py`,
`test_model_config_dynamic_loading.py`, `test_workflow_dependency_parser.py`,
and `test_git_manager_gitignore.py`.

### CGSPEC-MODEL-14 [LIVE]: Workflow path sync mutates only known built-in loader widgets
Validation: TEST

When syncing resolved model paths back into workflow JSON, core should update
only known built-in model-loader widget values. It should strip the built-in base
directory prefix expected by ComfyUI loaders, preserve subdirectories, normalize
path separators, and skip custom/unknown node widgets.

Suggested evidence:
`packages/cli/tests/test_update_workflow_model_paths.py`,
`test_model_path_sync_detection.py`, and category mismatch tests for custom
nodes.

### CGSPEC-MODEL-15 [LIVE]: Category mismatch is a functional workflow issue for known loaders
Validation: TEST

For known built-in loaders, a resolved model whose indexed locations do not
include one of the loader's expected directories should be reported as a
functional category mismatch. Custom nodes should be skipped because core does
not know their model search paths.

Suggested evidence:
`packages/core/tests/integration/test_model_category_mismatch_detection.py`.

### CGCORE-DEP-06A [PARTIAL]: Core has provider-backed source lookup but not full source-candidate discovery
Validation: MIXED

Core currently exposes provider-backed lookup by hash/filename and workflow
analysis enrichment. Full source-candidate discovery from saved workflow text,
embedded URLs, deduplication, and repair presentation remains planned shared
logic.

Suggested evidence:
`packages/core/tests/unit/services/test_model_source_lookup.py` and
`packages/core/src/comfygit_core/services/workflow_analysis_service.py`.

## Tests That Should Reference Clauses

- Add `CGSPEC-MODEL-07` to a new unreadable-file scanner test.
- Add `CGSPEC-MODEL-08` to `test_model_short_hash.py`.
- Add `CGSPEC-MODEL-09` to readiness/source-management tests.
- Add `CGSPEC-MODEL-10` to deferred-download and import-download tests.
- Add `CGSPEC-MODEL-11` to manual workflow model core and CLI tests.
- Add `CGSPEC-MODEL-12` and `CGSPEC-MODEL-13` to dynamic config, loader
  extractor, workflow parser, and gitignore tests.
- Add `CGSPEC-MODEL-14` and `CGSPEC-MODEL-15` to path sync and category
  mismatch tests.

## Recommended Integration Plan

1. Split the existing broad model clauses so implemented local behavior can be
   marked `LIVE` without overclaiming future build/provider behavior.
2. Update `CGSPEC-MODEL-03A`, `CGSPEC-MODEL-04A`, `CGCORE-DEP-02B`, and
   `CGMAT-API-04` from purely planned language to current partial behavior.
3. Add the SQLite model index and scan-error clauses because those are real
   reproducibility/debugging contracts not currently documented.
4. Add source-proof vs source-hint wording before expanding readiness or source
   lookup, because that boundary prevents accidental false readiness.
5. Add clause references incrementally to the listed tests as those files are
   touched; do not attempt a full historical annotation pass in one change.
