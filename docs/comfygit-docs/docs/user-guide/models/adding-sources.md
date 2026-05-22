# Adding Model Sources

A model source tells ComfyGit where a model can be acquired again.

This matters because model bytes are not committed to Git or bundled into normal
environment exports. If a required model has no usable source, another machine
may not be able to recreate the workflow.

## Add A Source

```bash
cg model add-source film_net_fp16.safetensors \
  https://huggingface.co/org/repo/resolve/main/film_net_fp16.safetensors
```

You can identify a model by filename, hash prefix, or relative path:

```bash
cg model add-source frame_interpolation/film_net_fp16.safetensors URL
cg model add-source abc123def456 URL
```

If you omit arguments, ComfyGit can prompt interactively:

```bash
cg model add-source
```

## Source Hints Vs Source Proof

The local model index may know useful source hints. The environment manifest is
what handoff and readiness checks use to decide whether a required model is
portable.

When ComfyGit warns that a required model has no source, add or confirm a source
for the model in the environment you plan to commit.

## Good Source URLs

Prefer URLs that can be fetched non-interactively:

- direct Hugging Face `resolve/main/...` file URLs
- Civitai API download URLs
- stable direct-download URLs controlled by your team

Avoid browser-only pages unless ComfyGit can resolve them into a direct download.

## Check Before Sharing

```bash
cg status
cg commit -m "Add model sources"
```

Required model source gaps should be fixed before exporting, pushing for handoff,
or materializing a runtime.

Optional model gaps may be non-blocking, but they should still be visible to
users because outputs may differ.
