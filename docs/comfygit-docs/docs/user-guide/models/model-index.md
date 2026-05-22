# Model Index

The model index is ComfyGit's local inventory of model files on this machine.
It helps ComfyGit find models quickly, avoid duplicate downloads, and match
workflow references to files you already have.

The index is local runtime state. It is not the portable source of truth for an
environment.

## Set The Model Directory

Point ComfyGit at the model folder you want environments to use:

```bash
cg model index dir ~/ComfyUI/models
```

This directory should contain ComfyUI-style subfolders such as:

```text
checkpoints/
loras/
vae/
controlnet/
diffusion_models/
text_encoders/
frame_interpolation/
```

ComfyGit environments link to this model directory. Model bytes are not copied
into every environment.

## Sync The Index

Run a sync after adding, deleting, moving, or fixing permissions on model files:

```bash
cg model index sync
```

Check index status:

```bash
cg model index status
```

Find a model:

```bash
cg model index find filmnet
```

Inspect a specific model:

```bash
cg model index show frame_interpolation/film_net_fp16.safetensors
```

## What The Index Stores

The index records local facts such as:

- file name
- relative model path
- size
- category/folder
- content hash
- known local locations
- source hints, when available

ComfyGit uses content-oriented identity so the same file can be recognized even
when it appears in more than one location.

## Categories Follow ComfyUI

ComfyGit uses model folders to classify files. Newer ComfyUI versions and custom
nodes may introduce folders that older static lists did not know about.

When an environment has an active ComfyUI checkout, ComfyGit can learn folder
metadata from that checkout. Unknown or custom folders are still valid; they just
mean ComfyGit could not classify the folder as a known active ComfyUI category.

## Scan Errors Are Per-File

If one file is unreadable, ComfyGit should keep scanning the rest of the model
directory. The unreadable file is reported and skipped; it is not indexed as a
usable model.

Common causes:

- file owned by another user
- restrictive permissions
- broken symlink
- incomplete download

Fix permissions or ownership, then resync:

```bash
cg model index sync
```

## Index Hints Vs Portable Source Proof

The model index can help repair an environment because it knows what exists
locally. But an environment is reproducible only when the manifest knows how to
acquire required models on another machine.

After ComfyGit detects or declares a required model, add source information
before sharing:

```bash
cg model add-source film_net_fp16.safetensors \
  https://huggingface.co/org/repo/resolve/main/film_net_fp16.safetensors
```

Read more: [Adding sources](adding-sources.md).

!!! note "Media placeholder"
    Add a screenshot of `cg model index status` plus a Manager model index view
    showing categories including `frame_interpolation`.
