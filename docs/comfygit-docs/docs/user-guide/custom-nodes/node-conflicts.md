# Resolving Node Conflicts

> Understand and fix dependency conflicts when adding or updating custom nodes.

## Overview

Node conflicts occur when two or more custom nodes require incompatible versions of the same Python package. ComfyGit uses UV's dependency resolver to detect these conflicts early and provide actionable solutions.

## What are dependency conflicts?

### Example conflict scenario

Imagine you have:

- **Node A** requires `torch>=2.1.0`
- **Node B** requires `torch==2.0.0`

These requirements are **incompatible** - you can't satisfy both in the same Python environment. ComfyGit detects this during installation and prevents broken environments.

### Why conflicts happen

Common causes:

- **PyTorch version differences** - Nodes built for different CUDA versions
- **Pinned dependencies** - Node hardcodes `package==1.0.0` instead of `package>=1.0.0`
- **Outdated requirements** - Node hasn't updated its `requirements.txt`
- **Conflicting sub-dependencies** - Package A needs X v1, Package B needs X v2

## How ComfyGit detects conflicts

When you run `cg node add` or `cg node update`, ComfyGit:

1. **Parses requirements.txt** - Reads the node's dependencies
2. **Runs UV resolution** - Attempts to resolve all dependencies together
3. **Detects conflicts** - UV reports incompatibilities
4. **Displays error** - Shows conflict details with suggested fixes

By default, ComfyGit **prevents** installing nodes that would break your environment.

## Automatic conflict resolution (probing mode)

ComfyGit now includes an automatic probing mode that attempts to resolve dependency conflicts without user intervention:

### How probing works

1. **Detects conflict** - UV reports incompatible dependencies
2. **Probes one-by-one** - Tests each dependency individually to discover which constraints would resolve the conflict
3. **Suggests constraints** - Identifies version pins that would allow installation
4. **Auto-applies** - Applies the discovered constraints during installation

### When probing succeeds

Most conflicts are auto-resolved:

```
📦 Adding node: new-node
⚠️  Dependency conflict detected, probing for resolution...
✓ Found compatible constraints:
    numpy>=1.24.0,<1.26.0
✓ Constraints applied automatically
✓ Node 'new-node' installed successfully
```

### When probing fails

Some conflicts require manual intervention:

- **Protected package changes** - Probing won't downgrade PyTorch or other protected packages
- **Unsolvable conflicts** - No constraint combination satisfies all requirements
- **Install failures** - Constraint works in theory but fails in practice

In these cases, ComfyGit falls back to the interactive suggestions described below.

### Using strict mode

To get the old behavior (fail immediately on conflicts without probing):

```bash
cg node add new-node --strict
```

This is useful when you want explicit control over all constraint decisions.

## Reading conflict error messages

When a dependency conflict occurs, ComfyGit displays uv's native resolution output. This shows exactly which packages conflict and why, with the full dependency chain.

Example output:

```
✗ Dependency conflict detected

  × No solution found when resolving dependencies:
  ╰─▶ Because node-a depends on torch==2.0.0 and node-b depends on torch>=2.1.0,
      we can conclude that node-a and node-b are incompatible.
      And because you require node-a and node-b, we can conclude that
      your requirements are unsatisfiable.
```

The uv resolver provides detailed information about:

- Which packages have conflicting requirements
- The full dependency chain showing why each version is required
- Which combination of packages cannot be satisfied together

## Common conflict types

### PyTorch version conflicts

**Most common conflict** - Different CUDA backends or PyTorch versions.

**Example:**

```
✗ Failed to add node 'cuda-node'
  torch==2.0.1+cu117 conflicts with torch==2.1.0+cu121
```

**Solutions:**

1. **Check your PyTorch backend:**
   ```bash
   # View current PyTorch version
   cg py list | grep torch
   ```

2. **Recreate environment with matching backend:**
   ```bash
   # If node needs CUDA 11.7
   cg create new-env --torch-backend cu117
   cg -e new-env node add cuda-node
   ```

3. **Update the node** (if newer version supports your PyTorch):
   ```bash
   cg node update cuda-node
   ```

4. **Use constraints** to pin PyTorch version:
   ```bash
   cg constraint add "torch==2.1.0"
   cg node add cuda-node
   ```

### Package pinning conflicts

**Example:**

```
✗ Failed to add node 'old-node'
  pillow==8.0.0 (required by old-node)
  conflicts with pillow>=9.0.0 (required by another-node)
```

**Solutions:**

1. **Check if node has updates:**
   ```bash
   # Try adding latest version
   cg node add old-node@main
   ```

2. **Manually edit requirements.txt** (for development nodes):
   ```bash
   cd custom_nodes/old-node
   # Change pillow==8.0.0 to pillow>=8.0.0
   nano requirements.txt
   cg node update old-node
   ```

3. **Remove conflicting node:**
   ```bash
   cg node remove another-node
   cg node add old-node
   ```

### Directory name conflicts

**Example:**

```
✗ Cannot add node 'comfyui-impact-pack'
  Directory custom_nodes/ComfyUI-Impact-Pack already exists
  Filesystem: https://github.com/yourfork/ComfyUI-Impact-Pack
  Registry:   https://github.com/ltdrdata/ComfyUI-Impact-Pack

Suggested actions:
  1. Remove existing node
     → cg node remove comfyui-impact-pack

  2. Force overwrite existing directory
     → cg node add comfyui-impact-pack --force

  3. Rename existing directory
     → mv custom_nodes/ComfyUI-Impact-Pack custom_nodes/ComfyUI-Impact-Pack-old
```

**Solutions:**

Choose based on what you want:

- **Use the registry version:** Follow suggestion 1 (remove) or 2 (force)
- **Keep your fork:** Remove from pyproject.toml, then re-add as git URL:
  ```bash
  cg node remove comfyui-impact-pack
  cg node add https://github.com/yourfork/ComfyUI-Impact-Pack --dev
  ```
- **Keep both:** Manually rename one directory (suggestion 3)

### Sub-dependency conflicts

**Example:**

```
✗ Failed to add node 'node-x'
  Package 'requests' requires urllib3>=1.26
  Package 'boto3' requires urllib3<1.27
```

This is a **transitive dependency conflict** - neither node directly requires urllib3, but their dependencies do.

**Solutions:**

1. **Use constraints to force a compatible version:**
   ```bash
   cg constraint add "urllib3>=1.26,<1.27"
   cg node add node-x
   ```

2. **Update existing nodes** - newer versions may have relaxed constraints:
   ```bash
   cg node update boto3-node
   cg node add node-x
   ```

3. **Skip resolution testing** (risky):
   ```bash
   cg node add node-x --no-test
   ```

## Resolution strategies

### Interactive resolution (default)

When conflicts occur, ComfyGit shows suggestions:

```
✗ Cannot add node 'new-node'
  torch==2.0.0 conflicts with torch>=2.1.0

Suggested actions:
  1. Update conflicting node
     → cg node update old-node

  2. Remove conflicting node
     → cg node remove old-node

What would you like to do? [1/2/cancel]:
```

Choose the appropriate action or cancel.

### Force overwrite (--force)

Override directory conflicts:

```bash
cg node add comfyui-pack --force
```

This **deletes** the existing directory and re-downloads/re-installs the node. Use when:

- You want the registry version instead of a fork
- The directory is corrupted
- You're okay losing local changes

!!! warning "Destructive operation"
    `--force` permanently deletes the existing directory. Any uncommitted changes are lost.

### Skip resolution testing (--no-test)

Bypass dependency conflict detection:

```bash
cg node add problematic-node --no-test
```

ComfyGit will:

- **Not** test if dependencies can resolve
- **Still install** the node and its dependencies
- **Hope** UV can handle it at runtime

Use when:

- You know the conflict is a false positive
- The node's requirements.txt is incorrect but the code works
- You'll manually fix dependencies later

!!! danger "Risk of broken environment"
    `--no-test` can result in an environment where `cg repair` fails. Use carefully and test thoroughly.

## Using constraints to prevent conflicts

Constraints are UV-specific dependency pins that apply globally to your environment.

### What are constraints?

Think of constraints as "meta-dependencies" that restrict what versions UV can choose:

```bash
# Prevent PyTorch from updating past 2.1.x
cg constraint add "torch>=2.1.0,<2.2.0"

# Pin NumPy to a specific version
cg constraint add "numpy==1.24.0"
```

Now, any node that requires incompatible versions will be rejected **before** installation.

### Common constraint patterns

**Pin PyTorch backend:**

```bash
# Lock to CUDA 12.1
cg constraint add "torch==2.1.0+cu121"
```

**Prevent major version updates:**

```bash
# Stay on Pillow 9.x
cg constraint add "pillow>=9.0.0,<10.0.0"
```

**Force minimum versions:**

```bash
# Ensure modern numpy
cg constraint add "numpy>=1.24.0"
```

### Managing constraints

**List active constraints:**

```bash
cg constraint list
```

**Remove a constraint:**

```bash
cg constraint remove torch
```

See [Python Dependencies: Constraints](../python-dependencies/constraints.md) for more details.

## Practical conflict resolution workflow

### Step 1: Identify the conflict

```bash
cg node add new-node
```

Read the error message carefully to understand:

- Which packages conflict
- Which nodes require them
- What versions are needed

### Step 2: Check existing nodes

```bash
cg node list
```

Identify if the conflicting node is:

- **Essential** - Keep it, reject the new node or find alternatives
- **Unused** - Remove it with `cg node remove`
- **Outdated** - Update it with `cg node update`

### Step 3: Try suggested actions

ComfyGit's suggested actions are usually the best path:

```
Suggested actions:
  1. Update existing node to compatible version
     → cg node update old-node
```

Follow the suggestions in order.

### Step 4: Use constraints if needed

For persistent conflicts:

```bash
# Pin the problematic package to a compatible version
cg constraint add "package>=1.0,<2.0"
cg node add new-node
```

### Step 5: Test the resolution

After resolving conflicts:

```bash
# Verify environment is consistent
cg status

# Test ComfyUI loads
cg run
```

Ensure no errors appear when ComfyUI starts.

## Advanced techniques

### Dependency conflict debugging

**View full UV error output:**

```bash
cg debug -n 100
```

This shows the complete UV resolution error, not just the summary.

**Manually test resolution:**

```bash
cd ~/comfygit/environments/my-env/.cec
uv pip compile pyproject.toml
```

This runs UV's resolver directly and shows detailed conflict traces.

### Creating conflict-free environments

**Start with a constraint file:**

```bash
# constraints.txt
torch==2.1.0+cu121
pillow>=9.0.0,<10.0.0
numpy>=1.24.0

# Add constraints before adding nodes
cg constraint add -r constraints.txt
cg node add node-a node-b node-c
```

This establishes a "compatibility baseline" before installing nodes.

### Splitting environments by compatibility

If nodes are fundamentally incompatible:

```bash
# Environment 1: PyTorch 2.0 nodes
cg create torch20-env --torch-backend cu117
cg -e torch20-env node add old-node

# Environment 2: PyTorch 2.1 nodes
cg create torch21-env --torch-backend cu121
cg -e torch21-env node add new-node
```

Use separate environments for incompatible node ecosystems.

## When conflicts can't be resolved

### Fundamental incompatibilities

Some nodes simply **cannot** coexist:

- Different major PyTorch versions (1.x vs 2.x)
- CPU-only vs GPU-specific packages
- Conflicting C extensions (opencv-python vs opencv-python-headless)

**Solution:** Use separate environments or choose one node over the other.

### Reporting upstream issues

If a node has overly restrictive requirements:

1. Check the node's GitHub issues for existing reports
2. Test if relaxing the constraint works:
   ```bash
   # Edit custom_nodes/node-name/requirements.txt
   # Change torch==2.0.0 to torch>=2.0.0
   cg node update node-name
   ```
3. If it works, open a PR to the node's repository
4. Track it as a development node with your fix:
   ```bash
   cg node add node-name --dev
   ```

## Troubleshooting common scenarios

### "Package not found" after conflict resolution

Sometimes UV can't find a package version that satisfies all constraints.

**Example:**

```
✗ Failed to resolve dependencies
  No version of 'obscure-package' satisfies constraints
```

**Solutions:**

1. **Remove the overly restrictive constraint:**
   ```bash
   cg constraint list
   cg constraint remove obscure-package
   ```

2. **Add the package manually with a broader range:**
   ```bash
   cg py add "obscure-package>=1.0"
   ```

### Environment becomes unsynced after conflict

After resolving conflicts, you might see:

```bash
cg status
```

```
Environment: my-env ⚠

⚠ Environment out of sync (2 changes)
```

**Solution:**

```bash
cg repair
```

This synchronizes the environment to match pyproject.toml.

### Circular dependency errors

UV reports circular dependencies:

```
✗ Circular dependency detected: A → B → C → A
```

**Solutions:**

1. **Update all involved nodes** - one may have fixed it:
   ```bash
   cg node update node-a node-b node-c
   ```

2. **Remove one node** from the cycle:
   ```bash
   cg node remove node-c
   ```

3. **Report to node maintainers** - this is a packaging bug

## Next steps

<div class="grid cards" markdown>

-   :material-plus-circle: **[Adding Nodes](adding-nodes.md)**

    ---

    Install nodes from registry, GitHub, or local development

-   :material-format-list-bulleted: **[Managing Nodes](managing-nodes.md)**

    ---

    List, update, remove, and prune installed nodes

-   :material-package-variant: **[Python Dependencies](../python-dependencies/py-commands.md)**

    ---

    Manage Python packages and constraints

-   :material-hammer-wrench: **[Environment Repair](../environments/version-control.md#repairing-environments)**

    ---

    Fix sync issues with the repair command

</div>
