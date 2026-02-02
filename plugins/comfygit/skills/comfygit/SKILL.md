---
name: comfygit
description: |
  ComfyGit CLI and library for managing ComfyUI environments with version control and dependency management.
  Use when: (1) Running cg/comfygit commands, (2) Managing ComfyUI custom nodes, (3) Syncing workflows with dependencies,
  (4) Handling model downloads and resolution, (5) Environment version control (git operations),
  (6) Creating or importing ComfyUI environments, (7) Troubleshooting node conflicts or dependency errors.
  Triggers: "cg", "comfygit", "ComfyUI environment", "custom nodes", "workflow sync", "model download".
---

## First-Time Setup Check

**When this skill is activated, ALWAYS run this check first:**

```bash
cg --version
```

- **If command succeeds**: ComfyGit is installed. Proceed with the user's request.
- **If command fails** ("command not found"): Guide installation before proceeding:

```bash
# Install with uv (recommended)
uv tool install comfygit

# Or with pip
pip install comfygit
```

After installation, verify with `cg --version`, then help initialize:
```bash
cg init                    # Initialize workspace (defaults to ~/comfygit)
cg create <env-name>       # Create first environment
```

---

# ComfyGit CLI Reference

ComfyGit manages ComfyUI environments with git-based version control, automatic dependency resolution, and portable workflows.

## Quick Reference

### Essential Commands

```bash
# Workspace setup
cg init                              # Initialize workspace at ~/comfygit
cg create myenv                      # Create new environment
cg list                              # List all environments
cg -e myenv run                      # Run ComfyUI in environment

# Node management
cg -e myenv node add <id>            # Add custom node from registry
cg -e myenv node add <github-url>    # Add from GitHub URL
cg -e myenv node remove <name>       # Remove custom node
cg -e myenv node list                # List installed nodes

# Workflow sync (auto-installs dependencies)
cg -e myenv sync                     # Sync all workflows
cg -e myenv workflow resolve <name>  # Resolve specific workflow

# Model management
cg model download <url>              # Download model (CivitAI/HuggingFace/URL)
cg model index sync                  # Scan and index models

# Git operations
cg -e myenv status                   # Show environment status
cg -e myenv commit -m "message"      # Commit changes
cg -e myenv pull                     # Pull and repair environment

# Environment config
cg -e myenv env-config torch-backend set cu121  # Set PyTorch backend
```

### Global Flag

- `-e <name>` or `--env <name>`: Target specific environment (required for most operations)
- Without `-e`: Uses active environment (set via `cg use <name>`)

## Architecture Overview

```
Workspace (~/comfygit/)
├── environments/<name>/
│   ├── .cec/                    # Git-tracked config
│   │   ├── pyproject.toml       # Dependencies & node tracking
│   │   ├── workflows/           # Workflow JSON files
│   │   └── .git/                # Environment version control
│   └── ComfyUI/                 # ComfyUI installation
│       ├── custom_nodes/ → symlink
│       └── models/ → symlink
├── models/                      # Global model storage
└── comfygit_cache/              # Registry data, model index
```

**Key Design:**
- Each environment is independently versioned via git
- Models stored globally (symlinked into environments)
- PyTorch backend is machine-specific (not in git)
- Workflows auto-sync dependencies on `cg run`

## Command Categories

### Environment Commands (require `-e <name>` or active environment)

| Command | Purpose |
|---------|---------|
| `run` | Launch ComfyUI (syncs first unless `--no-sync`) |
| `sync` | Install/update all dependencies |
| `status` | Show workflow status, missing nodes, git status |
| `repair` | Restore environment to pyproject.toml state |

### Node Commands

| Command | Purpose |
|---------|---------|
| `node add <id>` | Install from registry (e.g., `comfyui-manager`) |
| `node add <url>` | Install from GitHub URL |
| `node add <path> --dev` | Track local development node |
| `node remove <name>` | Remove node (keeps dev nodes on disk) |
| `node update <name>` | Update to latest version |
| `node list` | Show installed nodes |
| `node prune` | Remove unused nodes |

**Node identifiers:**
- Registry ID: `comfyui-manager`, `comfyui-manager@1.2.3`
- GitHub URL: `https://github.com/user/repo`
- GitHub with ref: `https://github.com/user/repo@branch`

### Workflow Commands

| Command | Purpose |
|---------|---------|
| `workflow list` | Show all workflows with sync status |
| `workflow resolve <name>` | Resolve single workflow dependencies |
| `workflow resolve <name> --install` | Resolve and auto-install |

**Workflow sync status:**
- `synced` - Dependencies resolved and installed
- `modified` - Workflow changed, needs re-sync
- `new` - Not yet resolved
- `issues` - Missing nodes or models

### Model Commands

| Command | Purpose |
|---------|---------|
| `model download <url>` | Download from CivitAI/HuggingFace/URL |
| `model add-source <model> <url>` | Add download source to existing model |
| `model index sync` | Scan and index all models |
| `model index find <query>` | Search models by name/hash |

**Supported sources:**
- CivitAI: `https://civitai.com/api/download/models/123456`
- HuggingFace: `https://huggingface.co/org/model/resolve/main/file.safetensors`
- Direct URLs: Any direct download link

### Git Commands

| Command | Purpose |
|---------|---------|
| `log` | Show commit history |
| `commit -m "msg"` | Save environment changes |
| `checkout <ref>` | Checkout commit/branch |
| `branch` | List/create/delete branches |
| `switch <branch>` | Switch branch |
| `pull` | Pull and repair environment |
| `push` | Push commits to remote |

### Python Dependency Commands

| Command | Purpose |
|---------|---------|
| `py add <pkg>` | Add Python dependency |
| `py add <pkg> --dev` | Add dev dependency |
| `py remove <pkg>` | Remove dependency |
| `py list` | List all dependencies |
| `py uv <args>` | Direct UV passthrough |
| `constraint add <pkg>` | Add version constraint |

## Common Workflows

### Starting Fresh

```bash
cg init                           # Initialize workspace
cg create production              # Create environment
cg -e production run              # Launch ComfyUI
```

### Installing Custom Nodes

```bash
# From registry (preferred)
cg -e myenv node add comfyui-manager

# From GitHub (specific version)
cg -e myenv node add https://github.com/user/repo@v1.0.0

# Development mode (local source)
cg -e myenv node add /path/to/node --dev
```

### Syncing Shared Workflows

```bash
# Put workflow.json in ComfyUI/user/default/workflows/
cg -e myenv workflow resolve my_workflow.json --install
# Interactive prompts for unknown nodes/models
```

### Exporting/Importing Environments

```bash
# Export (creates portable tarball)
cg -e production export ./production.tar.gz

# Import from tarball
cg import ./production.tar.gz --name imported

# Import from git repository
cg import https://github.com/user/comfygit-env --name from-git
```

### Handling Conflicts

When `cg node add` fails with conflicts:

1. **Duplicate node**: Remove existing first or use `--force`
2. **Dependency conflict**: Add constraint or use `--no-test`
3. **Git conflict**: Check suggested actions in error output

```bash
# See full error
cg -e myenv node add <pkg> --verbose

# Force installation (skip dependency test)
cg -e myenv node add <pkg> --no-test

# Add version constraint
cg -e myenv constraint add "package==1.2.3"
```

## Error Handling

### Node Conflict Errors

Error format includes suggested actions:
```
✗ Node conflict: <name>
  Filesystem: <url>
  Registry:   <url>

Suggested actions:
  1. Remove conflicting node
     → cg node remove <name>
  2. Track as dev node
     → cg node add <name> --dev
```

### Dependency Conflict Errors

```
✗ Dependency conflict installing <node>

  • package-a requires X>=2.0
  • package-b requires X<1.5

Options:
  1. Remove conflicting node
     → cg node remove <other-node>
  2. Add version constraint
     → cg constraint add "X==1.4.9"
```

## Reference Documents

For detailed information on specific subsystems:

- [CLI Commands Reference](references/cli-commands.md) - Complete command reference with all flags
- [Core Architecture](references/core-architecture.md) - Library internals and data flow
- [Workflow Resolution](references/workflow-resolution.md) - Node and model resolution strategies
- [Configuration Files](references/configuration.md) - pyproject.toml, package_config.toml structure
