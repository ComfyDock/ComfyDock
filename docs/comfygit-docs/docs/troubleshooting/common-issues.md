# Common Issues

> Quick solutions for frequently encountered ComfyGit problems.

This page helps you quickly diagnose and fix common issues. For each problem, you'll find a quick fix if it's simple, or a link to a detailed troubleshooting guide for complex issues.

## Quick diagnosis table

Use this table to identify your issue and find the right solution:

| Symptom | Most Likely Cause | Quick Fix |
|---------|-------------------|-----------|
| `cg: command not found` | PATH not configured | Restart terminal or [fix PATH](#cg-command-not-found) |
| `Workspace not initialized` | No workspace created | Run `cg init` |
| `Environment 'X' not found` | Wrong env name or not created | Check `cg list` or create with `cg create` |
| `Dependency conflict` error | Incompatible package versions | See [Dependency Conflicts](dependency-conflicts.md) |
| `No module named 'torch'` | Virtual environment broken | [Repair environment](#environment-wont-start) |
| `Missing model` in workflow | Model not downloaded/indexed | See [Missing Models](missing-models.md) |
| `uv` resolution fails | Package version incompatible | See [UV Errors](uv-errors.md) |
| ComfyUI won't start | Port conflict or corrupted env | [Check logs and repair](#comfyui-wont-start) |
| `out of sync` in status | Config drift | Run `cg repair` |
| Git errors (detached HEAD) | Manual git operations | See [Environment Corruption](environment-corruption.md) |

## Installation issues

### cg command not found

**Problem:** Running `cg` shows "command not found"

**Diagnosis:**

```bash
cg --version
# bash: cg: command not found
```

**Solutions:**

=== "Option 1: Restart terminal"

    UV adds itself to PATH, but you need to restart your shell:

    ```bash
    # Close terminal and open new one
    # Or source the config manually:

    # For bash
    source ~/.bashrc

    # For zsh
    source ~/.zshrc
    ```

=== "Option 2: Check UV installation"

    Verify UV is installed:

    ```bash
    uv --version
    ```

    If UV is missing, [install it first](../getting-started/installation.md#step-1-install-uv).

=== "Option 3: Reinstall ComfyGit"

    ```bash
    # Ensure UV is working
    uv --version

    # Reinstall ComfyGit
    uv tool install comfygit --force

    # Verify
    cg --version
    ```

=== "Option 4: Check PATH manually"

    UV tools should be in `~/.local/bin`:

    ```bash
    # Check if cg exists
    ls -la ~/.local/bin/cg

    # Add to PATH if needed (add to ~/.bashrc or ~/.zshrc)
    export PATH="$HOME/.local/bin:$PATH"
    ```

See the [Installation guide](../getting-started/installation.md#troubleshooting-installation) for more details.

---

### Workspace not initialized

**Problem:** Commands fail with "No workspace found"

**Diagnosis:**

```bash
$ cg list
✗ No workspace found. Initialize one with: cg init
```

**Solution:**

Initialize a workspace (required before using ComfyGit):

```bash
# Initialize in default location (~/comfygit)
cg init

# Or specify custom path
cg init /path/to/workspace
```

See [Core Concepts - Workspace](../getting-started/concepts.md#workspace) for more information.

---

### Python version too old

**Problem:** Installation fails with "Requires Python 3.10+"

**Solution:**

Install Python 3.10 or newer:

=== "Ubuntu/Debian"
    ```bash
    sudo add-apt-repository ppa:deadsnakes/ppa
    sudo apt-get update
    sudo apt-get install python3.11
    ```

=== "macOS"
    ```bash
    brew install python@3.11
    ```

=== "Windows"
    Download from [python.org](https://www.python.org/downloads/)

Then reinstall ComfyGit:

```bash
uv tool install comfygit --force
```

---

## Environment issues

### Environment not found

**Problem:** Commands fail with "Environment 'X' not found"

**Diagnosis:**

```bash
$ cg -e production status
✗ Environment 'production' not found
```

**Solution:**

Check available environments:

```bash
# List all environments
cg list

# If empty, create your first environment
cg create production

# If you meant a different environment
cg -e correct-name status

# Or set a default environment
cg use production
cg status  # Now uses 'production' by default
```

---

### Environment won't start

**Problem:** `cg run` fails with import errors or module not found

**Example errors:**

```
ModuleNotFoundError: No module named 'torch'
ImportError: cannot import name 'X' from 'Y'
```

**Diagnosis:**

Check environment status:

```bash
cg status
```

Look for:
- "Environment needs repair"
- "Python packages out of sync"
- "X nodes not installed"

**Solution:**

Repair the environment to fix virtual environment corruption:

```bash
# Preview what will change
cg repair

# Apply fixes
cg repair --yes
```

For severe corruption, see [Environment Corruption](environment-corruption.md).

---

### "Out of sync" in status

**Problem:** `cg status` shows "Environment needs repair" or "out of sync"

**Example:**

```
⚠️  Environment needs repair:
  • 2 nodes in pyproject.toml not installed
  • 1 untracked node on filesystem
  • Python packages out of sync
```

**Solution:**

```bash
# Repair synchronizes your environment with config
cg repair --yes
```

This is the most common fix for environment issues. See [Environment Corruption](environment-corruption.md#using-cg-repair) for details.

---

### ComfyUI won't start

**Problem:** `cg run` starts but ComfyUI doesn't load in browser

**Diagnosis steps:**

1. **Check if ComfyUI is actually running:**
   ```bash
   # Check process
   ps aux | grep comfyui

   # Check port (default 8188)
   lsof -i :8188
   ```

2. **Check logs for errors:**
   ```bash
   cg logs

   # Or view live logs
   cg logs --follow
   ```

**Common causes:**

=== "Port already in use"

    **Error in logs:** `Address already in use`

    **Solution:**
    ```bash
    # Find what's using the port
    lsof -i :8188

    # Kill the process
    kill <PID>

    # Or start on different port
    cg run --port 8189
    ```

=== "Missing dependencies"

    **Error in logs:** `ModuleNotFoundError` or import errors

    **Solution:**
    ```bash
    cg repair --yes
    cg run
    ```

=== "Node loading failure"

    **Error in logs:** "Cannot import node X" or "Node failed to load"

    **Solution:**
    ```bash
    # Check which nodes failed
    cg node list

    # Remove problematic nodes
    cg node remove problematic-node

    # Or update them
    cg node update --all
    ```

---

## Custom node issues

### Node installation fails

**Problem:** `cg node add` fails with errors

**Common scenarios:**

#### Dependency conflicts

**Error message:**
```
✗ Dependency conflict detected
  • existing-node requires torch==2.0.0
  • new-node requires torch>=2.1.0
```

**Solution:** See [Dependency Conflicts](dependency-conflicts.md) for comprehensive resolution strategies.

**Quick fix:**
```bash
# Try updating existing node first
cg node update existing-node

# Then add new node
cg node add new-node
```

#### Node not in registry

**Error message:**
```
✗ Node not found in registry: custom-node-name
```

**Solution:**

Add by git URL instead:

```bash
cg node add https://github.com/user/repo
```

Or search for correct name:

```bash
cg node search <partial-name>
```

#### Git clone failures

**Error message:**
```
✗ Failed to clone repository
  fatal: could not read Username
```

**Solution:**

Check git authentication:

```bash
# Test git access
git ls-remote https://github.com/user/repo

# If private, authenticate with gh CLI
gh auth login
```

---

### Node conflicts

**Problem:** Two nodes have conflicting names or directories

**Example:**

```
✗ Node conflict detected
  Directory 'comfyui-manager' already exists but points to different repository
```

**Solution:**

Follow the suggested actions in error message:

```bash
# Option 1: Remove old node
cg node remove old-node

# Option 2: Rename existing directory
mv custom_nodes/comfyui-manager custom_nodes/comfyui-manager-old

# Then retry
cg node add new-node
```

See [Node Conflicts guide](../user-guide/custom-nodes/node-conflicts.md) for details.

---

## Workflow issues

### Workflow shows missing nodes

**Problem:** `cg workflow resolve` reports missing custom nodes

**Example:**

```
⚠️  Partial resolution - issues remain:
  ✗ 2 custom nodes not found

Node issues:
  • comfyui-ipadapter-plus - not installed
  • comfyui-impact-pack - not installed
```

**Solution:**

Install missing nodes:

```bash
# Let ComfyGit find and install them
cg workflow resolve my_workflow

# Or install manually
cg node add comfyui-ipadapter-plus
cg node add comfyui-impact-pack
```

---

### Workflow shows missing models

**Problem:** Workflow resolution reports models not found

**Example:**

```
⚠️  Partial resolution - issues remain:
  ✗ 2 models not found

Model issues:
  • sd_xl_base_1.0.safetensors - not in index
  • realistic_vision_v5.safetensors - not in index
```

**Solution:** See [Missing Models](missing-models.md) for comprehensive fixes.

**Quick fix:**

```bash
# Sync model index (if you already have the models)
cg model index sync

# Or download missing models
cg model download https://civitai.com/api/download/models/XXXXX
```

---

## Model issues

### Models not appearing in index

**Problem:** Downloaded models don't show in `cg model index list`

**Solution:**

```bash
# Sync index to discover models
cg model index sync

# Verify models directory is set
cg model index status

# If no directory configured
cg model index dir ~/ComfyUI/models
```

See [Missing Models](missing-models.md#models-downloaded-but-not-appearing) for details.

---

### CivitAI download fails (401 error)

**Problem:** Model downloads fail with "Unauthorized" or HTTP 401

**Solution:**

Set your CivitAI API token:

```bash
# Get token from: https://civitai.com/user/account
export CIVITAI_API_TOKEN='your-token-here'

# Make it permanent (add to ~/.bashrc or ~/.zshrc)
echo 'export CIVITAI_API_TOKEN="your-token-here"' >> ~/.bashrc
source ~/.bashrc

# Retry download
cg model download <url>
```

See [Missing Models - CivitAI authentication](missing-models.md#civitai-authentication-failures) for details.

---

## Python package issues

### UV resolution fails

**Problem:** Adding nodes or packages fails with UV resolution errors

**Example:**

```
✗ Failed to resolve dependencies
  No solution found when resolving dependencies
```

**Solution:** See [UV Errors](uv-errors.md) for comprehensive troubleshooting.

**Quick fixes:**

```bash
# Try adding constraint for problematic package
cg constraint add "package-name>=1.0.0,<2.0.0"

# Repair environment
cg repair --yes

# If all else fails, update all nodes
cg node update --all
```

---

### Package build failures

**Problem:** Installing nodes fails with "Build failed" or compiler errors

**Example:**

```
error: Failed to build: sageattention
  × Build failed with exit code 1
  ╰─> error: Microsoft Visual C++ 14.0 or greater is required
```

**Solution:**

Install build tools for your platform:

=== "Windows"
    Install [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)

=== "Linux"
    ```bash
    # Ubuntu/Debian
    sudo apt-get install build-essential python3-dev

    # Fedora
    sudo dnf install gcc gcc-c++ python3-devel
    ```

=== "macOS"
    ```bash
    xcode-select --install
    ```

See [UV Errors - Build failures](uv-errors.md#build-failures-compiled-packages) for details.

---

## Getting detailed help

### View logs

Logs contain detailed error information:

```bash
# View recent logs
cg logs -n 100

# View logs in real-time
cg logs --follow

# Logs location
~/.config/comfygit/logs/<env-name>-<timestamp>.log
```

---

### Check environment status

Always start diagnosis with:

```bash
# Basic status
cg status

# Verbose output with full details
cg status --verbose
```

This shows:
- Environment health
- Sync status
- Git state
- Workflow issues
- Uncommitted changes

---

### Run verbose mode

Add `--verbose` to commands for detailed output:

```bash
cg node add <node> --verbose
cg repair --verbose
cg sync --verbose
```

---

## Getting help from the community

If you're still stuck after trying these solutions:

1. **Check logs** for detailed error traces:
   ```bash
   cg logs -n 100
   ```

2. **Capture environment info:**
   ```bash
   cg status
   cg --version
   uv --version
   python --version
   ```

3. **Search existing issues:**
   - [GitHub Issues](https://github.com/comfygit-ai/comfygit/issues)
   - [GitHub Discussions](https://github.com/comfygit-ai/comfygit/discussions)

4. **Report the issue** with:
   - ComfyGit version (`cg --version`)
   - Full error message or log excerpt
   - Steps to reproduce
   - Output of `cg status`

## Detailed troubleshooting guides

For complex issues, see these in-depth guides:

<div class="grid cards" markdown>

-   :material-package-variant-closed: **[Dependency Conflicts](dependency-conflicts.md)**

    ---

    Resolve Python dependency conflicts between custom nodes

-   :material-package-down: **[UV Errors](uv-errors.md)**

    ---

    Understand and fix UV package manager errors

-   :material-image-broken: **[Missing Models](missing-models.md)**

    ---

    Fix workflow model errors and download issues

-   :material-alert-circle: **[Environment Corruption](environment-corruption.md)**

    ---

    Recover from corrupted or broken environments

</div>
