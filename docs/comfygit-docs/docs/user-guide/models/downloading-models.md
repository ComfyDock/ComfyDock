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

Configure provider credentials through a hidden prompt when needed:

```bash
cg auth set civitai
cg auth login huggingface
```

For non-interactive environments, use `CIVITAI_API_TOKEN`, `HF_TOKEN`, or another
documented provider environment variable. Private Hugging Face or direct-download
access still depends on the URL and account permissions. Use sources that the
runtime can fetch non-interactively before relying on them for handoff.
