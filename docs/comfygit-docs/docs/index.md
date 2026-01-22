# ComfyGit

Git for your ComfyUI environments — version control, package management, and reproducible sharing.

## Highlights

- 🔄 **Isolated environments** — test new nodes without breaking production
- 📦 **Git-based versioning** — commit changes, rollback when things break
- 🚀 **One-command sharing** — export/import complete working environments
- 💾 **Smart model management** — content-addressable index, no duplicate storage
- 🔧 **Standard tooling** — built on UV and pyproject.toml, works with Python ecosystem
- 🖥️ **Cross-platform** — Windows, Linux, macOS

## Installation

=== "macOS/Linux"
    ```console
    $ curl -LsSf https://astral.sh/uv/install.sh | sh
    $ uv tool install comfygit
    ```

=== "Windows"
    ```pwsh-session
    PS> powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    PS> uv tool install comfygit
    ```

Then, check out the [installation guide](./getting-started/installation.md) or read on for a brief overview.

!!! tip

    ComfyGit can also be installed with pip. See all methods on the
    [installation page](./getting-started/installation.md).

## Environments

ComfyGit manages isolated ComfyUI environments with version control:

```console
$ cg init
Initialized ComfyGit workspace at ~/comfygit

$ cg create my-project --use
Created environment 'my-project'
Downloading ComfyUI v0.3.10...
Installing Python dependencies...
Active environment: my-project

$ cg node add comfyui-impact-pack
Resolving comfyui-impact-pack...
Installing ComfyUI-Impact-Pack from registry
 + comfyui-impact-pack@1.2.3
Syncing Python dependencies...
Resolved 45 packages in 1.2s

$ cg run
Starting ComfyUI at http://localhost:8188
```

See the [installation guide](./getting-started/installation.md) to get started.

## Version Control

ComfyGit tracks your environment state with Git, so you can commit changes and rollback when things break:

```console
$ cg commit -m "Added Impact Pack"
[main a28f333] Added Impact Pack
 1 file changed, 15 insertions(+)

$ cg node add comfyui-ipadapter-plus
Installing ComfyUI-IPAdapter-Plus from registry
 + comfyui-ipadapter-plus@2.1.0

$ cg commit -m "Added IPAdapter"
[main b39g444] Added IPAdapter
 1 file changed, 8 insertions(+)

$ cg log
b39g444 Added IPAdapter
a28f333 Added Impact Pack
9c1e222 Initial environment

$ cg revert HEAD
Reverting commit b39g444...
Removing comfyui-ipadapter-plus...
[main c40h555] Revert "Added IPAdapter"
```

See the [version control guide](./user-guide/environments/version-control.md) to learn more.

## Sharing

Export your complete environment for sharing, or sync with Git remotes for team collaboration:

```console
$ cg export my-workflow.tar.gz
Exporting environment 'my-project'...
Bundling node metadata...
Bundling model sources...
Created my-workflow.tar.gz (2.3 MB)

$ cg import my-workflow.tar.gz --name imported-env
Importing environment...
Installing 12 custom nodes...
Downloading 3 models from CivitAI...
Syncing Python dependencies...
Created environment 'imported-env'
```

Or use Git remotes:

```console
$ cg remote add origin https://github.com/you/my-env.git
$ cg push
Pushing to origin...
Branch 'main' pushed to origin

$ cg import https://github.com/team/shared-env.git --name team-env
Cloning repository...
Installing dependencies...
Created environment 'team-env'
```

See the [export & import guide](./user-guide/collaboration/export-import.md) to get started.

## Model Management

ComfyGit indexes models by content hash, preventing duplicates and enabling path-independent resolution:

```console
$ cg model index sync
Scanning models directory...
Indexed 47 models (156.3 GB)

$ cg model download https://civitai.com/models/133005
Downloading juggernautXL_v9.safetensors...
Downloaded to checkpoints/juggernautXL_v9.safetensors
Added to model index

$ cg model index find "juggernaut"
checkpoints/juggernautXL_v9.safetensors
  Hash: 7f3a8b2c...
  Size: 6.46 GB
  Source: civitai.com/models/133005
```

See the [model management guide](./user-guide/models/model-index.md) to learn more.

## Learn more

<div class="grid cards" markdown>

-   :rocket: **[Features](getting-started/features.md)**

    ---

    Complete overview of all capabilities

-   :material-book-open-variant: **[Core Concepts](getting-started/concepts.md)**

    ---

    Understand workspaces, environments, and the .cec directory

-   :material-console: **[CLI Reference](cli-reference/environment-commands.md)**

    ---

    Master all commands and options

-   :material-export: **[Export & Import](user-guide/collaboration/export-import.md)**

    ---

    Share environments with your team

</div>

## Community & Support

- **Discord**: [Join our community](https://discord.gg/2h5rSTeh6Y)
- **Issues**: [GitHub Issues](https://github.com/comfygit-ai/comfygit/issues)
- **Discussions**: [GitHub Discussions](https://github.com/comfygit-ai/comfygit/discussions)
