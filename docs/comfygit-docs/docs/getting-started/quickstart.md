# Quickstart

This guide gets you from a clean install to a running ComfyGit environment. By
the end, you will have a ComfyUI environment that can be committed, repaired, and
shared.

## Before You Begin

You need:

- A terminal.
- `uv`, the Python package manager ComfyGit uses.
- A directory where your ComfyUI models live, or an empty directory you want
  ComfyGit to use.
- Enough disk space for ComfyUI, Python packages, custom nodes, and model files.

If you already use ComfyUI, point ComfyGit at that existing `models/` directory.
ComfyGit indexes those files instead of copying them.

## 1. Install ComfyGit

```bash
uv tool install comfygit --upgrade
cg --version
```

If `uv` is not installed yet, install it first:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows users can use the PowerShell installer:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 2. Initialize A Workspace

A workspace is machine-local state for environments, model index data, cache, and
logs.

```bash
cg init --models-dir ~/ComfyUI/models --yes
```

Use any path that contains, or should contain, ComfyUI model subfolders such as
`checkpoints`, `loras`, `vae`, `controlnet`, or newer folders such as
`frame_interpolation`.

!!! note "Media placeholder"
    Add a screenshot of the first `cg init` output and the resulting workspace
    layout.

## 3. Create An Environment

```bash
cg create demo --torch-backend auto --use
```

ComfyGit creates an isolated ComfyUI environment, chooses a PyTorch backend for
this machine, installs the ComfyGit Manager custom node by default, and makes the
new environment active.

To skip the Manager for a headless environment:

```bash
cg create demo-headless --no-manager --torch-backend auto
```

## 4. Run ComfyUI

```bash
cg run
```

`cg run` syncs the environment first, then launches ComfyUI. ComfyUI arguments
can be passed after `--`:

```bash
cg run -- --listen 0.0.0.0 --port 8188
```

## 5. Index Models

If you added or moved files outside ComfyGit, rescan the model directory:

```bash
cg model index sync
cg model index status
```

The model index is local state. It helps ComfyGit match workflow references to
files you already have, but source URLs still need to be recorded before you can
claim another machine can reproduce the environment.

## 6. Add Or Open A Workflow

Open ComfyUI, build or load a workflow, and save it. ComfyGit Manager will show
the workflow in the ComfyGit panel.

Resolve dependencies from the CLI when needed:

```bash
cg workflow list
cg workflow resolve my-workflow
```

If a custom node loads a model ComfyGit cannot infer from the graph, attach an
already-indexed local model to the workflow:

```bash
cg workflow model add my-workflow \
  --path frame_interpolation/film_net_fp16.safetensors \
  --importance required
```

!!! note "Media placeholder"
    Add a screenshot of Manager workflow details with the Add Model action.

## 7. Save The Environment

```bash
cg status
cg commit -m "Add my workflow"
```

ComfyGit commits the tracked environment recipe: manifest, workflow files,
dependency metadata, model metadata, and workflow contract artifacts when present.
It does not commit model bytes or local runtime directories.

## What To Read Next

- [Core concepts](../concepts/what-comfygit-manages.md) explains what is portable and what is local.
- [Common workflows](../user-guide/common-workflows.md) gives task recipes.
- [Model dependencies](../user-guide/workflows/model-dependencies.md) explains
  manual workflow models and source proof.
- [Serve workflows](../user-guide/serve-studio/serving-workflows.md) shows how
  to run a workflow through Studio and HTTP.
