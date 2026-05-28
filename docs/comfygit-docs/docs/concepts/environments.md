# Environments

An environment is one managed ComfyUI installation. It is the unit you commit,
push, pull, import, export, and materialize.

```text
environments/my-project/
  pyproject.toml          # tracked portable manifest
  workflows/              # tracked editable ComfyUI workflows
  workflow_api/           # tracked API prompt artifacts for contracts
  overlays/               # shared dependency overlays, when used
  ComfyUI/                # derived runtime checkout
  .venv/                  # derived Python environment
  .cec/                   # local runtime/cache state
```

## Portable Environment State

Portable environment state includes:

- the manifest
- workflow files
- workflow contract metadata
- captured API prompt artifacts for contracts
- custom node metadata
- Python dependency metadata
- model metadata and source proof
- Git history

This is the state another machine can use to recreate the environment.

## Derived Runtime State

Derived runtime state includes:

- the ComfyUI checkout
- the Python virtualenv
- installed custom node directories
- symlinks into the shared model directory
- caches and logs

`cg sync`, `cg run`, `cg repair`, and `cg materialize` can recreate or reconcile
this state from the portable recipe plus local settings.

Read more: [Creating environments](../user-guide/environments/creating-environments.md).
