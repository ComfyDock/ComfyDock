# Managing Models

Model management in ComfyGit has two sides:

- local inventory in the model index
- portable workflow requirements in the environment manifest

## Inspect Local Inventory

```bash
cg model index status
cg model index list
cg model index find sdxl
cg model index show checkpoints/sd_xl_base_1.0.safetensors
```

Show duplicates:

```bash
cg model index list --duplicates
```

## Rescan After File Changes

```bash
cg model index sync
```

Run this after manually copying, moving, deleting, or fixing model files.

## Delete A Model File

```bash
cg model delete checkpoints/old-model.safetensors
```

Skip confirmation only when you are sure:

```bash
cg model delete checkpoints/old-model.safetensors --yes
```

Deleting a local file does not automatically remove historical manifest
references from old commits. Check workflows before deleting models that may
still be required.

## Add Sources

```bash
cg model add-source model.safetensors https://example.com/model.safetensors
```

Source information is what makes required models reproducible during export,
import, materialization, and build planning.

## Attach Models To Workflows

If a workflow needs a model that graph analysis did not discover:

```bash
cg workflow model add my-workflow \
  --path loras/detail-helper.safetensors \
  --importance required
```

Read more: [Workflow model dependencies](../workflows/model-dependencies.md).
