# Adding Custom Nodes

> Learn how to install custom nodes from the ComfyUI registry, GitHub repositories, and local development directories.

## Overview

ComfyGit provides several ways to add custom nodes to your environment:

- **Registry lookup** - Search the official ComfyUI registry by name
- **GitHub URLs** - Install directly from any GitHub repository
- **Development nodes** - Track local nodes you're actively developing
- **Batch installation** - Add multiple nodes in one command

## Prerequisites

Before adding nodes, make sure you have:

- An active environment (created with `cg create` or set with `cg use`)
- Internet connection for downloading repositories
- Registry cache downloaded (runs automatically on first use)

!!! tip "Check registry status"
    ```bash
    cg registry status
    ```

    If the registry cache is outdated or missing, update it:
    ```bash
    cg registry update
    ```

## Adding nodes from the registry

The ComfyUI registry contains hundreds of community-maintained custom nodes. ComfyGit searches this registry to find the correct GitHub repository.

### Basic installation

```bash
cg node add comfyui-impact-pack
```

**What happens:**

1. **Registry lookup** - ComfyGit searches for "comfyui-impact-pack" in the registry
2. **Package download** - Downloads pre-packaged node archive from ComfyUI Registry CDN to `custom_nodes/` (or clones from GitHub if CDN package unavailable)
3. **Dependency installation** - Scans for `requirements.txt` or `install.py` and installs Python packages
4. **Configuration update** - Adds the node to `.cec/pyproject.toml`

**Example output:**

```
📦 Adding node: comfyui-impact-pack
✓ Node 'ComfyUI-Impact-Pack' added to pyproject.toml

Run 'cg -e my-env env status' to review changes
```

### Specifying versions

Install a specific version using the `@version` syntax:

```bash
# Install specific release version
cg node add comfyui-impact-pack@1.2.0

# Install from a branch
cg node add comfyui-impact-pack@main

# Install from a commit hash
cg node add comfyui-impact-pack@abc1234
```

!!! info "Version resolution"
    **For registry nodes**: ComfyGit queries the registry API for the specific version (if available in the registry's CDN)

    **For GitHub nodes**: ComfyGit passes the version/ref to git during clone. Works with:

    - Release tags: `@v1.0.0`, `@1.0.0`
    - Branches: `@main`, `@develop`
    - Commit hashes: `@abc1234` (short or full)

### How registry lookup works

When you provide a registry ID like `comfyui-impact-pack`:

1. ComfyGit checks the local registry cache (if `prefer_registry_cache=true` in config)
2. If not found or cache disabled, queries the live ComfyUI registry API
3. Retrieves the node's download URL (CDN package) and metadata
4. Downloads the pre-packaged node from the registry CDN to your environment's `custom_nodes/` directory
5. If no CDN package is available, falls back to cloning from the node's GitHub repository

!!! tip "Registry ID vs. repository name"
    Registry IDs are usually lowercase with hyphens (e.g., `comfyui-impact-pack`), while repository names may have different casing (e.g., `ComfyUI-Impact-Pack`). ComfyGit handles this automatically.

## Adding nodes from GitHub

Install directly from any GitHub repository without registry lookup:

### Full GitHub URLs

```bash
cg node add https://github.com/ltdrdata/ComfyUI-Impact-Pack
```

This bypasses the registry entirely and **clones directly from GitHub** using git (not the CDN download method).

### GitHub URLs with versions

```bash
# Specific branch
cg node add https://github.com/ltdrdata/ComfyUI-Impact-Pack@main

# Specific tag
cg node add https://github.com/ltdrdata/ComfyUI-Impact-Pack@v1.2.0

# Specific commit
cg node add https://github.com/ltdrdata/ComfyUI-Impact-Pack@abc1234
```

!!! tip "When to use GitHub URLs"
    Use GitHub URLs when:

    - The node isn't in the registry yet
    - You want to install from a fork
    - You need a specific branch or commit that isn't packaged in the registry
    - The registry ID is ambiguous

    **Note:** GitHub URLs use git clone, while registry IDs typically use faster CDN downloads. Registry installation is usually preferred when available.

## Batch installation

Add multiple nodes in a single command:

```bash
cg node add comfyui-impact-pack comfyui-controlnet-aux comfyui-video-helper-suite
```

**Output:**

```
📦 Adding 3 nodes...
  [1/3] Installing comfyui-impact-pack... ✓
  [2/3] Installing comfyui-controlnet-aux... ✓
  [3/3] Installing comfyui-video-helper-suite... ✓

✅ Installed 3/3 nodes

Run 'cg -e my-env env status' to review changes
```

### Handling batch failures

If some nodes fail during batch installation:

```
📦 Adding 3 nodes...
  [1/3] Installing comfyui-impact-pack... ✓
  [2/3] Installing invalid-node... ✗ (Node not found in registry)
  [3/3] Installing comfyui-controlnet-aux... ✓

✅ Installed 2/3 nodes

⚠️  Failed to install 1 nodes:
  • invalid-node: Node not found in registry

Run 'cg -e my-env env status' to review changes
```

ComfyGit continues installing other nodes even if one fails.

## Development nodes

Track local nodes you're actively developing without managing them as regular installed nodes.

### What are development nodes?

Development nodes are:

- **Local directories** in `custom_nodes/` that you're editing
- **Tracked separately** from regular nodes in pyproject.toml
- **Not managed** by ComfyGit (you handle git operations yourself)
- **Dependency-aware** - ComfyGit syncs their `requirements.txt` to your environment

### Adding a development node

If you have a local node directory in `custom_nodes/my-custom-node/`:

```bash
cg node add my-custom-node --dev
```

**What happens:**

1. ComfyGit scans `custom_nodes/my-custom-node/requirements.txt`
2. Installs Python dependencies to the environment
3. Marks the node as `development` in pyproject.toml
4. **Does not** git clone or manage updates

**Example output:**

```
📦 Adding development node: my-custom-node
✓ Development node 'my-custom-node' added and tracked

Run 'cg -e my-env env status' to review changes
```

### Development node workflow

```bash
# 1. Clone your node repo manually
cd ~/comfygit/environments/my-env/ComfyUI/custom_nodes/
git clone https://github.com/you/your-custom-node

# 2. Track it as a development node
cg node add your-custom-node --dev

# 3. Edit code locally
cd your-custom-node
# ... make changes ...

# 4. Update dependencies if you change requirements.txt
cg node update your-custom-node

# 5. When done, commit your environment
cg commit -m "Added dev node: your-custom-node"
```

!!! tip "Why use development nodes?"
    Development nodes let you:

    - Work on node code while using it in ComfyUI
    - Keep your own git workflow separate from ComfyGit
    - Have ComfyGit manage Python dependencies automatically
    - Track which dev nodes are part of the environment
    - Share git info with teammates (if your dev node is a git repo)

### Git info tracking

If your development node is a git repository, ComfyGit automatically captures:

- **Repository URL** - The remote origin
- **Branch** - Current branch name
- **Commit hash** - Current HEAD commit

This information is stored in `pyproject.toml` and shared with teammates when they sync the environment. If a teammate syncs and the dev node directory is missing, ComfyGit can auto-clone it from the captured repository URL.

## Advanced options

### Force overwrite

Replace an existing node directory:

```bash
cg node add comfyui-impact-pack --force
```

This removes the existing `custom_nodes/ComfyUI-Impact-Pack/` directory and re-downloads/re-installs the node.

!!! warning "Destructive operation"
    `--force` deletes the existing directory. Any uncommitted local changes will be lost. Use with caution.

### Skip resolution testing

By default, ComfyGit tests that the node's dependencies can be resolved. Skip this with:

```bash
cg node add comfyui-impact-pack --no-test
```

Useful when:

- You know the dependencies are fine
- You want faster installation
- The node has complex dependencies that may show false conflicts

## What gets tracked

When you add a node, ComfyGit updates `.cec/pyproject.toml`:

```toml
[tool.comfygit.nodes]
"comfyui-impact-pack" = {name = "ComfyUI-Impact-Pack", repository = "https://github.com/ltdrdata/ComfyUI-Impact-Pack", version = "abc1234", source = "registry"}
```

This tracks:

- **name** - The node's directory name in `custom_nodes/`
- **repository** - The git repository URL
- **version** - The git commit hash (for reproducibility)
- **source** - Where it came from (`registry`, `git`, or `development`)

## Dependency installation

ComfyGit automatically handles node dependencies:

### requirements.txt

If the node has `requirements.txt`:

```
# custom_nodes/ComfyUI-Impact-Pack/requirements.txt
opencv-python>=4.5.0
pillow>=9.0.0
```

ComfyGit runs:

```bash
uv add opencv-python pillow
```

These get added to your environment's `pyproject.toml` under a dedicated dependency group.

### install.py scripts

Some nodes have `install.py` scripts for custom installation. ComfyGit:

1. Scans for `requirements.txt` first
2. If `install.py` exists, **does not** run it automatically
3. You may need to run it manually:

```bash
cd ~/comfygit/environments/my-env/ComfyUI/custom_nodes/node-name
python install.py
```

!!! info "Why not auto-run install.py?"
    ComfyGit doesn't run arbitrary scripts for security reasons. Review the script first, then run manually if needed.

## How node caching works

ComfyGit uses a two-stage installation process for efficiency:

1. **Download to global cache** - Nodes are first downloaded to a workspace-level cache directory
2. **Copy to environment** - The cached node is then copied to your environment's `custom_nodes/` directory

**Benefits of caching:**

- **Fast reinstallation** - Reinstalling the same node version is instant (no re-download)
- **Shared across environments** - Multiple environments can share the same cached node files
- **Preserved on removal** - Removing a node from an environment doesn't delete the cached copy
- **Reduced bandwidth** - CDN packages are only downloaded once per workspace

**Cache location:**

```
~/comfygit/cache/custom_nodes/
  ├── ComfyUI-Impact-Pack@abc1234/
  ├── ComfyUI-ControlNet-Aux@def5678/
  └── ...
```

!!! tip "Quick reinstallation"
    If you remove a node and then re-add it (same version), ComfyGit will copy it from cache instantly instead of re-downloading.

## Avoiding ComfyUI-Manager

!!! warning "Don't install ComfyUI-Manager"
    ComfyGit **replaces** ComfyUI-Manager's functionality. Installing `comfyui-manager` can cause conflicts because both tools manage custom nodes.

    **Instead of ComfyUI-Manager:**

    - Use `cg node add` to install nodes
    - Use `cg node update` to update nodes
    - Use `cg node list` to see installed nodes
    - Use `cg workflow resolve` to resolve workflow dependencies

## Common patterns

### Installing from a requirements file

If you have a list of nodes:

```bash
# nodes.txt
comfyui-impact-pack
comfyui-controlnet-aux
comfyui-video-helper-suite
```

Install them all:

```bash
cg node add $(cat nodes.txt)
```

Or manually:

```bash
cg node add comfyui-impact-pack comfyui-controlnet-aux comfyui-video-helper-suite
```

### Installing a fork

```bash
# Install from your fork instead of the original
cg node add https://github.com/yourusername/ComfyUI-Impact-Pack
```

### Installing a specific commit for stability

```bash
# Pin to a known-working commit
cg node add comfyui-impact-pack@abc1234567890abcdef
```

## Troubleshooting

### Node not found in registry

```
✗ Failed to add node 'unknown-node'
   Node not found in registry
```

**Solutions:**

1. Check spelling and try again
2. Use the GitHub URL directly:
   ```bash
   cg node add https://github.com/user/repo
   ```
3. Update the registry cache:
   ```bash
   cg registry update
   cg node add unknown-node
   ```

### Registry cache unavailable

```
✗ Cannot add node - registry data unavailable
  Cache location: ~/comfygit/comfygit_cache/registry/

To fix this issue:
  1. Download registry data:
     → cg registry update

  2. Check download status:
     → cg registry status
```

Follow the suggested commands to download the registry.

### Directory already exists

```
✗ Cannot add node 'comfyui-impact-pack'
  Directory custom_nodes/ComfyUI-Impact-Pack already exists
  Filesystem: https://github.com/user/fork
  Registry:   https://github.com/ltdrdata/ComfyUI-Impact-Pack

Suggested actions:
  1. Remove existing node
     → cg node remove comfyui-impact-pack

  2. Force overwrite existing directory
     → cg node add comfyui-impact-pack --force
```

Choose one of the suggested actions based on what you want.

### Dependency conflicts

If a node has conflicting dependencies:

```
✗ Failed to add node 'problematic-node'
   Dependency conflict: torch==2.0.0 (required) conflicts with torch>=2.1.0 (installed)
```

See [Node Conflicts](node-conflicts.md) for detailed conflict resolution strategies.

## Next steps

<div class="grid cards" markdown>

-   :material-format-list-bulleted: **[Managing Nodes](managing-nodes.md)**

    ---

    List, update, remove, and prune installed nodes

-   :material-alert-circle: **[Node Conflicts](node-conflicts.md)**

    ---

    Resolve dependency conflicts between nodes

-   :material-file-tree: **[Workflows](../workflows/workflow-resolution.md)**

    ---

    Automatically resolve node dependencies from workflows

</div>
