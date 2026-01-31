# Managing Custom Nodes

> View, update, remove, and clean up custom nodes in your environment.

## Overview

Once you've added custom nodes, ComfyGit provides commands to manage their lifecycle:

- **List** - View all installed nodes with version info
- **Update** - Pull latest changes from repositories
- **Remove** - Uninstall nodes (single or batch)
- **Prune** - Clean up unused nodes automatically

## Listing installed nodes

View all custom nodes in your environment:

```bash
cg node list
```

**Example output:**

```
Custom nodes in 'my-project':
  • comfyui-impact-pack (registry) @ abc12345
  • comfyui-controlnet-aux (git) @ def67890
  • my-custom-node (development) (dev)
```

### Understanding the output

Each line shows:

- **Node name** - The registry ID or directory name
- **Source type** - Where the node came from:
  - `registry` - Installed from ComfyUI registry lookup
  - `git` - Installed directly from GitHub URL
  - `development` - Local development node tracked with `--dev`
- **Version** - The git commit hash (short form) or `(dev)` for development nodes

### When no nodes are installed

```
No custom nodes installed
```

This means your environment only has ComfyUI's built-in nodes.

## Updating nodes

Update a node to the latest version from its repository:

```bash
cg node update comfyui-impact-pack
```

**What happens:**

1. **Git pull** - Fetches latest changes from the node's repository
2. **Dependency scan** - Checks for updated `requirements.txt`
3. **Dependency update** - Installs any new or updated Python packages
4. **Version update** - Updates the commit hash in pyproject.toml

**Example output (changes detected):**

```
🔄 Updating node: comfyui-impact-pack
✓ Updated to commit abc1234 (10 commits ahead)

Run 'cg status' to review changes
```

**Example output (no changes):**

```
🔄 Updating node: comfyui-impact-pack
ℹ️  Already up to date
```

### Auto-confirm updates

Skip the confirmation prompt with `--yes`:

```bash
cg node update comfyui-impact-pack --yes
```

Useful for scripting or CI/CD pipelines.

### Skip resolution testing

By default, ComfyGit tests that updated dependencies don't conflict. Skip this with:

```bash
cg node update comfyui-impact-pack --no-test
```

### Updating development nodes

Development nodes have a different update behavior:

```bash
cg node update my-custom-node
```

For development nodes:

- **Does not** run `git pull` (you manage git yourself)
- **Does** re-scan `requirements.txt` and sync dependencies
- **Shows** what dependencies were added or removed

**Example output:**

```
🔄 Updating node: my-custom-node
✓ Development node dependencies synced
  Added dependencies:
    + opencv-python>=4.8.0
  Removed dependencies:
    - pillow<9.0.0

Run 'cg status' to review changes
```

!!! tip "Development nodes are self-managed"
    Dev nodes are managed by you, the developer — ComfyGit won't auto-pull or modify your code:

    - **Git state**: Push/pull using standard git commands
    - **Dependencies**: Run `cg node update <node>` to sync `requirements.txt` changes to the environment
    - **Code**: You develop and test the node directly in `custom_nodes/`

    ComfyGit tracks name, repository URL, and requirements so teammates can clone and install your dev nodes.

## Removing nodes

Remove custom nodes from your environment:

```bash
cg node remove comfyui-impact-pack
```

**What happens:**

1. **Removes from pyproject.toml** - Node configuration deleted
2. **Deletes directory** - Removes `custom_nodes/ComfyUI-Impact-Pack/`
3. **Preserves in cache** - Node is cached globally and can be reinstalled quickly

**Example output:**

```
🗑 Removing node: comfyui-impact-pack
✓ Node 'ComfyUI-Impact-Pack' removed from environment
   (cached globally, can reinstall)

Run 'cg -e my-env env status' to review changes
```

### Batch removal

Remove multiple nodes at once:

```bash
cg node remove comfyui-impact-pack comfyui-controlnet-aux comfyui-video-helper-suite
```

**Output:**

```
🗑 Removing 3 nodes...
  [1/3] Removing comfyui-impact-pack... ✓
  [2/3] Removing comfyui-controlnet-aux... ✓
  [3/3] Removing comfyui-video-helper-suite... ✓

✅ Removed 3/3 nodes

Run 'cg -e my-env env status' to review changes
```

### Removing development nodes

Development nodes are handled differently:

```bash
cg node remove my-custom-node
```

**Output:**

```
🗑 Removing node: my-custom-node
ℹ️  Development node 'my-custom-node' removed from tracking
   Files preserved at: custom_nodes/my-custom-node.disabled/
```

Development nodes are:

- **Removed from tracking** - No longer in pyproject.toml
- **Directory renamed** - Moved to `.disabled` suffix to prevent ComfyUI from loading it
- **Not deleted** - Your code is preserved

!!! info "Why preserve development nodes?"
    ComfyGit assumes you want to keep local development work. The directory is disabled (renamed) so ComfyUI won't load it, but your code remains intact.

### Remove development nodes with --dev flag

Explicitly remove a development node:

```bash
cg node remove my-custom-node --dev
```

This has the same behavior as regular removal of dev nodes (renames to `.disabled`).

## Pruning unused nodes

Remove all nodes that aren't used by any tracked workflow:

```bash
cg node prune
```

**What it does:**

1. Analyzes all workflows in your environment
2. Identifies nodes not referenced by any workflow
3. Prompts for confirmation
4. Removes unused nodes

**Example output:**

```
Found 2 unused node(s):

  • comfyui-old-pack
  • comfyui-experimental-feature

Remove 2 node(s)? [y/N]: y

🗑 Pruning 2 unused nodes...
  [1/2] Removing comfyui-old-pack... ✓
  [2/2] Removing comfyui-experimental-feature... ✓

✓ Removed 2 node(s)
```

### Auto-confirm pruning

Skip the confirmation prompt:

```bash
cg node prune --yes
```

### Exclude specific nodes

Keep certain nodes even if unused:

```bash
cg node prune --exclude comfyui-dev-tools comfyui-experimental-feature
```

This removes unused nodes **except** the excluded ones.

### When no unused nodes exist

```
✓ No unused nodes found
```

All installed nodes are referenced by at least one workflow.

!!! tip "When to use prune"
    Use `cg node prune` when:

    - Cleaning up after testing many nodes
    - Reducing environment size before export
    - Keeping only workflow-essential nodes
    - Preparing a production environment

## Viewing node status

The `cg status` command shows node-related information:

```bash
cg status
```

**Example output:**

```
Environment: my-project ✓

📦 Nodes (3 installed):
  ✓ comfyui-impact-pack @ abc1234
  ✓ comfyui-controlnet-aux @ def6789
  ⚠ comfyui-old-node @ ghi0123 (update available)
```

### Status indicators

- **✓ Green checkmark** - Node installed and up to date
- **⚠ Warning** - Update available or issue detected

!!! note "Dev nodes don't show update status"
    Development nodes are self-managed by you. ComfyGit doesn't track their
    requirements or suggest updates - you manage your own git state and dependencies.

## Node types explained

ComfyGit tracks three types of nodes:

### Registry nodes

```bash
cg node add comfyui-impact-pack
```

- **Source**: ComfyUI registry lookup
- **Management**: Full ComfyGit control (update, remove)
- **Version tracking**: Git commit hash
- **Listed as**: `comfyui-impact-pack (registry) @ abc1234`

### Git nodes

```bash
cg node add https://github.com/user/custom-node
```

- **Source**: Direct GitHub URL
- **Management**: Full ComfyGit control
- **Version tracking**: Git commit hash
- **Listed as**: `custom-node (git) @ def5678`

### Development nodes

```bash
cg node add my-local-node --dev
```

- **Source**: Local development directory
- **Management**: You handle git, ComfyGit handles dependencies
- **Version tracking**: Marked as `dev`
- **Listed as**: `my-local-node (development) (dev)`

## Common workflows

### Update all nodes

ComfyGit doesn't have a built-in "update all" command, but you can script it:

```bash
# List node names and update each
cg node list | grep '•' | awk '{print $2}' | while read node; do
    cg node update "$node" --yes
done
```

!!! warning "Use with caution"
    Updating all nodes at once can introduce breaking changes. Test in a non-production environment first.

### Clean up after workflow testing

```bash
# Remove unused nodes after experimenting
cg node prune --yes

# Commit the cleanup
cg commit -m "Pruned unused nodes"
```

### Temporarily disable a node

Instead of removing:

```bash
# Manually rename the directory
cd ~/comfygit/environments/my-env/ComfyUI/custom_nodes/
mv ComfyUI-SomeNode ComfyUI-SomeNode.disabled
```

ComfyUI won't load `.disabled` directories. Re-enable by renaming back.

### Keep development nodes in sync

Create a git hook in your dev node repository:

```bash
# In your dev node repo: .git/hooks/post-checkout
#!/bin/bash
cg node update my-custom-node
```

This auto-syncs dependencies when you checkout branches.

## Troubleshooting

### Node not found when updating

```
✗ Failed to update node 'unknown-node'
   Node not found in environment
```

**Solutions:**

1. Check installed nodes:
   ```bash
   cg node list
   ```
2. Verify spelling matches the listed name
3. The node may have been removed - reinstall:
   ```bash
   cg node add unknown-node
   ```

### Update fails with git errors

```
✗ Failed to update node 'comfyui-impact-pack'
   Git pull failed: uncommitted changes in repository
```

**Solutions:**

1. Check the node directory for local changes:
   ```bash
   cd ~/comfygit/environments/my-env/ComfyUI/custom_nodes/ComfyUI-Impact-Pack
   git status
   ```
2. Commit or stash changes:
   ```bash
   git stash
   ```
3. Try updating again:
   ```bash
   cg node update comfyui-impact-pack
   ```

### Prune removes important nodes

If you accidentally pruned nodes you need:

```bash
# Rollback to previous version
cg rollback

# Or reinstall specific nodes
cg node add comfyui-important-pack
```

### Development node not detected

If `cg node list` doesn't show your dev node:

1. Verify it was added with `--dev`:
   ```bash
   cg node add my-node --dev
   ```
2. Check pyproject.toml:
   ```bash
   grep my-node .cec/pyproject.toml
   ```

## Next steps

<div class="grid cards" markdown>

-   :material-plus-circle: **[Adding Nodes](adding-nodes.md)**

    ---

    Install nodes from registry, GitHub, or local development

-   :material-alert-circle: **[Node Conflicts](node-conflicts.md)**

    ---

    Resolve dependency conflicts between nodes

-   :material-hammer-wrench: **[Repair Command](../environments/version-control.md#repairing-environments)**

    ---

    Fix environment sync issues with `cg repair`

</div>
