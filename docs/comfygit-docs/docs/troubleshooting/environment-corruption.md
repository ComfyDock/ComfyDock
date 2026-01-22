# Environment Corruption

> Diagnose and recover from environment corruption caused by failed operations, manual edits, or git conflicts.

Environment corruption occurs when your environment's state becomes inconsistent. This can happen from interrupted operations, manual file edits, git conflicts, or filesystem issues. ComfyGit provides tools to diagnose and repair corruption automatically.

## What is environment corruption?

An environment is **corrupted** when there's a mismatch between:

* **Configuration** (`pyproject.toml`) vs **Filesystem** (actual installed nodes/packages)
* **Git state** (`.cec/.git`) vs **Working directory** (uncommitted changes or conflicts)
* **Virtual environment** (broken `.venv` or missing dependencies)
* **Workflow state** (tracked workflows with broken references or missing models)

These mismatches prevent ComfyUI from running correctly and can cause node loading failures, import errors, or workflow issues.

## Signs of corruption

### Configuration drift

**Symptom:** Nodes in `pyproject.toml` not installed on filesystem (or vice versa)

**Detected by:** `cg status`

```
⚠️  Environment needs repair:
  • 3 nodes in pyproject.toml not installed
  • 2 untracked nodes on filesystem:
    - comfyui-impact-pack
    - comfyui-controlnet-aux
  • Python packages out of sync
```

**Cause:** Manual edits to `.cec/pyproject.toml`, interrupted `cg node add`, or direct git operations

---

### Git state corruption

**Symptom:** Detached HEAD, unresolved merge conflicts, or corrupted git repository

**Detected by:** `cg status`

```
Environment: my-env (detached HEAD) ⚠️

⚠️  You are in detached HEAD state
   Any commits you make will not be saved to a branch!
   Create a branch: cg checkout -b <branch-name>
```

**Cause:** Manual git operations in `.cec/.git`, failed `cg pull`, or interrupted rollback

---

### Virtual environment corruption

**Symptom:** Import errors, missing packages, or `uv` failures

**Detected by:** Import failures when running `cg run` or `uv` errors during operations

```
ModuleNotFoundError: No module named 'torch'
```

**Cause:** Interrupted `cg create`, manual venv deletion, or filesystem issues

---

### Workflow sync issues

**Symptom:** Workflows reference nodes or models that aren't installed/available

**Detected by:** `cg status`

```
📋 Workflows:
  ⚠️  portrait.json (synced)
      2 unresolved nodes
      1 model not found
      Run: cg workflow resolve portrait
```

**Cause:** Removing nodes used by workflows, missing model sources, or workflow drift after `cg pull`

## Diagnosing corruption

### Using cg status

The `cg status` command is your primary diagnostic tool:

```bash
cg status
```

**Clean environment** (no issues):

```
Environment: my-env (on main) ✓

✓ No workflows
✓ No uncommitted changes
```

**Corrupted environment** (multiple issues):

```
Environment: my-env (on main)

📋 Workflows:
  ⚠️  portrait.json (modified)
      2 missing models

⚠️  Environment needs repair:
  • 1 node in pyproject.toml not installed
  • 2 untracked nodes on filesystem:
    - comfyui-manager
    - comfyui-custom-scripts
  • Python packages out of sync

📦 Uncommitted changes:
  • Added node: comfyui-ipadapter-plus
```

**Use verbose mode** for full details:

```bash
cg status --verbose
```

### Understanding drift indicators

| Indicator | Meaning | Action |
|-----------|---------|--------|
| `nodes in pyproject.toml not installed` | Config says node should exist but it's missing | Run `cg repair` to install |
| `untracked nodes on filesystem` | Node exists but not in `pyproject.toml` | Run `cg repair` to remove or add to config |
| `version mismatches` | Wrong version installed | Run `cg repair` to update |
| `Python packages out of sync` | `uv.lock` doesn't match installed packages | Run `cg repair` to sync |
| `detached HEAD` | Git repository not on a branch | Create branch or checkout existing one |

## Recovery strategies

### Decision tree: Repair vs Recreate

```
Is the environment corrupted?
│
├─ YES → Can you identify the issue?
│        │
│        ├─ Configuration drift (pyproject.toml vs filesystem)
│        │  → Use `cg repair`
│        │
│        ├─ Git conflicts or detached HEAD
│        │  → Resolve git issues manually, then `cg repair`
│        │
│        ├─ Workflow sync issues
│        │  → Use `cg workflow resolve <name>` then `cg repair`
│        │
│        └─ Venv corruption or unknown severe corruption
│           → Delete and recreate environment
│
└─ NO → Environment is clean
```

### Using cg repair

The `cg repair` command synchronizes your environment to match `pyproject.toml`. It's the **primary recovery tool**.

**What it does:**

1. Compares `pyproject.toml` to filesystem state
2. Shows preview of changes (nodes to install/remove, packages to sync)
3. Applies changes after confirmation
4. Downloads missing models (optional)

**When to use:**

* After manual edits to `pyproject.toml`
* After `cg pull` or `cg rollback`
* When nodes aren't loading in ComfyUI
* After resolving git conflicts
* When `cg status` shows drift

**Basic usage:**

```bash
cg repair
```

**Output:**

```
This will apply the following changes:
  • Install 1 missing node:
    - comfyui-manager

  • Remove 2 extra nodes:
    - old-node-1
    - old-node-2

  • Sync Python packages

Continue? (y/N): y

⚙️ Applying changes to: my-env
  [1/1] Installing comfyui-manager... ✓

✓ Changes applied successfully!

Environment 'my-env' is ready to use
```

**Skip confirmation:**

```bash
cg repair --yes
```

**Model download strategies:**

```bash
# Download all missing models (default)
cg repair --models=all

# Download only required models
cg repair --models=required

# Skip model downloads
cg repair --models=skip
```

### Manual git recovery

If git state is corrupted or you're in detached HEAD:

**Detached HEAD recovery:**

```bash
# Option 1: Create new branch from current state
cd ~/comfygit/environments/my-env/.cec
git checkout -b recovery-branch
cd ~/comfygit
cg repair
```

```bash
# Option 2: Checkout existing branch (loses uncommitted work)
cd ~/comfygit/environments/my-env/.cec
git checkout main
cd ~/comfygit
cg repair
```

**Merge conflict resolution:**

After `cg pull` fails with conflicts:

```bash
# Navigate to .cec
cd ~/comfygit/environments/my-env/.cec

# Check conflict status
git status

# Edit conflicted files (usually pyproject.toml)
# Look for: <<<<<<<, =======, >>>>>>>
# Keep the changes you want

# Stage resolved files
git add pyproject.toml

# Complete the merge
git commit -m "Resolved merge conflicts"

# Return and repair
cd ~/comfygit
cg repair
```

**Corrupted git repository:**

If `.git` directory is corrupted:

```bash
# Last resort - force reset
cd ~/comfygit/environments/my-env/.cec
git reset --hard HEAD
cd ~/comfygit
cg repair
```

!!! warning "Data loss"
    `git reset --hard` discards all uncommitted changes. Only use if you can't resolve conflicts manually.

### Filesystem recovery

If nodes are manually deleted or corrupted:

**Missing custom_nodes directory:**

```bash
# Check if custom_nodes exists
ls ~/comfygit/environments/my-env/custom_nodes

# If missing, repair will recreate and install nodes
cg repair
```

**Broken node installations:**

```bash
# Remove broken node manually
rm -rf ~/comfygit/environments/my-env/custom_nodes/broken-node

# Repair to reinstall
cg repair
```

### Virtual environment corruption

If `.venv` is corrupted:

**Symptom:** Import errors, `uv` failures, or missing Python packages

**Recovery:**

```bash
# Delete corrupted venv
rm -rf ~/comfygit/environments/my-env/.venv

# Recreate venv and sync packages
cg repair
```

ComfyGit will detect missing `.venv` and recreate it automatically with correct Python version and dependencies.

### When to delete and recreate

**Delete and recreate** when:

* Multiple corruption types at once (git + venv + filesystem)
* Unknown corruption that `cg repair` can't fix
* Faster than debugging (if environment is simple)
* Testing a clean slate

**Steps:**

```bash
# Export environment configuration first (optional backup)
cg export my-env backup.tar.gz

# Delete corrupted environment
cg delete my-env --yes

# Recreate from scratch
cg create my-env --use

# Restore from backup (optional)
cg import backup.tar.gz --name my-env

# Or pull from remote
cg remote add origin https://github.com/user/my-env.git
cg pull origin
```

## Prevention strategies

### Commit frequently

Avoid long-running uncommitted states:

```bash
# Good: commit after each logical change
cg node add new-node
cg commit -m "Added new-node"

# Bad: many uncommitted changes
cg node add node1
cg node add node2
# ... days later ...
cg repair  # If something breaks, hard to diagnose
```

### Avoid manual edits

Use ComfyGit commands instead of editing files directly:

```bash
# Good: Use CLI commands
cg node add comfyui-manager
cg py add requests

# Bad: Manual edits
vim .cec/pyproject.toml  # Easy to introduce drift
```

**Exception:** Advanced users can manually edit `pyproject.toml`, but **always run `cg repair` after**.

### Use version control properly

Commit before risky operations:

```bash
# Save current state before experiment
cg commit -m "Stable state before experiment"

# Try risky change
cg node add untested-node
cg run
# Doesn't work...

# Rollback to safety
cg rollback
```

### Regular status checks

Check environment health periodically:

```bash
# Before starting work
cg status

# After making changes
cg status

# Before committing
cg status
```

### Validate after git operations

Always repair after git operations:

```bash
# After pull
cg pull origin
# Auto-runs repair, but verify
cg status

# After manual git operations
cd .cec
git checkout other-branch
cd ..
cg repair  # Sync environment
```

## Recovery checklist

When environment is corrupted, follow this checklist:

1. **Diagnose**
   ```bash
   cg status --verbose
   ```

2. **Identify issue type**
   - Configuration drift → `cg repair`
   - Git issues → Manual git recovery → `cg repair`
   - Workflow issues → `cg workflow resolve <name>`
   - Venv corruption → Delete `.venv` → `cg repair`

3. **Attempt repair**
   ```bash
   cg repair
   ```

4. **Verify recovery**
   ```bash
   cg status
   # Should show clean state
   ```

5. **Test environment**
   ```bash
   cg run
   # ComfyUI should launch without errors
   ```

6. **Fallback: Recreate if repair fails**
   ```bash
   cg export my-env backup.tar.gz
   cg delete my-env
   cg import backup.tar.gz --name my-env
   ```

## See also

* [Version Control](../user-guide/environments/version-control.md) — Git operations and workflows
* [Common Issues](common-issues.md) — Other troubleshooting topics
* [UV Errors](uv-errors.md) — Python package manager issues
* [Dependency Conflicts](dependency-conflicts.md) — Node and package conflicts
* [CLI Reference - repair](../cli-reference/environment-commands.md#repair) — Full repair command documentation
* [CLI Reference - status](../cli-reference/environment-commands.md#status) — Full status command documentation
