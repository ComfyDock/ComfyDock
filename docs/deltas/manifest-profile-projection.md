# Delta Dossier: Manifest Profile Projection

## Clauses

- CGSPEC-MAN-01
- CGSPEC-MAN-05
- CGSPEC-LOCAL-01
- CGSPEC-LOCAL-02
- CGSYNC-LIFE-03
- CGSYNC-LIFE-05
- CGSYNC-BUILD-01

## Current Evidence

- Code:
  - `packages/core/src/comfygit_core/managers/pyproject_manager.py`
  - `packages/core/src/comfygit_core/managers/overlay_manager.py`
  - `packages/core/src/comfygit_core/managers/pytorch_backend_manager.py`
  - `packages/core/src/comfygit_core/core/environment.py`
  - `packages/core/src/comfygit_core/core/workspace.py`
  - `packages/cli/comfygit_cli/global_commands.py`
  - `packages/cli/comfygit_cli/env_commands.py`
- Specs:
  - `docs/specs/environment-manifest-model.md`
  - `docs/specs/environment-sync-lifecycle.md`
  - `docs/specs/environment-materialization-lifecycle.md`

## Gap

ComfyGit currently has separate mechanisms for related ideas:

- `pyproject.toml` is the portable source manifest committed by environment
  authors.
- PyTorch backend selection is machine-local and materialized only in disposable
  uv projects.
- Overlays can materialize machine-local uv sources, packages, indexes, and
  optional accelerator dependencies during sync/run.
- `comfygit-manager` may be useful in authoring environments but undesirable in
  runtime or deployment materializations.

The smoke-test workflow exposed an awkward authoring/runtime split: users may
author contracts and resolve dependencies with Manager installed, then want to
export, materialize, or run a runtime projection without Manager. Manually
deleting the Manager node entry and dependency group from the committed manifest
works for a fixture, but it creates a misleading environment commit. Checking out
or repairing that commit can remove Manager from the authoring environment even
though the user only wanted a runtime projection.

## Proposed Change

Introduce a core manifest projection service as a deferred architecture slice.
The service would produce an operation-local manifest view from the committed
source manifest plus explicit projection inputs:

1. A named profile, initially at least `authoring` and `runtime`.
2. Machine-local PyTorch backend materialization.
3. Selected overlays, including `.local` and optional accelerator overlays such
   as xformers or sageattention.

The committed source manifest remains authoritative. Projection output is a
temporary sync/materialization artifact, not a file that should be committed.

Initial behavior can stay narrow:

- `authoring` is the default profile and preserves current behavior.
- `comfygit-manager` may be marked as authoring-only.
- `runtime` excludes authoring-only nodes and matching dependency groups.
- Other nodes default to all profiles unless explicitly scoped.
- Overlays remain external/local inputs and are not embedded into the source
  manifest.

Future profile metadata could look like this in the source manifest:

```toml
[tool.comfygit.nodes.comfygit-manager]
name = "comfygit-manager"
profiles = ["authoring"]
```

The projection pipeline would conceptually be:

```text
source pyproject.toml
  -> apply profile filter
  -> materialize PyTorch backend policy
  -> apply selected overlays
  -> write temporary projected manifest for uv/materialize/run/export
  -> discard projected manifest after operation
```

## Authoring And Runtime UX

Default authoring behavior should not change. A user who runs `cg run` or uses
Manager normally should keep Manager installed and active when it is part of the
environment.

Runtime-oriented commands may opt into a projection:

```bash
cg -e my-env run --profile runtime
cg -e my-env export --profile runtime
cg materialize <source> --profile runtime
```

For a local authoring environment, `run --profile runtime` is more complex than
export/materialize because ComfyUI imports whatever is present in
`custom_nodes/`. A future implementation must either:

- create a temporary projected runtime copy, or
- temporarily disable excluded custom nodes, for example by adding `.disabled`,
  and reliably restore them when the profile changes or the command exits.

Because that lifecycle is disruptive, runtime projection for existing local
authoring environments should be deferred until export/materialize projections
are working and tested.

## Non-Goals

- Do not implement this in the current slice.
- Do not make projected manifests commit targets.
- Do not embed `.local`, xformers, sageattention, or other machine-specific
  overlays directly into portable manifest truth.
- Do not require every node or dependency group to declare profiles.
- Do not redesign the PyTorch backend file in this slice; `.pytorch-backend`
  can continue to be the local backend source.

## Affected Files

Likely future implementation areas:

- `packages/core/src/comfygit_core/services/manifest_projection.py`
- `packages/core/src/comfygit_core/managers/pyproject_manager.py`
- `packages/core/src/comfygit_core/managers/overlay_manager.py`
- `packages/core/src/comfygit_core/managers/uv_project_manager.py`
- `packages/core/src/comfygit_core/core/environment.py`
- `packages/core/src/comfygit_core/core/workspace.py`
- `packages/cli/comfygit_cli/cli.py`
- `packages/cli/comfygit_cli/env_commands.py`
- `packages/cli/comfygit_cli/global_commands.py`
- Manager export/materialize/run surfaces if the profile becomes user-facing in
  the panel.

## Validation

Future implementation should add tests proving:

- source `pyproject.toml` is restored or untouched after projection-backed sync.
- `authoring` profile preserves current dependency behavior.
- `runtime` profile excludes `comfygit-manager` without mutating source truth.
- overlays and PyTorch materialization are applied after profile filtering and remain
  absent from committed source manifest state.
- materialization from a runtime projection creates an environment that boots
  without Manager when workflows and contracts do not require it.
- profile changes that temporarily disable custom nodes restore the filesystem
  on success, failure, and interruption if local `run --profile runtime` is
  implemented.
