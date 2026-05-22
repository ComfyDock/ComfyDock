# ComfyGit Overview

ComfyGit helps you turn a working ComfyUI setup into a reproducible
environment, a tracked workflow, and, when you are ready, a local Studio or API
surface for running that workflow.

ComfyUI is flexible because everything can change: custom nodes, Python
packages, model files, workflow JSON, and runtime settings. ComfyGit gives those
moving parts a shape you can inspect, commit, share, repair, and run again.

!!! note "Media placeholder"
    Add a short hero video showing a workflow moving from ComfyUI to ComfyGit
    Manager to `cg serve` Studio.

## Start Here

If you are new to ComfyGit, follow the quickstart first:

```bash
uv tool install comfygit --upgrade
cg init --models-dir ~/ComfyUI/models --yes
cg create demo --torch-backend auto --use
cg run
```

The quickstart walks through installing the CLI, creating an environment, using
the Manager panel, indexing models, tracking a workflow, and committing the
environment.

[Continue with the quickstart](quickstart.md)

## What ComfyGit Tracks

ComfyGit separates portable environment truth from local runtime state.

Portable truth lives in the environment repository: the manifest, workflows,
model metadata, custom node metadata, workflow contracts, and Git history. This
is what you commit, push, export, import, and materialize.

Local runtime state is everything ComfyGit can recreate or adapt for the current
machine: the virtual environment, ComfyUI checkout, installed node directories,
model symlinks, caches, local overlays, and selected PyTorch backend.

That split is the reason ComfyGit can answer practical questions:

- Which custom nodes does this workflow need?
- Which models are required, optional, or missing a source?
- Can another machine recreate this environment?
- What changed since the last working commit?
- Can this workflow be served as a small Studio or API?

## Common Paths

### I want to run ComfyUI safely

Create an isolated environment, install nodes, sync dependencies, and run
ComfyUI without mutating a global install.

[Create and run environments](../user-guide/environments/creating-environments.md)

### I want to share a workflow

Track the workflow, resolve node and model dependencies, add missing model
sources, commit the result, then push or export it.

[Track workflow dependencies](../user-guide/workflows/workflow-resolution.md)

### I need a model ComfyGit did not detect

Index the model locally, attach it to the workflow as a manual dependency, and
add a source before handoff.

[Declare workflow model dependencies](../user-guide/workflows/model-dependencies.md)

### I want a workflow-specific UI or API

Use ComfyGit Manager to save a workflow contract, then run `cg serve` to host the
packaged Studio and contract-shaped endpoints.

[Serve workflows with Studio](../user-guide/serve-studio/serving-workflows.md)

### I need a headless runtime

Use `cg materialize` to hydrate a committed environment in Docker, CI, a remote
machine, or a runtime container without authoring prompts.

[Materialize runtime environments](../user-guide/collaboration/materialize.md)

## Next Steps

- [Core concepts](../concepts/what-comfygit-manages.md) explains the mental model.
- [Common workflows](../user-guide/common-workflows.md) gives task-oriented recipes.
- [CLI reference](../cli-reference/global-commands.md) lists command syntax.
- [Troubleshooting](../troubleshooting/common-issues.md) covers common failure modes.
