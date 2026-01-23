# Troubleshooting Dependency Conflicts

> Diagnose and resolve Python dependency conflicts when managing custom nodes.

## Overview

Dependency conflicts are one of the most common issues when working with ComfyUI custom nodes. This guide helps you diagnose and fix conflicts using ComfyGit's built-in tools and UV's dependency resolver.

## Quick diagnosis checklist

When you encounter a dependency conflict:

1. **Read the error message carefully** - UV provides detailed conflict information
2. **Check which packages conflict** - Look for version mismatches
3. **Identify the conflicting nodes** - See which nodes require incompatible versions
4. **Try suggested actions** - ComfyGit provides actionable fixes
5. **Use constraints if needed** - Pin problematic packages to compatible versions

## Understanding UV error messages

ComfyGit uses UV's dependency resolver, which provides detailed error output when conflicts occur.

### Basic conflict structure

```
✗ Dependency conflict detected

  • node-a requires torch==2.0.0
  • node-b requires torch>=2.1.0
```

The error shows:

- **Which packages conflict** - e.g., `torch`
- **What versions are needed** - e.g., `==2.0.0` vs `>=2.1.0`
- **Which nodes require them** - e.g., `node-a` and `node-b`

### Full UV resolution output

UV provides a complete dependency chain showing why packages are required:

```
  × No solution found when resolving dependencies:
  ╰─▶ Because node-a depends on torch==2.0.0 and node-b depends on torch>=2.1.0,
      we can conclude that node-a and node-b are incompatible.
      And because you require node-a and node-b, we can conclude that
      your requirements are unsatisfiable.
```

This shows the **logical chain** that leads to the conflict.

## Common conflict scenarios

### PyTorch version conflicts

**Most frequent issue** - Different nodes require different PyTorch versions.

**Example error:**

```bash
$ cg node add new-cuda-node

✗ Dependency conflict detected

  • existing-node requires torch==2.0.1+cu117
  • new-cuda-node requires torch==2.1.0+cu121
```

**Diagnosis steps:**

1. Check your current PyTorch version:
   ```bash
   cg py list | grep torch
   ```

2. Check which nodes require specific versions:
   ```bash
   cg node list --verbose
   ```

**Solutions:**

=== "Option 1: Update existing node"

    ```bash
    # Try updating the old node to support newer PyTorch
    cg node update existing-node
    cg node add new-cuda-node
    ```

=== "Option 2: Use environment constraints"

    ```bash
    # Force a specific PyTorch version for all nodes
    cg constraint add "torch==2.1.0+cu121"
    cg node update existing-node
    cg node add new-cuda-node
    ```

=== "Option 3: Create separate environments"

    ```bash
    # Environment for PyTorch 2.0 nodes
    cg create torch20-env --torch-backend cu117
    cg -e torch20-env node add existing-node

    # Environment for PyTorch 2.1 nodes
    cg create torch21-env --torch-backend cu121
    cg -e torch21-env node add new-cuda-node
    ```

### Package pinning conflicts

**Example error:**

```bash
$ cg node add old-library-node

✗ Dependency conflict detected

  • old-library-node requires pillow==8.0.0
  • modern-node requires pillow>=10.0.0

Options:
  1. Update conflicting node
     → cg node update old-library-node

  2. Remove conflicting node
     → cg node remove modern-node
```

**Diagnosis:**

Check if either node has updates that relax the constraint:

```bash
# Check for updates
cg node update --check old-library-node
cg node update --check modern-node
```

**Solutions:**

=== "Update the node"

    ```bash
    # If newer version exists with relaxed constraints
    cg node update old-library-node
    cg node add modern-node
    ```

=== "Edit requirements manually (dev nodes)"

    For development nodes, you can manually relax constraints:

    ```bash
    cd custom_nodes/old-library-node
    # Edit requirements.txt: pillow==8.0.0 → pillow>=8.0.0
    nano requirements.txt
    cg node update old-library-node
    ```

=== "Force a compatible version"

    ```bash
    # Find a version that works for both
    cg constraint add "pillow>=9.0.0,<11.0.0"
    cg repair
    ```

### Sub-dependency (transitive) conflicts

**Example error:**

```bash
$ cg node add complex-node

✗ Failed to resolve dependencies

  • requests (required by node-a) requires urllib3>=1.26
  • boto3 (required by node-b) requires urllib3<1.27
```

Neither node directly requires `urllib3`, but their dependencies do.

**Diagnosis:**

Use verbose mode to see the full dependency tree:

```bash
cg node add complex-node --verbose
```

**Solutions:**

=== "Add explicit constraint"

    ```bash
    # Force a version that satisfies both
    cg constraint add "urllib3>=1.26,<1.27"
    cg node add complex-node
    ```

=== "Update indirect dependencies"

    ```bash
    # Update the nodes that depend on conflicting packages
    cg node update node-a node-b
    cg node add complex-node
    ```

=== "Force installation (risky)"

    ```bash
    # Skip conflict checking (may break environment)
    cg node add complex-node --no-test
    # Then test if ComfyUI still works
    cg run
    ```

    !!! danger "Use with caution"
        `--no-test` bypasses dependency resolution. Your environment may become unstable.

## Using diagnostic commands

### Verbose mode for detailed errors

Add `--verbose` to see full UV error output:

```bash
cg node add problematic-node --verbose
```

This shows:

- Complete dependency resolution trace
- All package versions considered
- Exact reason for each rejection

### Check environment consistency

After resolving conflicts, verify environment health:

```bash
# Show environment status
cg status

# Look for warnings like:
# ⚠ Environment out of sync (2 changes)
```

If out of sync, repair:

```bash
cg repair
```

### View dependency tree

See which nodes require which packages:

```bash
# List all nodes with their dependencies
cg node list --verbose

# Check specific package usage
cg py list | grep <package-name>
```

## Using constraints to fix conflicts

Constraints are UV-specific version pins that apply globally to your environment.

### When to use constraints

- **Before adding nodes** - Establish compatibility baseline
- **After conflicts** - Force compatible versions
- **For stability** - Lock critical packages (PyTorch, CUDA)

### Adding constraints

```bash
# Pin PyTorch to specific version
cg constraint add "torch==2.1.0+cu121"

# Prevent major version updates
cg constraint add "pillow>=9.0.0,<10.0.0"

# Ensure minimum version
cg constraint add "numpy>=1.24.0"
```

### Viewing active constraints

```bash
cg constraint list
```

Example output:

```
Constraint dependencies in 'production':
  • torch==2.1.0+cu121
  • pillow>=9.0.0,<10.0.0
  • numpy>=1.24.0
```

### Removing constraints

```bash
# Remove specific constraint
cg constraint remove torch

# Then repair environment
cg repair
```

See [Python Dependencies: Constraints](../user-guide/python-dependencies/constraints.md) for more details.

## Step-by-step resolution workflow

### 1. Attempt installation and capture error

```bash
cg node add new-node
```

Read the error carefully - it tells you exactly what conflicts.

### 2. Use suggested actions

ComfyGit provides numbered suggestions:

```
Options:
  1. Update conflicting node
     → cg node update old-node

  2. Remove conflicting node
     → cg node remove old-node
```

Try suggestions in order - they're ranked by likelihood of success.

### 3. If suggestions don't work, use constraints

```bash
# Add constraint for the conflicting package
cg constraint add "<package>>=<min-version>,<max-version>"

# Retry installation
cg node add new-node
```

### 4. Verify environment health

```bash
# Check status
cg status

# Repair if needed
cg repair

# Test ComfyUI launches
cg run
```

### 5. Document the solution

If you had to manually resolve the conflict:

```bash
# Add a note in your workspace
git commit -m "Add constraints for <package> compatibility"
```

## Advanced troubleshooting

### UV resolution fails with no clear conflict

Sometimes UV can't find any compatible versions:

```
✗ Failed to resolve dependencies
  No version of 'obscure-package' satisfies constraints
```

**Diagnosis:**

Check if you have overly restrictive constraints:

```bash
cg constraint list
```

**Solution:**

Remove or relax constraints:

```bash
cg constraint remove obscure-package
cg py add "obscure-package>=1.0"  # Broader range
```

### Circular dependency errors

```
✗ Circular dependency detected: A → B → C → A
```

This is a **packaging bug** in one of the nodes.

**Solutions:**

1. Update all involved nodes:
   ```bash
   cg node update node-a node-b node-c
   ```

2. Remove one node from the cycle:
   ```bash
   cg node remove node-c
   ```

3. Report to node maintainers

### Environment becomes corrupted after resolution

After resolving conflicts, `cg status` shows errors:

```
⚠ Environment out of sync (5 changes)
```

**Solution:**

```bash
# Repair environment to match pyproject.toml
cg repair
```

If repair fails:

```bash
# View detailed error output
cg repair --verbose

# Last resort: recreate environment
cg create fresh-env
cg -e fresh-env import old-env.comfygit
```

## Preventing conflicts

### Use constraints proactively

Before adding many nodes, establish a baseline:

```bash
# constraints.txt
torch==2.1.0+cu121
pillow>=9.0.0,<10.0.0
numpy>=1.24.0

# Apply constraints
cg constraint add -r constraints.txt

# Now add nodes
cg node add node-a node-b node-c
```

### Test nodes individually

Add nodes one at a time to isolate conflicts:

```bash
cg node add node-a
# Test works
cg node add node-b
# Test works
cg node add node-c
# Conflict! We know node-c is the problem.
```

### Keep nodes updated

Regular updates prevent accumulation of outdated dependencies:

```bash
# Update all nodes
cg node update --all

# Or update specific nodes
cg node update node-a node-b
```

## When to use separate environments

Some nodes are **fundamentally incompatible**:

- Different major PyTorch versions (1.x vs 2.x)
- CPU-only vs GPU packages
- Conflicting system libraries (opencv-python vs opencv-python-headless)

**Solution:** Use multiple environments:

```bash
# Environment 1: Legacy PyTorch 1.x
cg create legacy --torch-backend cu117
cg -e legacy node add old-node

# Environment 2: Modern PyTorch 2.x
cg create modern --torch-backend cu121
cg -e modern node add new-node
```

Switch between environments as needed:

```bash
cg -e legacy run     # Use old nodes
cg -e modern run     # Use new nodes
```

## Getting help

If you're stuck after trying these steps:

1. **Check the logs:**
   ```bash
   cg debug -n 100
   ```

2. **Run UV manually** for detailed output:
   ```bash
   cd ~/comfygit/environments/my-env/.cec
   uv pip compile pyproject.toml
   ```

3. **Report to node maintainers** if the issue is in their requirements

4. **Ask in Discord** - Share the error message and `cg status` output

## Related documentation

<div class="grid cards" markdown>

-   :material-alert-circle: **[Node Conflicts](../user-guide/custom-nodes/node-conflicts.md)**

    ---

    Understanding node conflicts and prevention strategies

-   :material-package-variant: **[Python Dependencies](../user-guide/python-dependencies/py-commands.md)**

    ---

    Managing Python packages and constraints

-   :material-hammer-wrench: **[Environment Repair](../user-guide/environments/version-control.md#repairing-environments)**

    ---

    Fix sync issues with the repair command

-   :material-cog: **[Constraints](../user-guide/python-dependencies/constraints.md)**

    ---

    Detailed guide to UV constraints

</div>
