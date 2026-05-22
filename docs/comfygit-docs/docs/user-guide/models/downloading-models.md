# Downloading Models

Use ComfyGit downloads when you want the file placed under the configured models
directory and indexed immediately.

```bash
cg model download URL
```

## Choose A Target Path

If the loader expects a specific folder, pass the path explicitly:

```bash
cg model download https://huggingface.co/org/repo/resolve/main/model.safetensors \
  --path frame_interpolation/model.safetensors \
  --yes
```

Or choose a category and let ComfyGit suggest a path:

```bash
cg model download https://civitai.com/api/download/models/123456 \
  --category checkpoints
```

## Why Path Matters

Some loaders only search one model folder. A file with the right hash in the
wrong folder can still fail at runtime.

For workflow dependencies declared manually, keep the file at the relative path
the loader expects.

## After Downloading

Downloads are indexed automatically. You can inspect the result:

```bash
cg model index show checkpoints/model.safetensors
```

If the model is required by a workflow but ComfyGit did not detect it, attach it:

```bash
cg workflow model add my-workflow \
  --path checkpoints/model.safetensors \
  --importance required
```

## Authentication

Configure provider tokens at the workspace level when needed:

```bash
cg config --civitai-key "$CIVITAI_API_KEY"
```

Private Hugging Face or direct-download access depends on the URL and your local
environment. Use URLs that the runtime can fetch non-interactively before relying
on them for handoff.
