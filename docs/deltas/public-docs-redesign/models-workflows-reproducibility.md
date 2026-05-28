# Public Docs Redesign Audit: Models, Workflows, Reproducibility

## 1. Scope and user story

This slice covers how a user gets from "my workflow runs on my machine" to "this
workflow has explicit, reproducible model requirements." The core story should
be:

1. Point ComfyGit at the local models directory and index what exists.
2. Let workflow analysis discover standard built-in loader references.
3. Manually attach already-indexed models that custom nodes load opaquely.
4. Add portable source URLs to manifest model entries before handoff.
5. Use criticality to distinguish required, flexible, and optional model gaps.
6. Treat unreadable files, wrong model folders, missing source proof, and missing
   exact manual paths as visible readiness issues.

This is a local-first MVP story. A missing model declared only by URL and target
path is still future download-intent behavior, not the primary manual model flow
today.

## 2. Current public docs summary

- `model-index.md` explains the local SQLite index, sampled BLAKE3 identity,
  locations, sources, syncing, categories, duplicate locations, and directory
  switching. It presents the index as shared workspace state and says categories
  come from relative paths (`docs/comfygit-docs/docs/user-guide/models/model-index.md:15`,
  `:286`, `:324`).
- `downloading-models.md` explains direct model downloads, CivitAI/HuggingFace
  sources, target paths, categories, progress, auth config, and troubleshooting.
- `adding-sources.md` explains source URLs as re-download/export/import aids, but
  says sources are stored in the model index and frames export validation around
  index sources (`docs/comfygit-docs/docs/user-guide/models/adding-sources.md:14`,
  `:237`).
- `managing-models.md` is mostly an expanded reference for listing, searching,
  syncing, and inspecting local model inventory.
- `workflow-resolution.md` explains auto/manual workflow resolution, graph-derived
  nodes/models, model path sync, subgraphs, caching, progressive writes, download
  intents, and unresolved dependency handling
  (`docs/comfygit-docs/docs/user-guide/workflows/workflow-resolution.md:1`,
  `:165`, `:243`, `:404`).
- `workflow-model-importance.md` explains required/flexible/optional model
  criticality and `cg workflow model importance`, but does not cover manual model
  declarations (`docs/comfygit-docs/docs/user-guide/workflows/workflow-model-importance.md:1`,
  `:24`).
- `missing-models.md` gives practical troubleshooting for missing index entries,
  permissions, category mismatches, and downloads
  (`docs/comfygit-docs/docs/troubleshooting/missing-models.md:16`, `:370`,
  `:412`).

## 3. Truth-layer/code behavior that must be reflected

- The tracked manifest is `pyproject.toml`; the model index is local derived
  runtime state. Public docs should not imply that index-only data is portable
  truth (`docs/specs/environment-manifest-model.md:8`,
  `docs/specs/environment-manifest-model.md:286`).
- Required models without manifest source proof are reproducibility blockers.
  Optional models can warn without blocking every flow
  (`docs/specs/environment-manifest-model.md:209`,
  `docs/specs/environment-manifest-model.md:216`,
  `docs/contracts/core/CONTRACT.md:237`).
- Manifest model sources are source proof; model-index sources are repair hints
  until copied into manifest/global model metadata
  (`docs/specs/environment-manifest-model.md:303`,
  `packages/core/src/comfygit_core/services/environment_readiness.py:168`,
  `packages/core/tests/unit/services/test_environment_readiness.py:193`).
- Manual workflow model dependencies are supported only for already-indexed local
  models. They record hash, filename, category, criticality, resolved status,
  expected relative path, and `declared_by = "manual"` with no fake node refs
  (`docs/specs/environment-manifest-model.md:240`,
  `docs/contracts/core/CONTRACT.md:201`,
  `packages/core/src/comfygit_core/managers/workflow_manager.py:219`,
  `packages/core/tests/unit/managers/test_workflow_manager.py:123`).
- For manual dependencies, path matters. A matching hash at another path is not
  enough if the custom loader expects a specific folder
  (`docs/specs/dependency-criticality.md:56`,
  `packages/core/tests/unit/managers/test_environment_model_manager.py:8`).
- `workflow_manager.apply_resolution()` preserves manual manifest-only models
  when graph resolution runs again
  (`packages/core/src/comfygit_core/managers/workflow_manager.py:1548`,
  `packages/core/tests/unit/managers/test_workflow_manager.py:734`).
- CLI now has `cg workflow model list`, `add`, `remove`, and `importance`
  subcommands. `add` accepts `--hash` or `--path` and `--importance/--criticality`
  (`packages/cli/comfygit_cli/cli.py:1064`,
  `packages/cli/comfygit_cli/env_commands.py:3471`,
  `packages/cli/tests/test_workflow_model_importance.py:227`).
- Model scanner errors are per-file and nonfatal. Unreadable files are counted
  and surfaced but not indexed as valid models
  (`docs/specs/environment-manifest-model.md:295`,
  `packages/core/src/comfygit_core/analyzers/model_scanner.py:144`,
  `packages/core/src/comfygit_core/analyzers/model_scanner.py:262`).
- Category/folder metadata is now partly environment-aware. Generated
  `comfyui_folder_paths.json` and `comfyui_model_loaders.json` can add active
  ComfyUI categories and folder-backed loader widgets
  (`docs/specs/environment-manifest-model.md:223`,
  `packages/core/src/comfygit_core/configs/model_config.py:68`,
  `packages/core/src/comfygit_core/configs/model_config.py:199`).
- Built-in loader discovery should prefer generated ComfyUI metadata when
  available, including newer loaders such as frame interpolation. The current
  extractor parses ComfyUI `INPUT_TYPES`/schema code that calls
  `folder_paths.get_filename_list(...)`
  (`docs/specs/environment-manifest-model.md:256`,
  `packages/core/src/comfygit_core/utils/model_loader_extractor.py:44`,
  `packages/core/tests/unit/analyzers/test_workflow_dependency_parser.py:159`).
- Path sync is intentionally limited to known built-in model-loader widgets and
  must skip custom/unknown widgets
  (`docs/specs/environment-manifest-model.md:321`,
  `docs/comfygit-docs/docs/user-guide/workflows/workflow-resolution.md:276`).

## 4. Gaps/stale/misleading content with file references

- Source docs blur local index hints and portable manifest proof. `adding-sources`
  says sources are stored in the model index and enable export validation
  (`docs/comfygit-docs/docs/user-guide/models/adding-sources.md:16`,
  `:25`), but readiness now treats manifest sources as proof and index sources
  only as repair candidates.
- Workflow docs do not explain the new manual dependency escape hatch. The
  importance page only covers changing importance for models already discovered
  in the workflow (`workflow-model-importance.md:24`), and resolution says model
  dependencies come from workflow JSON/widget analysis (`workflow-resolution.md:7`,
  `:165`).
- `workflow-resolution.md` overstates custom-node model detection. It says custom
  nodes are scanned for file extensions in widgets (`workflow-resolution.md:177`),
  but the current truth layer says opaque/custom loaders require manual
  declarations when core cannot infer them safely.
- Download-intent docs should be narrowed. The page describes entering a URL for
  a missing model during resolution as a normal path (`workflow-resolution.md:404`),
  while the truth layer says declaring missing manual models by URL/path remains
  planned; current manual add is indexed-local first
  (`docs/specs/environment-manifest-model.md:278`).
- Category docs are too static. `model-index.md` lists a fixed category table and
  "Plus 8 more" (`model-index.md:286`) but does not explain active ComfyUI folder
  paths, generated categories such as `frame_interpolation`, or valid custom/
  unknown categories.
- Missing-model troubleshooting recommends renaming files to match workflow
  filenames as the first fix (`missing-models.md:390`). The safer modern story is:
  sync index, resolve/select indexed model, ensure loader-specific relative path,
  and only move/rename when ComfyUI's loader path really requires it.
- Permissions troubleshooting shows `chmod 644` only (`missing-models.md:370`).
  It should explain that unreadable files are skipped/nonfatal scan errors, that
  ownership may need fixing, and that the file must be readable by the user
  running ComfyGit/ComfyUI.
- The importance page says optional missing models produce "No warning" during
  commit/import (`workflow-model-importance.md:149`). Truth says optional gaps
  should remain visible warnings, even if non-blocking.
- Public docs still mention editing `.cec/pyproject.toml` manually for clearing
  importance (`workflow-model-importance.md:247`). Prefer documenting supported
  CLI/Manager operations and avoid encouraging direct manifest edits for routine
  workflows.

## 5. Proposed public-doc pages/sections and where each concept should live

- `user-guide/models/model-index.md`
  - Keep as local inventory/index mental model.
  - Add "Index is local state, not portable proof."
  - Add "Unreadable files and scan errors" subsection.
  - Update categories to "folder-path categories from active ComfyUI, with static
    fallback" and include examples like `frame_interpolation`,
    `diffusion_models`, `text_encoders`, and custom folders.

- `user-guide/models/model-sources.md` or revised `adding-sources.md`
  - Make this the canonical page for source proof.
  - Separate "source saved in local index" from "source recorded in manifest for
    handoff/readiness."
  - Explain source candidates/repair hints and why ComfyGit asks users to confirm
    or add sources before claiming reproducibility.

- `user-guide/workflows/model-dependencies.md` (new or replacement for
  `workflow-model-importance.md`)
  - Define workflow model dependencies as graph-discovered or manually declared.
  - Explain local-first manual add: model must exist in the model index first.
  - Explain manual dependencies have no node refs and are for custom nodes or
    opaque loaders.
  - Include required/flexible/optional criticality in the same page so users
    understand declaration plus importance together.

- `user-guide/workflows/workflow-resolution.md`
  - Keep for automatic graph/node/model resolution, cache behavior, path sync,
    and built-in loader awareness.
  - Add a short "What automatic resolution cannot know" section that points to
    manual workflow model declarations.
  - Replace static "custom nodes are scanned" wording with "custom nodes may be
    detected only when there is safe metadata; otherwise declare manually."

- `troubleshooting/missing-models.md`
  - Reorganize by symptom:
    - Model file exists but is not indexed.
    - Scan reports permission denied.
    - Workflow needs a model that graph analysis did not discover.
    - Model source warning/readiness blocker.
    - Category/path mismatch for known loaders.
  - Prefer "fix index/path/source state" over filename renames as the default
    guidance.

- CLI reference
  - Regenerate or hand-update `workflow model` docs to include `list`, `add`,
    `remove`, and `importance`.

## 6. Safe command examples to publish

```bash
# Check where ComfyGit is indexing models from
cg model index status

# Point the workspace at an existing ComfyUI models directory
cg model index dir ~/ComfyUI/models

# Rescan after copying, moving, or fixing permissions on model files
cg model index sync

# Inspect an indexed model by filename, hash prefix, or relative path
cg model index show frame_interpolation/film_net_fp16.safetensors

# Add a source URL to a known model
cg model add-source film_net_fp16.safetensors https://huggingface.co/org/repo/resolve/main/film_net_fp16.safetensors

# List models declared for a workflow
cg -e my-env workflow model list my-workflow

# Manually declare an already-indexed model required by a workflow
cg -e my-env workflow model add my-workflow --path frame_interpolation/film_net_fp16.safetensors --importance required

# Mark a declared model as optional/flexible/required
cg -e my-env workflow model importance my-workflow film_net_fp16.safetensors optional

# Remove a manually declared workflow model dependency
cg -e my-env workflow model remove my-workflow --path frame_interpolation/film_net_fp16.safetensors

# Run automatic workflow dependency resolution
cg -e my-env workflow resolve my-workflow
```

Avoid publishing examples that imply users can manually declare a missing model
by URL/path today. The supported manual dependency command attaches indexed local
models.

## 7. Open questions/risks

- Which public term should win: "importance" (current CLI wording) or
  "criticality" (truth-layer/internal wording)? Recommendation: user docs say
  "importance" first and explain it maps to manifest criticality.
- Should docs expose source-candidate behavior explicitly, or keep it as UI/CLI
  presentation detail? Recommendation: explain enough to avoid confusion when a
  local index source is suggested but readiness still asks to save source proof.
- Manager docs may need a matching page for the workflow-detail "Add Model" UI.
  This audit only covers public core/CLI docs, but the user journey is likely
  Manager-first.
- Download intents are partially implemented for graph-discovered missing models,
  but missing manual-by-URL declarations are planned. Public docs should avoid
  overpromising until the Manager/CLI flow is intentionally supported.
- Built-in loader metadata is generated local state and partial coverage. Docs
  should say ComfyGit understands many folder-backed built-in loaders from the
  active ComfyUI checkout, not "all loaders forever."
