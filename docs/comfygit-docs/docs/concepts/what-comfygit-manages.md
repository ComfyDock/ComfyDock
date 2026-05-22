# What ComfyGit Manages

ComfyGit is a layer around ComfyUI that records what made a workflow runnable.

ComfyUI gives you the graph editor and inference engine. ComfyGit adds the
portable environment recipe, Git history, model/source metadata, custom node
metadata, and a small runtime surface for serving saved workflow contracts.

The core idea is simple:

- Keep the runnable recipe in git.
- Keep machine-specific runtime state local.
- Keep model bytes outside git, but record enough metadata to find them again.
- Use workflow contracts when a workflow should become a stable Studio/API
  surface.

!!! note "Media placeholder"
    Add a diagram showing ComfyUI, ComfyGit environment manifests, the model
    index, Manager, and `cg serve` as connected pieces.

## Start With These Concepts

Read these in order if you are new to ComfyGit:

1. [Workspaces](workspaces.md) are the machine-local home for ComfyGit.
2. [Environments](environments.md) are portable ComfyUI projects.
3. [Manifests](manifests.md) are the tracked environment recipe.
4. [Models](models.md) explains why model bytes stay outside git.
5. [Custom nodes](custom-nodes.md) explains how node code and dependencies are
   tracked.
6. [Workflows](workflows.md) explains graph tracking, model dependencies, and
   contracts.
7. [Studio and serve](studio-and-serve.md) explains the local contract UI/API
   runtime.

## Portable Vs Local

ComfyGit works because it separates portable truth from local runtime state.

Portable state is the part you can commit, push, import, export, or materialize:

- `pyproject.toml`
- workflow files
- workflow API prompt artifacts for saved contracts
- dependency and custom node metadata
- model metadata and source proof
- shared overlays, when intentionally committed

Local state is the part that belongs to this machine:

- virtualenvs
- ComfyUI checkouts
- installed node directories and symlinks
- model bytes
- caches, logs, local overlays, and hardware-specific runtime settings

This lets two people use the same environment commit on different hardware
without committing different CUDA, ROCm, CPU, or local path settings.

## The Short Version

- Use environments as the thing you share.
- Use the manifest as the portable recipe.
- Use the model index to understand what exists locally.
- Add model sources before handing an environment to someone else.
- Use Manager to author workflow contracts.
- Use `cg serve` when a saved workflow should become a local Studio/API surface.
