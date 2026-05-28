# Manifest Reference

The environment manifest is the tracked `pyproject.toml` file at the root of a
ComfyGit environment repository.

It is the portable recipe for the environment. Sync, repair, export, import,
materialize, Manager, and `cg serve` all read from this state.

## Major Manifest Responsibilities

The manifest records:

- project metadata and Python dependency declarations
- ComfyUI version intent
- custom node package metadata
- custom node dependency groups
- workflow entries
- workflow model dependencies
- workflow execution contracts
- model metadata and source proof
- shared overlays, when intentionally committed

## Local State Is Separate

The manifest should not contain machine-local runtime state:

- credentials
- local model directory paths
- virtualenv contents
- installed runtime checkouts
- local-only overlays
- hardware-specific PyTorch backend choices

Those values are injected during sync/run/materialization from local
configuration.

## Inspecting The Manifest

```bash
cg manifest
cg manifest --pretty
cg manifest --section tool.comfygit
cg manifest --ide
```

Use ComfyGit commands or Manager actions for normal edits. Direct manifest edits
should be followed by `cg sync` or `cg repair` to reconcile runtime state.

## Related Pages

- [Manifests concept](../concepts/manifests.md)
- [Environment history](../user-guide/environments/version-control.md)
- [Environment commands](../cli-reference/environment-commands.md)
