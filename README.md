# ComfyGit

[![Documentation](https://img.shields.io/badge/docs-comfygit.org-blue)](https://docs.comfygit.org/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE.txt)
[![Discord](https://img.shields.io/badge/Discord-%235865F2.svg?logo=discord&logoColor=white)](https://discord.gg/2h5rSTeh6Y)

Git for your ComfyUI environments — version control, package management, and reproducible sharing.

**Status:** Early release, actively developed. Feedback welcome via [GitHub Issues](https://github.com/comfygit-ai/comfygit/issues) or [Discord](https://discord.gg/2h5rSTeh6Y).

<img width="2400" height="813" alt="Gemini_Generated_Image_gg9thvgg9thvgg9t - Copy" src="https://github.com/user-attachments/assets/8d215b1a-c59e-4f03-855c-170e05cfa5f7" />

## Highlights

- 🔄 **Isolated environments** — test new nodes without breaking production
- 📦 **Git-based versioning** — commit changes, rollback when things break
- 🚀 **One-command sharing** — export/import complete working environments
- 💾 **Smart model management** — content-addressable index, no duplicate storage
- 🔧 **Standard tooling** — built on UV and pyproject.toml, works with Python ecosystem
- 🖥️ **Cross-platform** — Windows, Linux, macOS

> [!NOTE] 
> For a visual UI inside ComfyUI, check out [ComfyGit Manager](https://github.com/comfygit-ai/comfygit-manager)

## How Is This Different From ComfyUI Manager?

ComfyUI Manager helps you browse, install, and update custom nodes in a single shared ComfyUI setup. ComfyGit focuses on **isolated, version-controlled environments** you can reproduce and share anywhere.

- **ComfyUI Manager:** manage nodes in-place (one environment)
- **ComfyGit:** create per-project environments with commits, branches, rollback, export/import

## Installation

```bash
# With UV (recommended)
uv tool install comfygit

# Or with pip
pip install comfygit
```

Need UV? See [UV installation](https://docs.astral.sh/uv/getting-started/installation/).

## Quick Start

```console
$ cg init
Initialized ComfyGit workspace at ~/comfygit

$ cg create my-project --use
Created environment 'my-project'
Active environment: my-project

$ cg node add comfyui-impact-pack
Resolving comfyui-impact-pack...
Installing ComfyUI-Impact-Pack from registry
 + comfyui-impact-pack@1.2.3

$ cg commit -m "Initial setup with Impact Pack"
[main a28f333] Initial setup with Impact Pack
 1 file changed, 15 insertions(+)

$ cg -e my-project run
Starting ComfyUI at http://localhost:8188
```

## What About My Existing Setup?

ComfyGit creates **new, isolated** ComfyUI environments inside your ComfyGit workspace. Your existing ComfyUI install (and anything in it) is **untouched**.

Models are stored once and **symlinked into environments**, so you can share the same model library across projects without duplicating storage.

For your first environment, expect roughly **~2GB** of downloads for ComfyUI and base dependencies.

See the [documentation](https://docs.comfygit.org/getting-started/installation/) for more examples including version control workflows, sharing environments, and team collaboration.

## Documentation

Full documentation at **[docs.comfygit.org](https://docs.comfygit.org/)** including:

- [How It Works](https://docs.comfygit.org/getting-started/concepts/) — architecture and design
- [Model Management](https://docs.comfygit.org/user-guide/models/model-index/) — content-addressable indexing
- [Sharing Environments](https://docs.comfygit.org/user-guide/collaboration/export-import/) — export/import and git remotes

## Features

### Environments
```bash
cg create <name>              # Create new environment
cg list                       # List all environments
cg use <name>                 # Set active environment
cg status                     # Show environment state
cg run                        # Run ComfyUI
```

### Nodes
```bash
cg node add <id>              # Add from registry
cg node add <github-url>      # Add from GitHub
cg node remove <id>           # Remove node
cg node list                  # List installed nodes
```

### Version Control
```bash
cg commit -m "message"        # Save snapshot
cg log                        # View history
cg revert <commit>            # Undo a commit
cg checkout <commit>          # Explore old state
```

### Sharing
```bash
cg export <file.tar.gz>       # Export environment
cg import <file.tar.gz>       # Import environment
cg push / cg pull             # Sync with git remote
```

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

- [GitHub Issues](https://github.com/comfygit-ai/comfygit/issues) — bugs and features
- [GitHub Discussions](https://github.com/comfygit-ai/comfygit/discussions) — questions and ideas
- [Discord](https://discord.gg/2h5rSTeh6Y) — community chat

## License

ComfyGit is licensed under [GPL-3.0](LICENSE.txt).
