# Workflow Resolution

Workflow resolution teaches ComfyGit what a workflow needs.

It can detect many custom node packages and model references automatically, then
record those dependencies in the environment manifest.

## Run Resolution

```bash
cg workflow resolve my-workflow
```

Install resolved missing nodes automatically:

```bash
cg workflow resolve my-workflow --install
```

Skip installation and only update metadata:

```bash
cg workflow resolve my-workflow --no-install
```

Use automatic choices when you do not want prompts:

```bash
cg workflow resolve my-workflow --auto
```

## What Resolution Can Detect

ComfyGit can usually detect:

- built-in ComfyUI nodes
- many custom node package mappings
- built-in model loader widget values
- model folder categories from active ComfyUI metadata
- previous workflow-specific node mappings
- previously declared workflow models

## What Resolution Cannot Know

Some custom nodes load files through code paths that are not visible in the
workflow JSON. ComfyGit should not guess those dependencies.

If the workflow needs a model that resolution does not find, declare it manually:

```bash
cg workflow model add my-workflow \
  --path frame_interpolation/film_net_fp16.safetensors \
  --importance required
```

Read more: [Workflow model dependencies](model-dependencies.md).

## Node Resolution

Custom node resolution maps workflow node types to installable node packages.
When multiple candidates are possible, ComfyGit may ask you to choose.

Persisted workflow node references use canonical manifest package IDs, not
display names or local directory aliases.

## Model Resolution

Model resolution matches workflow references to indexed local files and manifest
metadata.

Required unresolved models or required models without source proof should be
fixed before sharing or materializing a runtime.

## Path Sync

When ComfyGit knows a built-in loader widget and the selected indexed model path,
it can update the workflow JSON to use the correct relative model path.

For custom or unknown widgets, ComfyGit avoids rewriting values it cannot
understand safely.

## After Resolution

```bash
cg status
cg commit -m "Resolve workflow dependencies"
```

!!! note "Media placeholder"
    Add a before/after screenshot showing an unresolved workflow becoming clean
    after node resolution and manual model declaration.
