# Creating Environments

> Everything you need to know about creating isolated ComfyUI environments with different Python versions, ComfyUI versions, and hardware configurations.

## Prerequisites

* ComfyGit workspace initialized — `cg init`
* Internet connection for downloading ComfyUI and dependencies
* Disk space (2-5 GB per environment depending on PyTorch backend)

## Basic environment creation

Create a new environment with default settings:

```bash
cg create my-env
```

This creates an environment with:

* **Python 3.12** (default version)
* **Latest ComfyUI** (master branch)
* **PyTorch with auto-detected GPU support** (CUDA, ROCm, or CPU)
* Isolated Python virtual environment
* Git-tracked configuration in `.cec/`

**Output:**

```
🚀 Creating environment: my-env
   This will download PyTorch and dependencies (may take a few minutes)...

✓ Environment created: my-env

Next steps:
  • Run ComfyUI: cg -e my-env run
  • Add nodes: cg -e my-env node add <node-name>
  • Set as active: cg use my-env
```

!!! info "What's happening?"
    ComfyGit creates an isolated directory at `~/comfygit/environments/my-env/`, downloads ComfyUI from GitHub, sets up a Python virtual environment with UV, installs PyTorch and dependencies, and initializes a git repository in `.cec/` for version control.

## Setting as active environment

Skip the `-e` flag on every command by setting an active environment:

```bash
cg create my-env --use
```

**Output:**

```
✓ Environment created: my-env
✓ Active environment set to: my-env

Next steps:
  • Run ComfyUI: cg run
  • Add nodes: cg node add <node-name>
```

Now you can run commands without specifying `-e my-env`.

## Specifying Python version

Choose a specific Python version:

```bash
# Python 3.11
cg create py311-env --python 3.11

# Python 3.10
cg create legacy-env --python 3.10

# Python 3.12 (default)
cg create modern-env --python 3.12
```

The Python version is pinned in `.cec/.python-version` and UV ensures that exact version is used.

!!! warning "Python version availability"
    UV will download the specified Python version if it's not already installed. Make sure the version you specify is supported by ComfyUI (typically 3.10+).

## Specifying ComfyUI version

### Latest ComfyUI (default)

```bash
cg create latest-env
```

Uses the `master` branch HEAD.

### Specific ComfyUI version tag

```bash
# Specific release version
cg create stable-env --comfyui v0.2.2

# Another version
cg create older-env --comfyui v0.1.0
```

### Specific branch

```bash
# Development branch
cg create dev-env --comfyui dev

# Feature branch
cg create feature-env --comfyui feature/new-nodes
```

### Specific commit SHA

```bash
# Pin to exact commit
cg create pinned-env --comfyui a1b2c3d4
```

!!! tip "ComfyUI caching"
    ComfyGit caches downloaded ComfyUI versions locally. If you create multiple environments with the same ComfyUI version, the second one will be much faster (restored from cache instead of re-cloning).

## PyTorch backend configuration

ComfyGit supports multiple PyTorch backends for different hardware:

### Auto-detection (default)

```bash
cg create auto-env
```

Automatically detects your GPU:

* **NVIDIA GPU** → Installs CUDA 12.8 backend
* **AMD GPU** → Installs ROCm backend
* **No GPU** → Installs CPU-only backend

### Specific CUDA version

```bash
# CUDA 12.8 (latest, recommended for RTX 40-series)
cg create cuda128-env --torch-backend cu128

# CUDA 12.6
cg create cuda126-env --torch-backend cu126

# CUDA 12.4
cg create cuda124-env --torch-backend cu124

# CUDA 11.8 (for older GPUs)
cg create cuda118-env --torch-backend cu118
```

### AMD ROCm

```bash
# ROCm 6.3 (for AMD GPUs)
cg create amd-env --torch-backend rocm6.3
```

### Intel XPU

```bash
# Intel Arc GPUs
cg create intel-env --torch-backend xpu
```

### CPU-only

```bash
# No GPU acceleration
cg create cpu-env --torch-backend cpu
```

!!! tip "When to specify backend manually"
    Auto-detection works for most users. Specify backend manually when:

    * You want a specific CUDA version for compatibility
    * Auto-detection picks the wrong backend
    * You're creating a CPU-only environment on a GPU machine
    * You need to match another environment's configuration

## Combining options

Create a fully customized environment:

```bash
cg create production \
  --python 3.11 \
  --comfyui v0.2.2 \
  --torch-backend cu128 \
  --use
```

Creates environment with:

* Python 3.11
* ComfyUI v0.2.2
* PyTorch with CUDA 12.8
* Set as active environment

## Environment naming rules

Environment names must follow these rules:

**✅ Valid names:**

```bash
cg create my-project
cg create sdxl-testing
cg create env_123
cg create production-v2
```

**❌ Invalid names:**

```bash
# Reserved names (case-insensitive)
cg create workspace  # Reserved
cg create models     # Reserved
cg create logs       # Reserved

# Hidden directories
cg create .hidden    # Cannot start with '.'

# Path separators
cg create my/env     # No slashes
cg create my\\env    # No backslashes
cg create ../env     # No path traversal

# Empty names
cg create ""         # Must have a name
```

!!! info "Reserved names"
    These names are reserved for ComfyGit internal directories: `workspace`, `logs`, `models`, `comfygit`

## What happens during creation?

Understanding the creation process helps troubleshoot issues:

1. **Validate environment name** — Check for reserved names and invalid characters
2. **Create directory structure** — `~/comfygit/environments/my-env/.cec/`
3. **Pin Python version** — Write `.python-version` file
4. **Clone ComfyUI** — Download from GitHub (or restore from cache)
5. **Create virtual environment** — Use UV to create `.venv/`
6. **Install PyTorch** — Download PyTorch with specified backend
7. **Detect backend** — Extract backend from installed PyTorch version
8. **Configure UV index** — Add PyTorch download index to `pyproject.toml`
9. **Pin PyTorch versions** — Lock torch, torchvision, torchaudio versions
10. **Install ComfyUI requirements** — Add dependencies from `requirements.txt`
11. **Sync dependencies** — Final UV sync to install everything
12. **Initialize git** — Create `.cec/.git/` with initial commit
13. **Create model symlink** — Link `ComfyUI/models/` to workspace models directory

**Typical creation time:**

* **With internet:** 2-5 minutes (mostly PyTorch download)
* **From cache:** 30-60 seconds (ComfyUI already cached)
* **Subsequent creates:** Faster as PyTorch packages are cached locally

## Common variations

### Minimal environment for testing

```bash
cg create test --use
```

Quick environment with all defaults for experimentation.

### Production environment

```bash
cg create production \
  --python 3.11 \
  --comfyui v0.2.2 \
  --torch-backend cu128
```

Pinned versions for stability.

### Development environment

```bash
cg create dev --comfyui dev --use
```

Track ComfyUI's development branch for latest features.

### Multiple environments for different projects

```bash
# Client A's project
cg create client-a --comfyui v0.2.2

# Client B's project
cg create client-b --comfyui v0.2.1

# Personal experiments
cg create playground --use
```

## Troubleshooting

### Creation fails during PyTorch install

**Symptom:** Error during "Installing PyTorch with backend: auto"

**Solutions:**

```bash
# Try CPU-only first to test
cg create test-cpu --torch-backend cpu

# Specify exact CUDA version
cg create test-cuda --torch-backend cu128

# Check disk space
df -h ~/comfygit
```

### Environment already exists

**Symptom:** `Environment 'my-env' already exists`

**Solutions:**

```bash
# List existing environments
cg list

# Delete the old environment first
cg delete my-env

# Or choose a different name
cg create my-env-v2
```

### ComfyUI clone fails

**Symptom:** Failed during "Cloning ComfyUI..."

**Solutions:**

```bash
# Check internet connection
ping github.com

# Try a specific version instead of latest
cg create test --comfyui v0.2.2

# Check GitHub API rate limits (rare)
curl -I https://api.github.com/rate_limit
```

### Python version not available

**Symptom:** UV cannot find specified Python version

**Solutions:**

```bash
# Let UV download it automatically (it will)
# Or install Python manually first

# On macOS
brew install python@3.11

# On Ubuntu
sudo apt install python3.11

# Then retry creation
cg create my-env --python 3.11
```

### Interrupted creation leaves partial environment

**Symptom:** Ctrl+C during creation, environment partially created

**Solution:**

ComfyGit automatically cleans up partial environments. If cleanup fails:

```bash
# Manually delete the partial environment
cg delete my-env

# Or remove directory directly
rm -rf ~/comfygit/environments/my-env
```

## Next steps

After creating an environment:

* **[Run ComfyUI](running-comfyui.md)** — Start the web interface
* **[Add custom nodes](../custom-nodes/adding-nodes.md)** — Install extensions
* **[Version control](version-control.md)** — Commit your configuration

## See also

* [Core Concepts](../../getting-started/concepts.md#environment) — Deep dive into environment architecture
* [CLI Reference](../../cli-reference/environment-commands.md) — Complete create command documentation
* [Python Dependencies](../python-dependencies/py-commands.md) — Managing packages
