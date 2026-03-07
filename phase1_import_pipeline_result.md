# Platform Spec Audit + Phase 1 Import Pipeline Work

## Part 1: Spec Audit

The overall approach is sound. The thin-export/heavy-import split matches the real constraint in this domain: the only place you can safely resolve custom-node Python dependencies, PyTorch overlays, model availability, and ComfyUI runtime behavior is on the target machine and provider image. Building persistent pods before serverless also looks correct, because pods are the validation and hydration lane and serverless should consume already-proven environments rather than becoming the place where resolution bugs are debugged.

The two main gaps I would address in the implementation plan are around runtime identity and orchestration state. First, a "hydrated" repo is only portable if the target image/runtime contract is stable: Python version, OS/image contents, PyTorch backend, and provider-specific overlays all affect whether `uv.lock` and node dependency groups remain valid. The spec should treat hydration as scoped to a base image/runtime contract, not universally portable. Second, Phase 2 should explicitly include a durable job/state machine for long-running imports, pod startup, retries, and resumability; provider APIs and `cg import` are both multi-minute workflows, so this needs to exist before the dashboard becomes a thin shell over fragile ad hoc calls.

One other missing consideration is credential handling. Model source URLs, private GitHub repos, and provider execution all imply secrets that must not be committed into thin specs or hydrated repos. Secret injection/redaction is worth pulling earlier, at least into the Phase 2 pod-import design, because it affects the repo format and import contract.

## Part 2: Implementation Summary

### Fix 12.3: Node Dependency Provisioning During Import

Implemented in `comfygit` and committed as `ca0f67b` (`Provision missing node dependencies during sync`).

Changes:

- Added `NodeManager.provision_missing_node_dependencies()` in [packages/core/src/comfygit_core/managers/node_manager.py](/data/projects/comfygit-ai/comfygit/packages/core/src/comfygit_core/managers/node_manager.py).
- The new method:
  - walks tracked non-development nodes
  - computes the existing hash-based dependency group name via `generate_group_name()`
  - skips nodes whose group already exists
  - scans the extracted node directory with `node_lookup.scan_requirements(..., package_config=self.package_config)`
  - stages requirements into `pyproject.toml` with `uv.add_requirements_with_sources(..., no_sync=True, raw=True)`
  - records an empty dependency group for nodes with no Python requirements so later syncs do not rescan forever
  - updates `dependency_sources` when new UV sources are introduced
- Wired this into [packages/core/src/comfygit_core/core/environment.py](/data/projects/comfygit-ai/comfygit/packages/core/src/comfygit_core/core/environment.py) immediately after `sync_nodes_to_filesystem()`.
- After staging all missing groups, `Environment.sync()` now runs one final `uv sync` with PyTorch injection and the same sync overlays/extras context, instead of doing per-node syncs.
- Hydrated exports stay a no-op because existing dependency groups short-circuit the new staging pass.

Tests added:

- [packages/core/tests/unit/managers/test_node_manager.py](/data/projects/comfygit-ai/comfygit/packages/core/tests/unit/managers/test_node_manager.py)
- [packages/core/tests/unit/core/test_sync_node_dependency_provisioning.py](/data/projects/comfygit-ai/comfygit/packages/core/tests/unit/core/test_sync_node_dependency_provisioning.py)

### Fixes 12.1, 12.2, 12.4: Cloud Export Model Status + ComfyUI Version Floor

I could not apply these directly because the sandbox allows reads from `comfygit-cloud` but denies writes outside the current writable repo root. I prepared the exact patch here:

- `/tmp/comfygit-cloud-phase1-export.patch`

That patch does the following in `comfygit-cloud`:

- changes exported models with source URLs to `status = "unresolved"` so import treats them as download intents
- resolves `comfyui_version = "latest"` to a concrete release tag via the GitHub client, with fallback to `v0.11.0`
- normalizes bare semver strings like `0.12.1` to `v0.12.1`
- floors release tags below `v0.11.0` up to `v0.11.0`
- adds focused router tests for both behaviors

## Risks / Edge Cases

- If node extraction fails and the node directory is still missing after `sync_nodes_to_filesystem()`, the new provisioning pass logs and skips that node; the final sync only covers nodes that actually exist on disk.
- If the final batched UV sync fails, the dependency groups remain staged in `pyproject.toml`; this matches existing sync behavior (non-transactional repair path) but should be validated in real import logs.
- The proposed cloud version-floor logic only floors semver-style release tags. Branches or commit SHAs are left untouched because they cannot be compared safely as releases.
- Recording empty dependency groups is intentional; without that, thin imports of nodes with no Python requirements would be rescanned on every sync.

## Validation / What To Test

- Thin web export with model URLs:
  - exported workflow models should be `status = "unresolved"` with `sources`
  - `cg import` should download those models on `model_strategy=all`
- Thin web export with old or missing ComfyUI version:
  - export should emit a concrete release tag
  - anything below `v0.11.0` should be bumped to `v0.11.0`
- Thin import of a node with `requirements.txt`:
  - node files install
  - dependency group is added once
  - exactly one follow-up UV sync happens after staging
- Hydrated export import:
  - existing node dependency groups should cause the new provisioning step to no-op
  - no extra follow-up UV sync should run
- Node with no Python requirements:
  - import should record an empty dependency group and not rescan on later syncs
- Full end-to-end:
  - `cg import`
  - `cg run`
  - workflow loads and node imports succeed without `ModuleNotFoundError`

## Verification Run

Executed successfully in `comfygit`:

- `uv run pytest packages/core/tests/unit/managers/test_node_manager.py -k 'provision_missing_node_dependencies or sync_uv_adds_system_group_when_missing' -v`
- `uv run pytest packages/core/tests/unit/core/test_sync_node_dependency_provisioning.py -v`
- `uv run pytest packages/core/tests/unit/core/test_import_download_failures.py packages/core/tests/unit/core/test_import_no_manager.py -v`
- `uv run pytest packages/core/tests/integration/test_export_import.py packages/core/tests/integration/test_import_comfyui_version_bug.py -v`

Push status:

- `git push origin dev` failed from this environment because outbound network/DNS is blocked (`Could not resolve host: github.com`).
