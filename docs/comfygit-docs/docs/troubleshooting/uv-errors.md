# UV Errors

> Understanding and resolving UV package manager errors in ComfyGit environments.

## Overview

UV is the high-performance Python package manager that powers ComfyGit's dependency management. When UV encounters issues during dependency resolution, installation, or synchronization, it produces error messages that can be cryptic.

This guide helps you:

- **Understand** what UV error messages mean
- **Diagnose** the root cause of resolution failures
- **Resolve** version conflicts and dependency issues
- **Recover** from corrupted state or cache problems
- **Use** ComfyGit's diagnostic tools effectively

!!! info "UV vs pip"
    UV is significantly faster than pip and provides better dependency resolution. However, its error messages focus on technical precision over user-friendliness. This guide bridges that gap.

## Understanding UV errors

UV errors typically fall into these categories:

| Error Type | Cause | Common Triggers |
|------------|-------|-----------------|
| **Resolution failures** | Dependency version conflicts | Two nodes need incompatible package versions |
| **Build failures** | Package compilation errors | Missing system libraries, incompatible Python version |
| **Network errors** | Connection/download issues | Offline, proxy misconfiguration, PyPI downtime |
| **Cache corruption** | Invalid cached data | Interrupted downloads, disk issues |
| **Lock file issues** | Stale or invalid `uv.lock` | Manual edits, merge conflicts, UV version mismatch |

## Common errors and solutions

### Dependency resolution failures

**Symptom:**

```
✗ Failed to add packages
   The following versions do not satisfy the requirements:
     torch>=2.0.0,<2.1.0 (from node-a)
     torch>=2.1.0 (from node-b)
```

**What it means:**

UV cannot find a version of `torch` that satisfies both requirements. Node A needs torch 2.0.x, but Node B requires 2.1.0 or higher.

**Solution 1: Use constraints to force a compatible version**

```bash
# Check what's required
cg py list --all | grep torch

# Force a version that satisfies both (if possible)
cg constraint add "torch==2.1.0"

# Apply the changes
cg repair --yes
```

If 2.1.0 works for both nodes, the conflict is resolved.

**Solution 2: Remove conflicting node**

```bash
# Identify which node is problematic
cg status

# Remove the node you don't need
cg node remove node-a

# Sync without the conflicting dependency
cg sync
```

**Solution 3: Check for node updates**

```bash
# See if a newer version of the node supports newer torch
cg node search node-a

# Update the node
cg node update node-a
```

See the [Node Conflicts](../user-guide/custom-nodes/node-conflicts.md) guide for more conflict resolution strategies.

### Package not found on PyPI

**Symptom:**

```
✗ Failed to add packages
   No versions found for: nonexistent-package
```

**What it means:**

UV cannot find the package on PyPI. Common causes:

- Typo in package name
- Package was removed from PyPI
- Private/internal package that requires custom index
- Package name differs from import name (e.g., `opencv-python` not `opencv`)

**Solution:**

1. **Verify package name** on [PyPI](https://pypi.org):
   ```bash
   # Search PyPI manually or check project README
   ```

2. **Check import vs install name**:
   ```
   opencv-python  # Install name (✓)
   opencv         # Import name (✗)

   pillow         # Install name (✓)
   PIL            # Import name (✗)
   ```

3. **For private packages**, use UV's index configuration:
   ```bash
   cg py uv add your-package --index-url https://your-private-index.com/simple
   ```

### Network and download errors

**Symptom:**

```
error: Failed to download distribution
   Connection timeout after 30s
   URL: https://files.pythonhosted.org/...
```

**What it means:**

UV cannot download packages from PyPI due to network issues.

**Solution 1: Check internet connection**

```bash
# Test connectivity to PyPI
curl -I https://pypi.org
```

**Solution 2: Retry with increased timeout**

```bash
# UV uses default timeout; retry the operation
cg sync

# For direct UV access with custom timeout
cg py uv add package-name --timeout 300
```

**Solution 3: Configure proxy (if behind corporate firewall)**

```bash
# Set HTTP(S) proxy environment variables
export HTTP_PROXY=http://proxy.company.com:8080
export HTTPS_PROXY=http://proxy.company.com:8080

# Run ComfyGit commands
cg sync
```

**Solution 4: Check PyPI status**

Visit [PyPI Status](https://status.python.org/) to see if PyPI is experiencing outages.

### Build failures (compiled packages)

**Symptom:**

```
error: Failed to build: sageattention
   × Build failed with exit code 1
   ╰─> error: Microsoft Visual C++ 14.0 or greater is required
       (or similar compiler error)
```

**What it means:**

The package requires compilation (C/C++/Rust), but the compiler or system libraries are missing.

**Solution 1: Install build tools**

**Windows:**
- Install [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
- Or install Visual Studio with C++ workload

**Linux:**
```bash
# Ubuntu/Debian
sudo apt-get install build-essential python3-dev

# Fedora/RHEL
sudo dnf install gcc gcc-c++ python3-devel
```

**macOS:**
```bash
xcode-select --install
```

**Solution 2: Use pre-built wheels**

Some packages offer pre-built binaries. Check if your Python version and platform are supported:

```bash
# Check available wheels on PyPI
# Visit: https://pypi.org/project/<package-name>/#files
```

**Solution 3: Install package from conda-forge (if available)**

Some packages are easier to install via conda:

```bash
# Not recommended for ComfyGit, but can extract wheel
conda create -n temp-env python=3.11
conda activate temp-env
conda install -c conda-forge package-name
# Copy wheel from conda env
```

### Cache corruption

**Symptom:**

```
error: Integrity check failed
   Expected hash: sha256:abc123...
   Actual hash: sha256:def456...
```

**What it means:**

UV's download cache contains corrupted data, possibly from an interrupted download or disk error.

**Solution: Clear UV cache**

```bash
# Clear UV's cache directory
cg py uv cache clean

# Then retry the operation
cg sync
```

!!! warning "Cache is shared across environments"
    UV's cache is global (not per-environment). Clearing it will require re-downloading packages for all environments on next sync.

### Lock file issues

**Symptom:**

```
error: Lock file is out of date
   Run `uv lock` to update
```

**What it means:**

The `uv.lock` file doesn't match your `pyproject.toml`. This can happen after:

- Manual edits to `pyproject.toml`
- Git merge/pull that changed dependencies
- Switching between ComfyGit versions

**Solution 1: Regenerate lock file**

```bash
# Regenerate lock file from pyproject.toml
cg py uv lock

# Then sync to install
cg sync
```

**Solution 2: Use repair command (easier)**

```bash
# Repair detects mismatches and fixes them
cg repair --yes
```

**Solution 3: For merge conflicts in lock file**

```bash
# Don't manually resolve lock file conflicts
# Instead, regenerate from pyproject.toml
git checkout --theirs .cec/pyproject.toml  # or --ours
cg py uv lock  # Regenerate lock
git add .cec/uv.lock
git commit -m "Regenerate lock file after merge"
```

## Using ComfyGit diagnostic commands

### `cg py uv` - Direct UV access

For advanced troubleshooting, bypass ComfyGit's wrapper and run UV directly:

```bash
# Show UV version
cg py uv --version

# Lock without syncing (diagnose resolution)
cg py uv lock

# Sync from lock file without updates
cg py uv sync --frozen

# Verbose output for debugging
cg py uv add package-name --verbose
```

!!! warning "Advanced users only"
    Direct UV access gives you full control but can break things. Use `cg py add/remove` unless you specifically need UV features.

See [Py Commands - Direct UV Access](../user-guide/python-dependencies/py-commands.md#direct-uv-access) for more examples.

### `cg sync` - Synchronize environment

Sync ensures your environment matches the declared dependencies:

```bash
# Basic sync
cg sync

# Verbose output (shows UV commands)
cg sync --verbose

# Sync with specific backend
cg sync --torch-backend cuda
```

**When to use:**

- After adding/removing nodes or packages
- After pulling changes from git
- When packages seem out of sync

### `cg repair` - Fix mismatches

Repair detects and fixes discrepancies between:

- `pyproject.toml` (declared dependencies)
- Installed packages (actual state)
- Lock file (resolved versions)

```bash
# Preview what will change
cg repair

# Apply changes without confirmation
cg repair --yes
```

**When to use:**

- After manual edits to `pyproject.toml`
- When `status` shows "out of sync"
- After resolving git conflicts
- When packages mysteriously break

## Advanced troubleshooting

### Debugging resolution failures

**Step 1: Enable verbose output**

```bash
cg py uv add package-name --verbose
```

This shows UV's full resolution process and where it fails.

**Step 2: Check dependency tree**

```bash
# Show all dependencies (direct and transitive)
cg py uv tree

# Search for specific package
cg py uv tree | grep torch
```

**Step 3: Inspect lock file**

```bash
# View resolved versions
cat .cec/uv.lock | grep -A5 "name = \"torch\""
```

### Forcing specific package versions

If UV's resolver is stuck, you can force versions with constraints:

```bash
# Add constraint without installing
cg constraint add "torch==2.1.0"

# Force all transitive dependencies to specific versions
cg constraint add "torch==2.1.0" "numpy==1.24.0" "pillow==10.0.0"

# Apply with repair
cg repair --yes
```

See [Constraints](../user-guide/python-dependencies/constraints.md) for detailed constraint usage.

### Dealing with platform-specific issues

**Windows path issues:**

```bash
# UV handles Windows paths, but check for:
# - Long path names (>260 chars)
# - Special characters in environment names
# - Spaces in COMFYGIT_HOME path
```

**Linux permission issues:**

```bash
# Ensure .venv is not owned by root
ls -la .cec/

# Fix ownership if needed
sudo chown -R $USER:$USER .cec/
```

**macOS ARM (M1/M2) issues:**

```bash
# Some packages don't have ARM wheels yet
# Check if package supports arm64:
# https://pypi.org/project/<package-name>/#files

# Fallback: Use Rosetta 2 for x86_64 packages
arch -x86_64 cg py add package-name
```

### Recovering from broken state

If your environment is completely broken:

**Option 1: Repair from scratch**

```bash
# Remove venv
rm -rf .cec/.venv

# Rebuild from pyproject.toml
cg sync --verbose
```

**Option 2: Reset to last commit**

```bash
# Check git history
cg log

# Reset to working state
cg reset --hard HEAD~1

# Sync from reset state
cg sync
```

**Option 3: Export/import to fresh environment**

```bash
# Export current environment config
cg export -o backup.tar.gz

# Create fresh environment
cg env-create fresh-env

# Import config
cg -e fresh-env import backup.tar.gz
```

## Getting help

If you're still stuck after trying these solutions:

1. **Check logs** for detailed error traces:
   ```bash
   # Logs are in .config/comfygit/logs/
   tail -f ~/.config/comfygit/logs/<env-name>-*.log
   ```

2. **Capture full error output**:
   ```bash
   cg sync --verbose 2>&1 | tee error.log
   ```

3. **Gather environment info**:
   ```bash
   cg status
   uv --version
   python --version
   ```

4. **Report issue** with:
   - ComfyGit version (`cg --version`)
   - UV version (`cg py uv --version`)
   - Full error message
   - Relevant logs
   - Steps to reproduce

## Related documentation

- [Py Commands](../user-guide/python-dependencies/py-commands.md) - Managing Python packages
- [Constraints](../user-guide/python-dependencies/constraints.md) - Controlling package versions
- [Node Conflicts](../user-guide/custom-nodes/node-conflicts.md) - Resolving dependency conflicts between nodes
