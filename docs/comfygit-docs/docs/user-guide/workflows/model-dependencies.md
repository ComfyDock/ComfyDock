# Workflow Model Dependencies

ComfyGit tracks model dependencies at the workflow level. This is how a workflow
can say, "I need this model file to run correctly."

Some dependencies are discovered automatically from loader nodes. Others must be
declared by the user because a custom node loads a file in a way ComfyGit cannot
infer safely.

## The Local-First Flow

For the current workflow, manual model dependencies start from a model that
already exists on your machine.

1. Put the model in the right folder under your configured models directory.
2. Sync the model index.
3. Attach the indexed model to the workflow.
4. Add source information before sharing.

```bash
cg model index sync
cg model index show frame_interpolation/film_net_fp16.safetensors
cg workflow model add my-workflow \
  --path frame_interpolation/film_net_fp16.safetensors \
  --importance required
```

This deliberately proves that the workflow can see the file locally before the
dependency is committed.

## Automatic Dependencies

ComfyGit can detect many built-in loader nodes and folder-backed model widgets.
For example, checkpoint, LoRA, VAE, ControlNet, upscale, and newer ComfyUI model
folders can be detected when ComfyGit has metadata from the active ComfyUI
checkout.

```bash
cg workflow resolve my-workflow
```

Automatic resolution is conservative. If ComfyGit cannot classify a custom node
or dynamic loader safely, it should ask for help or leave the model undiscovered
rather than inventing a dependency.

## Manual Dependencies

Use manual dependencies when:

- A custom node loads a model without a standard loader widget.
- A node expects a model in a newer or custom model folder.
- The workflow works locally, but ComfyGit does not show the model as required.
- A model must exist at a specific relative path for a custom loader.

List the models declared for a workflow:

```bash
cg workflow model list my-workflow
```

Attach by relative path:

```bash
cg workflow model add my-workflow \
  --path loras/style-helper.safetensors \
  --importance flexible
```

Attach by hash:

```bash
cg workflow model add my-workflow \
  --hash abc123def456 \
  --importance required
```

Remove a manually declared model:

```bash
cg workflow model remove my-workflow \
  --path loras/style-helper.safetensors
```

Manual dependencies do not create fake workflow node references. They are
manifest-declared workflow requirements.

## Importance Levels

Model importance tells ComfyGit how serious a missing model is.

| Importance | Meaning |
| --- | --- |
| `required` | The workflow is not reproducible without this model. |
| `flexible` | A similar model may work, but the dependency should stay visible. |
| `optional` | The model can be absent, but users should know behavior may differ. |

Change importance:

```bash
cg workflow model importance my-workflow film_net_fp16.safetensors optional
```

Required models without source proof can block handoff and readiness checks.
Optional models should not block every flow, but they should still be visible.

## Path Matters

For manual dependencies, a matching hash somewhere else is not always enough.
Custom loaders often expect a file at a specific relative path under the models
directory.

For example, a frame interpolation loader may look under:

```text
models/frame_interpolation/
```

If the same file exists under `checkpoints/`, the content hash may match, but the
workflow may still fail because the loader will not search there.

## Add A Source Before Handoff

The local model index can remember source hints, but reproducibility depends on
the manifest having usable source information for required models.

```bash
cg model add-source film_net_fp16.safetensors \
  https://huggingface.co/org/repo/resolve/main/film_net_fp16.safetensors
```

Before pushing or exporting, check status and address required model source
warnings.

```bash
cg status
cg commit -m "Declare workflow model dependencies"
```

!!! note "Media placeholder"
    Add a Manager screenshot showing a custom model in workflow details, its
    importance, and a missing-source warning.
