# Resource Inventory And Reclaim Lifecycle

This specification defines generic ComfyGit inventory and model-reclaim
primitives for adapters that need storage accounting or external ownership
policy. ComfyGit reports environment and filesystem facts. Product-specific
projects, experiments, retention classes, leases, and deletion authorization
remain outside core.

## Inventory

### CGRES-INV-01 [LIVE]: Model inventory groups every indexed location by content identity
Validation: TEST

Workspace model inventory should group repository rows by model hash and expose
file size, short hash, full BLAKE3/SHA-256 values when known, category, all
physical locations, source records, and manifest references from every complete
environment in the workspace.

Inventory is observational. It must not compute missing full hashes, scan model
directories, repair source metadata, or otherwise mutate runtime state unless a
caller invokes those existing operations separately.

### CGRES-INV-02 [LIVE]: Environment inventory derives dependencies from manifest truth
Validation: TEST

Environment inventory should use `Environment.get_manifest_snapshot()` for
ComfyUI revision, Python version, workflows, models, and custom nodes. It should
record the SHA-256 of the tracked `pyproject.toml`, materialized path, completion
state, and bounded storage summaries for the environment, virtual environment,
ComfyUI checkout, per-environment input/output, and shared workspace caches.

Model dependencies should preserve workflow names, criticality, expected
relative path, model hash, and source hints. Custom-node dependencies should
preserve manifest identifier, source kind, version/pinned commit, and
criticality.

### CGRES-INV-03 [LIVE]: Inventory has one stable JSON projection
Validation: TEST

All inventory models should serialize recursively through `to_dict()` methods.
The CLI may expose a combined workspace inventory document, but its JSON fields
must come from the public core models and facade methods. Top-level workspace
inventory and model deletion plan/result documents carry an integer
`schema_version` and stable `kind` discriminator so external adapters can reject
incompatible future shapes explicitly.

## Provider Provenance

### CGRES-SRC-01 [LIVE]: Hugging Face URL structure is retained without credentials
Validation: TEST

For Hugging Face file sources, inventory should expose `repo_id`, `repo_type`,
requested revision, resolved immutable revision, `path_in_repo`, original URL,
and nonsecret provider metadata such as ETag. Provider tokens and signed URL
query parameters must not be serialized.

When a download is requested through a moving revision, core should retain the
resolved commit reported by the successful local-dir download. Existing index
sources without resolved metadata remain valid source hints but must state that
immutable resolution is unknown.

## Reclaim Planning

### CGRES-DEL-01 [LIVE]: Planning never mutates files or index state
Validation: TEST

Planning should resolve a model identifier, snapshot all indexed locations and
references, and select either one explicit location or an explicitly requested
all-location set. A preview may show all locations when selection is omitted,
but that preview is not executable.

The plan should report potential physical bytes rather than promising exact
space recovery. Symlinks, hard links, reflinks, sparse files, filesystem
compression, and concurrent changes can make exact recovery unknowable.

### CGRES-DEL-02 [LIVE]: Default blockers are conservative and generic
Validation: TEST

By default, execution should be blocked when:

- no explicit location/all-locations selection was made;
- a selected location changed after planning;
- the final selected copy lacks a known recovery source or strong content hash;
- one or more ComfyGit environment manifests reference the model; or
- the selected location is outside its indexed base directory.

External callers may explicitly authorize reference/source overrides after
applying their own policy. Core should report such overrides in the result and
must not encode external experiment semantics.

### CGRES-DEL-03 [LIVE]: Applying a plan deletes only selected locations
Validation: TEST

Execution should revalidate the plan, unlink only the selected indexed
locations, clean corresponding location rows, and retain unselected copies.
When no locations remain, existing derived-index cleanup may remove the local
model/source rows; portable environment manifests remain the recovery authority.

## CLI

### CGRES-CLI-01 [LIVE]: Inventory and deletion plans support machine-readable output
Validation: TEST

The CLI should expose workspace inventory as JSON and offer JSON for model
deletion plans/results. `cg model delete IDENTIFIER` is a dry run by default.
Mutation requires `--apply` plus either `--location-id ID` or
`--all-locations`. The existing `--yes` option may remain as a compatibility
alias for explicitly applying all locations, but omission of all apply options
must never delete files.
