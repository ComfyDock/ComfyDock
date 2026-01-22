# Missing Models

> Solutions for workflow model errors, index issues, and download failures.

## Common scenarios

This guide covers troubleshooting for:

- Workflow shows "missing model" or "unresolved model" errors
- Model not found when searching the index
- CivitAI authentication failures (401 errors)
- Download failures (timeouts, 404s, network errors)
- Models downloaded but not appearing in index
- Workflow resolution can't find models

## Workflow shows missing models

**Problem:** Running `cg workflow resolve` or `cg status` shows unresolved models.

**Example error:**

```
⚠️  Partial resolution - issues remain:
  ✗ 3 models not found

Model issues:
  • realistic_vision_v5.safetensors - not in index
  • anime_lora.safetensors - not in index
  • detail_enhancer.safetensors - not in index
```

**Solutions:**

### 1. Check if models directory is configured

```bash
cg model index status
```

If you see "No models directory configured":

```bash
# Set your models directory
cg model index dir ~/ComfyUI/models

# Or if starting fresh
cg model index dir ~/comfygit/workspace/models
```

See [Setting your models directory](../user-guide/models/model-index.md#setting-your-models-directory) for details.

### 2. Sync the index

If you've added models manually (browser downloads, copying files), the index may be out of date:

```bash
cg model index sync
```

This scans your models directory and updates the index with new files.

### 3. Search for the model

Verify if the model exists with a different filename:

```bash
# Search by partial filename
cg model index find realistic

# Search by category
cg model index list | grep checkpoints
```

If found but with different name, the workflow references an outdated filename.

### 4. Download missing models

If models truly don't exist, download them:

```bash
# From CivitAI
cg model download https://civitai.com/api/download/models/128078

# From HuggingFace
cg model download https://huggingface.co/stabilityai/sdxl/resolve/main/sd_xl_base_1.0.safetensors

# From direct URL
cg model download https://example.com/models/model.safetensors
```

See [Downloading Models](../user-guide/models/downloading-models.md) for details.

### 5. Use interactive resolution

Run workflow resolution with interactive prompts:

```bash
cg workflow resolve my_workflow
```

ComfyGit will guide you through finding or downloading missing models.

## Model not found in index

**Problem:** `cg model index find` or `cg model index show` returns no results.

**Example:**

```bash
$ cg model index find sd_xl_base_1.0.safetensors
No models found matching: sd_xl_base_1.0.safetensors
```

**Solutions:**

### 1. Verify models directory is set

```bash
cg model index status
```

**Expected output:**

```
📊 Model Index Status:

   Models Directory: ✓ /home/user/ComfyUI/models
   Total Models: 148 unique models
   Total Files: 152 files indexed
```

If "No models directory configured", set it:

```bash
cg model index dir ~/ComfyUI/models
```

### 2. Check file actually exists

```bash
# List files in models directory
ls ~/ComfyUI/models/checkpoints/

# Or search filesystem
find ~/ComfyUI/models -name "*sd_xl*"
```

If file exists but not in index, run sync:

```bash
cg model index sync
```

### 3. Search with partial matches

Try broader search terms:

```bash
# Too specific - may miss variations
cg model index find sd_xl_base_1.0.safetensors

# Broader search
cg model index find sd_xl

# Even broader
cg model index find xl
```

### 4. List all models to verify

```bash
cg model index list
```

Page through results to see what's actually indexed.

## CivitAI authentication failures

**Problem:** Downloads from CivitAI fail with 401 or "unauthorized" errors.

**Example error:**

```
✗ Download failed: HTTP 401 Unauthorized

Some CivitAI models require authentication.
Get your API token: https://civitai.com/user/account

Set it with:
  export CIVITAI_API_TOKEN='your-token-here'

Or add to your shell config (~/.bashrc or ~/.zshrc):
  export CIVITAI_API_TOKEN='your-token-here'
```

**Solutions:**

### 1. Get CivitAI API token

1. Visit [civitai.com/user/account](https://civitai.com/user/account)
2. Scroll to "API Keys"
3. Click "Add API Key"
4. Copy the generated token

### 2. Set the token temporarily

For current session only:

```bash
export CIVITAI_API_TOKEN='your-token-here'
```

### 3. Set the token permanently

Add to your shell config:

```bash
# For bash
echo 'export CIVITAI_API_TOKEN="your-token-here"' >> ~/.bashrc
source ~/.bashrc

# For zsh
echo 'export CIVITAI_API_TOKEN="your-token-here"' >> ~/.zshrc
source ~/.zshrc
```

### 4. Verify token is set

```bash
echo $CIVITAI_API_TOKEN
```

Should print your token (not empty).

### 5. Retry download

```bash
cg model download https://civitai.com/api/download/models/128078
```

Should now work without 401 error.

## Download failures (timeouts, 404s)

**Problem:** Model downloads fail with network errors, timeouts, or 404 not found.

**Example errors:**

```
✗ Download failed: HTTP 404 Not Found
✗ Download failed: Connection timeout
✗ Download failed: Network unreachable
```

**Solutions:**

### 1. For 404 errors - verify URL

```bash
# Wrong - model page, not download URL
https://civitai.com/models/4201/realistic-vision

# Right - API download endpoint
https://civitai.com/api/download/models/128078
```

**Get correct URLs:**

- **CivitAI:** Right-click "Download" button → Copy link address
- **HuggingFace:** Right-click file download link → Copy link address
- **Direct:** Ensure URL is direct file download, not HTML page

### 2. For timeout errors - retry

Network timeouts are often temporary:

```bash
# Retry the download
cg model download <url>
```

### 3. For large files - check disk space

```bash
# Check available disk space
df -h ~/ComfyUI/models
```

Ensure sufficient space for model file (checkpoints: 2-7GB, loras: 50-200MB).

### 4. Try alternative source

If one source fails, try another:

```bash
# HuggingFace mirror
cg model download https://huggingface.co/user/repo/resolve/main/model.safetensors

# CivitAI mirror
cg model download https://civitai.com/api/download/models/XXXXX

# Direct from creator's hosting
cg model download https://creator-site.com/models/model.safetensors
```

### 5. Manual download workaround

If CLI download fails, download manually:

1. Download model in browser
2. Move to models directory:
   ```bash
   mv ~/Downloads/model.safetensors ~/ComfyUI/models/checkpoints/
   ```
3. Sync index:
   ```bash
   cg model index sync
   ```
4. Add source manually (optional):
   ```bash
   cg model add-source model.safetensors <url>
   ```

## Models downloaded but not appearing

**Problem:** Downloaded a model but it doesn't show in `cg model index list`.

**Solutions:**

### 1. Sync the index

ComfyGit only auto-indexes models downloaded via `cg model download`. For manual downloads:

```bash
cg model index sync
```

### 2. Verify file is in models directory

```bash
# Check if file is in the right place
ls ~/ComfyUI/models/checkpoints/

# Or find it
find ~/ComfyUI/models -name "model_name.safetensors"
```

If file is outside models directory, move it:

```bash
mv /path/to/file.safetensors ~/ComfyUI/models/checkpoints/
cg model index sync
```

### 3. Check models directory matches config

```bash
cg model index status
```

Verify "Models Directory" points to where you downloaded the file.

If mismatch:

```bash
# Set correct directory
cg model index dir /actual/path/to/models
```

### 4. Check file permissions

Ensure ComfyGit can read the file:

```bash
ls -l ~/ComfyUI/models/checkpoints/model.safetensors
```

If no read permission:

```bash
chmod 644 ~/ComfyUI/models/checkpoints/model.safetensors
```

## Workflow resolution issues

**Problem:** `cg workflow resolve` can't find models even though they exist.

**Solutions:**

### 1. Check workflow references correct filenames

Workflows reference models by filename. If you have `realistic_vision_v5.safetensors` but workflow references `realistic_vision.safetensors`, resolution fails.

**Fix:** Rename model to match workflow expectation:

```bash
cd ~/ComfyUI/models/checkpoints
mv realistic_vision_v5.safetensors realistic_vision.safetensors
cg model index sync
```

### 2. Use interactive resolution

Let ComfyGit help you map models:

```bash
cg workflow resolve my_workflow
```

When prompted for ambiguous models, select from available options or provide download URLs.

### 3. Check category mismatches

Models must be in the correct category directory:

```
✗ 1 model in wrong directory

  • sd_xl_base_1.0.safetensors
    Expected: checkpoints/
    Found: loras/sd_xl_base_1.0.safetensors
```

**Fix:** Move to correct directory:

```bash
mv ~/ComfyUI/models/loras/sd_xl_base_1.0.safetensors ~/ComfyUI/models/checkpoints/
cg model index sync
```

### 4. Add model sources for auto-download

If model doesn't exist and you want resolution to download it:

```bash
# Add source to model metadata
cg model add-source model.safetensors https://civitai.com/api/download/models/128078

# Or run interactive add-source
cg model add-source
```

Then resolve will offer to download from registered sources.

## Advanced troubleshooting

### Verify model hash integrity

Check if model file is corrupted:

```bash
# Show model details including hash
cg model index show model.safetensors
```

If hash seems wrong, re-download the model.

### Check workflow requirements

See exactly what models a workflow needs:

```bash
cg workflow show my_workflow
```

Look for "Models used" section to see referenced filenames.

### Debug resolution process

Run resolution with verbose workflow details:

```bash
cg workflow resolve my_workflow
```

Pay attention to specific error messages for each unresolved model.

### Inspect database directly

For advanced users, check the SQLite database:

```bash
# Show database location
cg model index status

# Query database (requires sqlite3)
sqlite3 ~/comfygit/workspace/.metadata/models.db "SELECT filename, hash, relative_path FROM models LIMIT 10;"
```

## Prevention tips

### Keep index synced

After manual downloads or file operations:

```bash
cg model index sync
```

### Use `cg model download`

Prefer CLI downloads over browser downloads - automatic indexing and source registration:

```bash
cg model download <url>
```

### Add sources before sharing

If you plan to export/share environments:

```bash
# Add sources to all models
cg model add-source

# Verify before export
cg export  # Will warn if models lack sources
```

### Standardize filenames

Use consistent, descriptive filenames matching common conventions:

```bash
# Good
sd_xl_base_1.0.safetensors
realistic_vision_v5.safetensors

# Avoid
model_final_2.safetensors
untitled.safetensors
```

### Organize by category

Keep models in correct category directories:

```
models/
├── checkpoints/       # Base models
├── loras/             # LoRA adapters
├── vae/               # VAE encoders
├── controlnet/        # ControlNet models
└── upscale_models/    # Upscalers
```

## Related documentation

<div class="grid cards" markdown>

-   :material-database: **[Model Index](../user-guide/models/model-index.md)**

    ---

    How the model index works and basic operations

-   :material-download: **[Downloading Models](../user-guide/models/downloading-models.md)**

    ---

    Download models from CivitAI, HuggingFace, and URLs

-   :material-link-variant: **[Adding Sources](../user-guide/models/adding-sources.md)**

    ---

    Register download URLs for re-downloads

-   :material-folder-open: **[Managing Models](../user-guide/models/managing-models.md)**

    ---

    Search, organize, and maintain model collection

-   :material-workflow: **[Workflow Resolution](../user-guide/workflows/workflow-resolution.md)**

    ---

    Resolve workflow dependencies automatically

</div>
