# Creating Environments

An environment is an isolated ComfyUI installation with a tracked manifest and
derived runtime state.

Use environments when you want to test nodes, work on a workflow, or prepare a
shareable ComfyUI setup without changing another install.

## Create And Use

```bash
cg create my-env --use
```

Create with automatic hardware detection:

```bash
cg create my-env --torch-backend auto --use
```

Create with a specific backend:

```bash
cg create cpu-test --torch-backend cpu
cg create cuda-test --torch-backend cu128
```

## Common Options

```bash
cg create my-env --python 3.11
cg create my-env --comfyui v0.3.68
cg create my-env --no-manager
cg create my-env --yes
```

`--no-manager` is useful for headless or runtime-only environments. Normal
authoring environments install `comfygit-manager` so you can use the ComfyGit
panel inside ComfyUI.

## What Gets Created

ComfyGit creates:

- A tracked environment manifest.
- A ComfyUI checkout.
- A Python virtual environment managed by uv.
- Model links to the workspace model directory.
- Runtime metadata and cache directories.
- The Manager custom node unless skipped.

Only the portable recipe should be committed. Runtime directories can be rebuilt
with sync or repair.

## After Creation

Run ComfyUI:

```bash
cg run
```

Check environment state:

```bash
cg status
```

Commit meaningful changes:

```bash
cg commit -m "Initial environment"
```

## Failed Or Interrupted Creation

If creation is interrupted, ComfyGit may leave partial runtime files. Run:

```bash
cg list
cg repair
```

If an environment does not appear in `cg list`, it did not become a completed
managed environment.

!!! note "Media placeholder"
    Add a short clip of creating an environment, opening ComfyUI, and seeing the
    Manager panel.
