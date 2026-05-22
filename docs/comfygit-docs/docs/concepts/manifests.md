# Manifests

The environment manifest is `pyproject.toml`. It is the portable source of truth
for a ComfyGit environment.

The manifest records:

- Python and ComfyUI intent
- Python dependencies
- custom nodes and source metadata
- workflow entries
- workflow model dependencies
- workflow execution contracts
- model metadata and source proof when available

You normally change the manifest through ComfyGit commands or Manager UI
actions. Direct edits are possible, but they are easier to get wrong because the
manifest ties together nodes, models, workflows, and runtime behavior.

## What Does Not Belong In The Manifest

Machine-local details should not become shared manifest truth:

- hardware-specific PyTorch backend selection
- private local source paths
- credentials
- local model directory paths
- virtualenv contents
- cache state

Local runtime configuration lets the same manifest work on different machines.

Read more: [Environment history](../user-guide/environments/version-control.md)
and [local runtime config](../user-guide/environments/local-runtime-config.md).
