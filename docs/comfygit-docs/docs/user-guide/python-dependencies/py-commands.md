# Managing Python Dependencies

> Add, remove, and manage Python packages in your ComfyUI environment using UV-powered dependency management.

## Overview

The `py` commands give you direct control over Python packages in your environment:

- **py add** - Install Python packages (requests, numpy, pillow, etc.)
- **py remove** - Uninstall packages you no longer need
- **py list** - View installed dependencies
- **py uv** - Direct UV access for advanced operations

All changes are tracked in `.cec/pyproject.toml` and committed with your environment for reproducibility.

!!! note "Python packages vs custom nodes"
    - **`cg py add`** - For general Python libraries (requests, opencv-python, numpy)
    - **`cg node add`** - For ComfyUI custom nodes (automatically installs their Python dependencies)

    Most of the time you'll use `node add`. Use `py add` when you need Python packages that aren't part of a custom node.

## Before you begin

Make sure you have:

- An active environment — `cg use <name>` or use `-e <name>` flag
- Internet connection for downloading packages from PyPI

## Adding packages

Add Python packages to your environment:

```bash
cg py add requests
```

**What happens:**

1. **UV resolution** - Checks if package exists and resolves dependencies
2. **Updates pyproject.toml** - Adds to `[project.dependencies]`
3. **Installs package** - Downloads and installs in environment's `.venv`
4. **Tracks in git** - Changes are ready to commit

**Example output:**

```
📦 Adding 1 package(s)...

✓ Added 1 package(s) to dependencies

Run 'cg -e my-env status' to review changes
```

### Adding multiple packages

Add several packages at once:

```bash
cg py add requests pillow tqdm
```

All packages are resolved together, ensuring compatibility.

### Adding with version constraints

Specify version requirements:

```bash
# Minimum version
cg py add "numpy>=1.24.0"

# Version range
cg py add "torch>=2.0.0,<2.5.0"

# Exact version
cg py add "pillow==10.0.0"
```

!!! warning "Quote version constraints"
    Always quote package specifications with special characters (>,<,=) to prevent shell interpretation:
    ```bash
    cg py add "numpy>=1.24"  # ✓ Correct
    cg py add numpy>=1.24    # ✗ Shell error
    ```

### Adding from requirements.txt

Install packages from a requirements file:

```bash
cg py add -r requirements.txt
```

**Example requirements.txt:**

```txt
requests>=2.28.0
pillow>=10.0.0
tqdm>=4.65.0
numpy>=1.24.0,<2.0.0
```

**What happens:**

- Reads all packages from the file
- Adds them to `[project.dependencies]`
- Resolves and installs as a batch

!!! tip "Requirements file location"
    The file path is relative to your current directory, not the environment:
    ```bash
    # If requirements.txt is in current directory
    cg py add -r requirements.txt

    # If it's somewhere else
    cg py add -r /path/to/requirements.txt
    ```

### Upgrading packages

Upgrade existing packages to their latest compatible versions:

```bash
cg py add requests --upgrade
```

This updates `requests` to the latest version that satisfies your constraints.

**Upgrade from requirements file:**

```bash
cg py add -r requirements.txt --upgrade
```

Upgrades all packages listed in the file.

### CUDA packages (no build isolation)

Some CUDA-dependent packages (e.g., SageAttention, flash-attn, deepspeed) need to build
against your installed PyTorch. Use `--no-build-isolation` so the build can access
PyTorch headers and CUDA libraries.

```bash
cg py add "git+https://github.com/thu-ml/SageAttention.git" \
  --optional cuda \
  --no-build-isolation
```

Then install it when you actually want the CUDA extras:

```bash
cg sync --extra cuda
```

If you need to set CUDA build variables, pass them in the environment:

```bash
CUDA_HOME=/usr \
TORCH_CUDA_ARCH_LIST="8.6;8.9" \
cg py add "git+https://github.com/thu-ml/SageAttention.git" --optional cuda --no-build-isolation
```

## Removing packages

Remove packages you no longer need:

```bash
cg py remove requests
```

**What happens:**

1. **Removes from pyproject.toml** - Deletes from `[project.dependencies]`
2. **Uninstalls package** - Removes from `.venv`
3. **Updates lockfile** - Re-resolves remaining dependencies

**Example output:**

```
🗑 Removing 1 package(s)...

✓ Removed 1 package(s) from dependencies

Run 'cg -e my-env status' to review changes
```

### Removing multiple packages

Remove several packages at once:

```bash
cg py remove requests pillow tqdm
```

### Removing non-existent packages

ComfyGit safely handles packages that don't exist:

```bash
cg py remove nonexistent-package
```

**Output:**

```
🗑 Removing 1 package(s)...

ℹ️  Package 'nonexistent-package' is not in dependencies (already removed or never added)
```

No error — the operation is idempotent.

### Mixed removal

When removing multiple packages where some exist and some don't:

```bash
cg py remove requests nonexistent pillow
```

**Output:**

```
🗑 Removing 3 package(s)...

✓ Removed 2 package(s) from dependencies

ℹ️  Skipped 1 package(s) not in dependencies:
  • nonexistent
```

## Listing dependencies

View all Python packages in your environment:

```bash
cg py list
```

**Example output:**

```
Dependencies (5):
  • requests>=2.28.0
  • pillow>=10.0.0
  • tqdm>=4.65.0
  • numpy>=1.24.0,<2.0.0
  • opencv-python>=4.8.0
```

### Understanding the output

- Shows packages from `[project.dependencies]` in pyproject.toml
- Includes version constraints as specified
- Does **not** show transitive dependencies (packages installed as dependencies of your packages)

### Viewing all dependencies

Include custom node dependency groups:

```bash
cg py list --all
```

**Example output:**

```
Dependencies (3):
  • requests>=2.28.0
  • pillow>=10.0.0
  • tqdm>=4.65.0

node/comfyui-impact-pack (4):
  • ultralytics>=8.0.0
  • onnxruntime>=1.15.0
  • opencv-python>=4.8.0
  • segment-anything>=1.0

node/comfyui-controlnet-aux (6):
  • mediapipe>=0.10.0
  • timm>=0.9.0
  • transformers>=4.30.0
  • diffusers>=0.21.0
  • einops>=0.7.0
  • scipy>=1.11.0
```

This shows:

- **Base dependencies** - Added with `cg py add`
- **Node groups** - Dependencies from each custom node

!!! info "Node dependencies are isolated"
    Custom nodes get their own dependency groups like `node/comfyui-impact-pack`. This allows:

    - **Conflict detection** - UV reports if two nodes need incompatible versions
    - **Clean removal** - Removing a node removes its unique dependencies
    - **Transparency** - See exactly what each node requires

## Advanced usage

### Power-user flags

ComfyGit exposes advanced UV features for power users:

#### Adding to dependency groups

Add packages to dependency groups (PEP 735). ComfyGit installs all dependency groups during `cg sync`.
If a group name starts with `optional-`, sync will remove it on build failure to keep the environment usable.

```bash
cg py add sageattention --group optional-cuda
```

**In pyproject.toml:**

```toml
[dependency-groups]
optional-cuda = [
    "sageattention"
]
```

**Use case:** Organize local-only or platform-specific groups. Prefix with `optional-` if it's safe to drop on failure.

#### Adding optional extras

Optional extras live in `[project.optional-dependencies]`. They are **not installed by default**.
Install them only when needed with `cg sync --extra <name>` or `cg sync --all-extras`.

```bash
cg py add "git+https://github.com/thu-ml/SageAttention.git" --optional cuda --no-build-isolation
cg sync --extra cuda
```

**In pyproject.toml:**

```toml
[project.optional-dependencies]
cuda = [
    "sageattention"
]
```

**Use case:** Keep CUDA-only or platform-specific packages optional so the environment still syncs on machines that cannot build them.

#### Adding development dependencies

Mark packages as development-only:

```bash
cg py add pytest black ruff --dev
```

**In pyproject.toml:**

```toml
[dependency-groups]
dev = [
    "pytest",
    "black",
    "ruff"
]
```

**Use case:** Testing, linting, and development tools that aren't needed for production.

#### Editable installs

Install local packages in development mode:

```bash
cg py add /path/to/my-package --editable
```

This creates a symbolic link, so changes to the package source are immediately available without reinstalling.

**Use case:** Developing a Python package that your custom node depends on.

#### Version specifier styles

Control how UV writes version constraints:

```bash
# Lower bound only (default)
cg py add numpy --bounds lower
# Result: numpy>=1.24.0

# Pin major version
cg py add numpy --bounds major
# Result: numpy>=1.24.0,<2.0.0

# Pin minor version
cg py add numpy --bounds minor
# Result: numpy>=1.24.0,<1.25.0

# Exact version
cg py add numpy --bounds exact
# Result: numpy==1.24.0
```

**Use case:** Control how strict your version constraints are for reproducibility vs flexibility.

### Direct UV access

For advanced operations not covered by `py add/remove/list`, use the UV passthrough:

```bash
cg py uv <uv-command> [args...]
```

This runs UV commands with proper environment context (working directory, environment variables).

**Examples:**

```bash
# Lock dependencies without syncing
cg py uv lock

# Sync from lockfile without updating
cg py uv sync --frozen

# Add to specific group with UV-specific flags
cg py uv add --group optional-cuda sageattention --no-sync

# Show UV help
cg py uv --help
```

!!! warning "Advanced users only"
    `cg py uv` gives you direct access to UV. This is powerful but can break things if misused:

    - **No validation** - ComfyGit doesn't check your commands
    - **Can corrupt state** - Incorrect commands can break your environment
    - **Exit codes propagated** - UV errors will exit with error codes

    Use `py add/remove/list` unless you specifically need UV features.

## Common patterns

### Adding packages for a workflow

You download a workflow that needs specific Python packages:

```bash
# Add packages the workflow needs
cg py add mediapipe timm transformers

# Verify they're installed
cg py list
```

### Setting up a development environment

You're developing custom nodes and need dev tools:

```bash
# Add dev dependencies
cg py add pytest black ruff mypy --dev

# View all dependencies including dev
cg py list --all
```

### Migrating from requirements.txt

You have an existing ComfyUI setup with `requirements.txt`:

```bash
# Import all packages
cg py add -r requirements.txt

# Remove old file (now tracked in pyproject.toml)
rm requirements.txt
```

### Fixing version conflicts

Two custom nodes conflict on package versions:

```bash
# Check what's installed
cg py list --all

# See the conflict
# node/comfyui-foo requires torch>=2.0,<2.1
# node/comfyui-bar requires torch>=2.1

# Force a specific version with constraints
cg constraint add "torch==2.1.0"

# Repair to apply
cg repair --yes
```

See [Constraints](constraints.md) for more on dependency constraints.

### Upgrading all packages

Update all packages to latest compatible versions:

```bash
# Export current dependencies
cg py list > /tmp/deps.txt

# Upgrade all
cg py add -r /tmp/deps.txt --upgrade
```

## Troubleshooting

### Package not found

**Error:**

```
✗ Failed to add packages
   No such package: nonexistent-pkg
```

**Solution:**

- Verify package name on [PyPI](https://pypi.org)
- Check for typos (e.g., `opencv-python` not `opencv`)
- Ensure you have internet connection

### Dependency conflict

**Error:**

```
✗ Failed to add packages
   torch==2.0.0 conflicts with torch>=2.1.0 (required by existing-node)
```

**Solution:**

1. Check which packages require conflicting versions:
   ```bash
   cg py list --all | grep torch
   ```

2. Use constraints to force a compatible version:
   ```bash
   cg constraint add "torch==2.1.0"
   ```

3. Or remove conflicting node:
   ```bash
   cg node remove existing-node
   ```

See [Resolving Node Conflicts](../custom-nodes/node-conflicts.md) for detailed conflict resolution.

### Can't remove package

**Error:**

```
✗ Failed to remove packages
   Package 'numpy' is required by: opencv-python, pillow
```

**Solution:**

This means other packages depend on it. You have two options:

1. **Remove dependent packages first:**
   ```bash
   cg py remove opencv-python pillow
   cg py remove numpy
   ```

2. **Force removal** (not recommended - may break things):
   ```bash
   cg py uv remove numpy --no-sync
   ```

### Requirements file not found

**Error:**

```
✗ Error: Requirements file not found: requirements.txt
```

**Solution:**

- Check file path is correct (relative to current directory)
- Use absolute path if needed:
  ```bash
  cg py add -r /absolute/path/to/requirements.txt
  ```

### Changes not taking effect

After adding packages, ComfyUI doesn't see them:

**Solution:**

1. Verify environment is active:
   ```bash
   cg list
   ```

2. Check packages are installed:
   ```bash
   cg py list
   ```

3. Restart ComfyUI:
   ```bash
   cg run
   ```

4. If still broken, repair environment:
   ```bash
   cg repair --yes
   ```

## How it works

### Behind the scenes

When you run `cg py add`:

1. **UV resolution** - UV checks PyPI, resolves dependencies, detects conflicts
2. **Updates pyproject.toml** - Adds package to `[project.dependencies]`
3. **Updates lockfile** - Regenerates `uv.lock` with exact versions
4. **Installs packages** - Downloads wheels and installs in `.venv`

### Relationship to custom nodes

Custom nodes have their own dependency groups:

```toml
[project.dependencies]
# Your packages (via cg py add)
requests = ">=2.28.0"

[project.optional-dependencies]
# Custom node packages (via cg node add)
"node/comfyui-impact-pack" = [
    "ultralytics>=8.0.0",
    "onnxruntime>=1.15.0"
]
```

When you install a custom node with `cg node add`, its Python dependencies are automatically added to the node's group. You rarely need to manually manage node dependencies.

### Version tracking

All changes are tracked in `.cec/`:

```bash
# View changes
cg status

# Commit changes
cg commit -m "Added image processing dependencies"

# Changes now versioned with your environment
```

This means your Python dependencies are:

- **Git-tracked** - Full history of changes
- **Reproducible** - Others can recreate your environment
- **Shareable** - Push to remote, others can pull

## Next steps

- **[Constraints](constraints.md)** - Override dependency versions with constraints
- **[Node Conflicts](../custom-nodes/node-conflicts.md)** - Resolve dependency conflicts between nodes
- **[Version Control](../environments/version-control.md)** - Commit and track changes over time
- **[Export & Import](../collaboration/export-import.md)** - Share environments with full dependencies
