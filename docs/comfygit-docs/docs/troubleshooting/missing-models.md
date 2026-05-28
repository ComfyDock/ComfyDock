# Missing Models

Missing model issues can mean different things:

- the file is not on this machine
- the file exists but is not indexed
- the file is unreadable
- the model is in the wrong folder for the loader
- the workflow needs a model ComfyGit did not detect
- the required model has no portable source

## File Exists But Is Not Indexed

```bash
cg model index sync
cg model index find model-name
```

If scan reports permission errors, fix ownership or permissions for the user
running ComfyGit and ComfyUI, then resync.

## Workflow Needs An Undetected Model

Attach an already-indexed model manually:

```bash
cg workflow model add my-workflow \
  --path frame_interpolation/film_net_fp16.safetensors \
  --importance required
```

## Model Is In The Wrong Folder

Some loaders only search one model folder. Move the file to the path the loader
expects, then resync:

```bash
cg model index sync
```

For manual workflow model dependencies, the relative path matters.

## Required Model Has No Source

Add a source before sharing:

```bash
cg model add-source model.safetensors URL
cg status
```

Required model source gaps can block reproducibility. Optional model gaps should
still be visible, but they are less likely to block every flow.
