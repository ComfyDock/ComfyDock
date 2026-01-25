# ComfyGit CLI Commands Reference

Complete reference for all CLI commands with flags and usage patterns.

## Table of Contents
- [Global Commands](#global-commands)
- [Environment Commands](#environment-commands)
- [Node Commands](#node-commands)
- [Workflow Commands](#workflow-commands)
- [Model Commands](#model-commands)
- [Git Commands](#git-commands)
- [Python Dependency Commands](#python-dependency-commands)

---

## Global Commands

Commands that operate at workspace level (no `-e` flag needed).

### `cg init [PATH]`
Initialize ComfyGit workspace.

```bash
cg init                    # Initialize at ~/comfygit
cg init /path/to/workspace # Initialize at specific path
cg init --models-dir /mnt/models  # Use custom models directory
cg init --yes              # Skip confirmations
```

### `cg list`
List all environments in workspace.

### `cg create NAME`
Create new environment.

```bash
cg create production
cg create dev --python 3.12
cg create test --comfyui snapshot      # Latest main branch
cg create test --comfyui v0.2.0        # Specific tag
cg create test --torch-backend cu121   # Specify PyTorch backend
cg create test --use                   # Set as active after creation
cg create test --template production   # Clone from existing (not yet implemented)
```

### `cg use NAME`
Set active environment (used when `-e` not specified).

### `cg delete NAME`
Delete environment.

```bash
cg delete test             # Prompts for confirmation
cg delete test --yes       # Skip confirmation
```

### `cg import [PATH|URL]`
Import environment from tarball or git repository.

```bash
# From tarball
cg import ./env.tar.gz --name imported

# From git repository
cg import https://github.com/user/repo --name from-git
cg import https://github.com/user/repo --branch main
cg import https://github.com/user/repo#subdirectory  # Import subdirectory

# Options
--torch-backend cu121      # Specify backend
--use                      # Set as active
--models all|required|skip # Model download behavior
```

### `cg export [PATH]`
Export environment as portable tarball.

```bash
cg -e production export ./production.tar.gz
cg -e production export --allow-issues  # Export even with unresolved issues
```

### `cg config`
Manage global configuration.

```bash
cg config --show                    # Show current config
cg config --civitai-key <token>     # Set CivitAI API key
cg config --uv-cache /path/to/cache # Set UV cache location
```

### `cg registry status`
Show registry cache status and age.

### `cg registry update`
Force update registry data from GitHub.

### `cg debug`
Show application debug logs.

```bash
cg debug                   # Last 200 lines
cg debug -n 500            # Last 500 lines
cg debug --level ERROR     # Filter by level
cg debug --full            # Full log content
cg debug --workspace       # Workspace-level logs
```

---

## Environment Commands

Commands that operate on a specific environment. Require `-e <name>` or active environment.

### `cg run`
Launch ComfyUI.

```bash
cg -e production run
cg -e production run --no-sync        # Skip dependency sync
cg -e production run --torch-backend cu118
cg -e production run -- --port 8190   # Pass args to ComfyUI
```

**Behavior:**
- Syncs dependencies first (unless `--no-sync`)
- Restarts on exit code 42 (ComfyUI restart signal)
- Uses environment's PyTorch backend

### `cg status`
Show environment status.

```bash
cg -e production status
cg -e production status -v   # Verbose (show node details)
```

**Shows:**
- Workflow sync status (synced/modified/new)
- Missing nodes and models
- Git status (uncommitted changes)
- Smart suggestions for next actions

### `cg sync`
Sync packages and dependencies.

```bash
cg -e production sync
cg -e production sync -v              # Verbose output
cg -e production sync --torch-backend cu121
```

### `cg repair`
Repair environment to match pyproject.toml.

```bash
cg -e production repair
cg -e production repair -y            # Skip confirmations
cg -e production repair --models all  # Download all models
cg -e production repair --models required  # Only required models
cg -e production repair --models skip # Skip model downloads
```

**Use when:**
- Git operations left environment inconsistent
- Node installations failed partway
- Need to restore to known state

### `cg manifest`
Show environment manifest (pyproject.toml).

```bash
cg -e production manifest              # Raw TOML
cg -e production manifest --pretty     # YAML format
cg -e production manifest --section nodes
cg -e production manifest --ide code   # Open in IDE
```

---

## Node Commands

### `cg node add NODE_NAMES...`
Add custom node(s).

```bash
# From registry
cg -e prod node add comfyui-manager
cg -e prod node add comfyui-manager@1.2.3   # Specific version

# From GitHub
cg -e prod node add https://github.com/user/repo
cg -e prod node add https://github.com/user/repo@v1.0.0

# Development mode
cg -e prod node add /path/to/local/node --dev

# Options
--force         # Force overwrite existing
--no-test       # Skip dependency testing (risky)
-v, --verbose   # Show detailed output
```

### `cg node remove NODE_NAMES...`
Remove custom node(s).

```bash
cg -e prod node remove comfyui-manager
cg -e prod node remove node1 node2   # Multiple

# Options
--dev           # Remove dev tracking (keeps files)
--untrack       # Only remove from pyproject
```

### `cg node list`
List installed custom nodes.

### `cg node update NODE_NAME`
Update node to latest version.

```bash
cg -e prod node update comfyui-manager
cg -e prod node update comfyui-manager -y    # Skip confirmation
cg -e prod node update comfyui-manager --no-test
```

### `cg node prune`
Remove nodes not used by any workflow.

```bash
cg -e prod node prune
cg -e prod node prune --exclude node1 node2  # Keep these
cg -e prod node prune -y   # Skip confirmation
```

---

## Workflow Commands

### `cg workflow list`
List all workflows with sync status.

**Status values:**
- `synced` - All dependencies resolved
- `modified` - Workflow changed since last sync
- `new` - Never synced
- `issues` - Missing dependencies

### `cg workflow resolve NAME`
Resolve workflow dependencies.

```bash
cg -e prod workflow resolve my_workflow.json
cg -e prod workflow resolve my_workflow.json --install   # Auto-install
cg -e prod workflow resolve my_workflow.json --auto      # Auto-select where possible
cg -e prod workflow resolve my_workflow.json --no-install  # Resolve only
```

**Interactive prompts:**
- Unknown nodes: Select from registry matches or enter manually
- Ambiguous models: Choose from local matches or download

### `cg workflow model importance [WORKFLOW] [MODEL] [IMPORTANCE]`
Set model importance level.

```bash
# Interactive mode
cg -e prod workflow model importance

# Direct mode
cg -e prod workflow model importance my_workflow.json sd_xl.safetensors required
```

**Importance levels:** `required`, `flexible`, `optional`

---

## Model Commands

### `cg model download URL`
Download model from URL.

```bash
cg model download https://civitai.com/api/download/models/123456
cg model download https://huggingface.co/org/model/resolve/main/model.safetensors

# Options
--path checkpoints/         # Target directory
-c, --category checkpoints  # Model category
--yes                       # Skip confirmations
```

**Supported sources:**
- CivitAI (requires API key for some models)
- HuggingFace (public models)
- Direct URLs

### `cg model add-source [MODEL] [URL]`
Add download source to existing model.

```bash
# Interactive mode (recommended)
cg model add-source

# Direct mode
cg model add-source sd_xl.safetensors https://civitai.com/...
```

### `cg model index list`
List all indexed models.

```bash
cg model index list
cg model index list --duplicates  # Show duplicate hashes
```

### `cg model index find QUERY`
Search models by name or hash.

### `cg model index show IDENTIFIER`
Show detailed model info (hash, sources, locations).

### `cg model index status`
Show models directory and index status.

### `cg model index sync`
Scan and update model index.

### `cg model index dir PATH`
Set global models directory.

---

## Git Commands

### `cg log`
Show commit history.

```bash
cg -e prod log
cg -e prod log -n 50      # Last 50 commits
cg -e prod log -v         # Verbose (show files changed)
```

### `cg commit`
Save environment changes.

```bash
cg -e prod commit -m "Add new workflow"
cg -e prod commit --auto             # Auto-generate message
cg -e prod commit --allow-issues     # Commit with unresolved issues
cg -e prod commit -y                 # Skip confirmations
```

### `cg checkout [REF]`
Checkout commit, branch, or file.

```bash
cg -e prod checkout main             # Switch to branch
cg -e prod checkout abc123           # Checkout commit
cg -e prod checkout -b new-branch    # Create and switch
cg -e prod checkout --force          # Discard local changes
cg -e prod checkout -y               # Skip confirmations
```

### `cg branch [NAME]`
List, create, or delete branches.

```bash
cg -e prod branch                    # List branches
cg -e prod branch new-feature        # Create branch
cg -e prod branch -d old-branch      # Delete branch
cg -e prod branch -D old-branch      # Force delete
```

### `cg switch BRANCH`
Switch to branch.

```bash
cg -e prod switch main
cg -e prod switch -c new-branch      # Create and switch
```

### `cg reset [REF]`
Reset HEAD to specified state.

```bash
cg -e prod reset HEAD~1              # Undo last commit
cg -e prod reset abc123 --soft       # Keep changes staged
cg -e prod reset abc123 --mixed      # Unstage changes (default)
cg -e prod reset abc123 --hard       # Discard all changes
cg -e prod reset -y                  # Skip confirmations
```

### `cg merge BRANCH`
Merge branch into current.

```bash
cg -e prod merge feature-branch
cg -e prod merge feature -m "Merge feature"
cg -e prod merge feature --preview   # Show what would merge
cg -e prod merge feature --auto-resolve mine   # Auto-resolve conflicts
cg -e prod merge feature --auto-resolve theirs
```

### `cg revert COMMIT`
Create commit undoing previous commit.

### `cg pull`
Pull from remote and repair environment.

```bash
cg -e prod pull
cg -e prod pull -r origin -b main
cg -e prod pull --models all         # Download new models
cg -e prod pull --force              # Force pull
cg -e prod pull --preview            # Show what would change
cg -e prod pull --auto-resolve mine  # Auto-resolve conflicts
```

### `cg push`
Push commits to remote.

```bash
cg -e prod push
cg -e prod push -r origin
cg -e prod push --force              # Force push (with lease)
```

### `cg remote add|remove|list NAME [URL]`
Manage git remotes.

```bash
cg -e prod remote list
cg -e prod remote add origin https://github.com/user/repo
cg -e prod remote remove origin
```

---

## Python Dependency Commands

### `cg py add [PACKAGES...]`
Add Python dependencies.

```bash
cg -e prod py add requests
cg -e prod py add "numpy>=1.20"
cg -e prod py add -r requirements.txt
cg -e prod py add torch --upgrade
cg -e prod py add mypackage --dev
cg -e prod py add /path/to/package --editable
cg -e prod py add requests --group optional
cg -e prod py add requests --bounds      # Add version bounds
```

### `cg py remove PACKAGES...`
Remove Python dependencies.

```bash
cg -e prod py remove requests
cg -e prod py remove --group optional mypackage
```

### `cg py remove-group GROUP`
Remove entire dependency group.

### `cg py list`
List dependencies.

```bash
cg -e prod py list
cg -e prod py list --all   # Include transitive dependencies
```

### `cg py uv [UV_ARGS...]`
Direct UV passthrough for advanced operations.

```bash
cg -e prod py uv tree      # Show dependency tree
cg -e prod py uv pip list  # uv pip list
```

### `cg constraint add|list|remove PACKAGES...`
Manage UV version constraints.

```bash
cg -e prod constraint add "numpy<2.0"
cg -e prod constraint list
cg -e prod constraint remove numpy
```

---

## Orchestrator Commands

### `cg orch status`
Show orchestrator (ComfyUI process) status.

```bash
cg orch status
cg orch status --json
```

### `cg orch restart`
Restart ComfyUI.

```bash
cg orch restart
cg orch restart --wait    # Wait for startup
```

### `cg orch kill`
Shutdown orchestrator.

```bash
cg orch kill
cg orch kill --force
```

### `cg orch clean`
Clean orchestrator state.

```bash
cg orch clean --dry-run
cg orch clean --force
cg orch clean --kill      # Kill first, then clean
```

### `cg orch logs`
Show orchestrator logs.

```bash
cg orch logs
cg orch logs -f           # Follow (live tail)
cg orch logs -n 100       # Last 100 lines
```

---

## Manager Commands

### `cg manager status`
Show comfygit-manager node version and update availability.

### `cg manager update`
Update comfygit-manager node.

```bash
cg -e prod manager update
cg -e prod manager update --version 1.2.3
cg -e prod manager update -y
```

---

## Environment Config Commands

### `cg env-config torch-backend show`
Show current PyTorch backend.

### `cg env-config torch-backend set BACKEND`
Set PyTorch backend.

```bash
cg -e prod env-config torch-backend set cu121
cg -e prod env-config torch-backend set cu118
cg -e prod env-config torch-backend set cpu
```

### `cg env-config torch-backend detect`
Auto-detect and set recommended backend.

---

## Shell Completion

### `cg completion install`
Install shell tab completion (bash/zsh/fish).

### `cg completion uninstall`
Remove shell completion.

### `cg completion status`
Show completion installation status.
