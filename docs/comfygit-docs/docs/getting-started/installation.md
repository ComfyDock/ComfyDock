# Installation

ComfyGit is installed as a command-line tool named `cg`. The tool creates and
manages ComfyUI environments with uv, so the recommended install path is `uv
tool install`.

## Prerequisites

You need:

- Python 3.10 or newer
- Git
- Internet access for packages, ComfyUI, custom nodes, and model downloads
- uv, the Python package manager used by ComfyGit

ComfyGit can configure PyTorch backends for CPU, NVIDIA CUDA, AMD ROCm, and
Intel XPU environments. You can let ComfyGit choose during environment setup or
pass a backend explicitly when needed.

## Install uv

=== "macOS/Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

    Restart your terminal, or run:

    ```bash
    source "$HOME/.cargo/env"
    ```

=== "Windows PowerShell"

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

    Restart PowerShell after installation.

Verify uv:

```bash
uv --version
```

## Install ComfyGit

Install or upgrade the CLI:

```bash
uv tool install comfygit --upgrade
```

Verify the command:

```bash
cg --version
```

You should see the installed ComfyGit CLI version.

!!! tip "Shell completion"
    ComfyGit can install completion for supported shells:

    ```bash
    cg completion install
    ```

    Restart your shell after installing completion.

## Initialize Your Workspace

Create the default workspace at `~/comfygit`:

```bash
cg init
```

If you already have a model directory, point ComfyGit at it immediately:

```bash
cg init --models-dir ~/ComfyUI/models --yes
```

Then check the active configuration:

```bash
cg config --show
```

The workspace stores environments, the shared model index, registry cache, logs,
and local machine settings. Environment repositories inside the workspace hold
the portable manifests that are meant to be committed and shared.

## Create A First Environment

Create an environment and make it active:

```bash
cg create my-first-env --use
```

Start ComfyUI:

```bash
cg run
```

When ComfyUI finishes starting, open the URL printed in the terminal.

## Update ComfyGit

Use the same uv command to update the CLI:

```bash
uv tool install comfygit --upgrade
```

If an environment includes `comfygit-manager`, update that node from inside the
environment:

```bash
cg manager status
cg manager update
```

Restart the environment after a manager update.

## Install From Source

Use the source install path when you are developing ComfyGit itself.

```bash
git clone https://github.com/comfygit-ai/comfygit.git
cd comfygit
make install
uv run cg --version
```

For normal usage, prefer `uv tool install comfygit --upgrade`. For development,
use the repo commands so the workspace packages resolve consistently.

## Platform Notes

### Windows

WSL2 is recommended for the smoothest ComfyUI and GPU workflow. Native Windows
can work, but Python build tooling and path length behavior are more likely to
need manual attention.

If long paths cause errors, enable long path support:

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

### macOS

Some dependencies may need Xcode Command Line Tools:

```bash
xcode-select --install
```

### Linux

Most distributions work without extra setup. If a Python package needs to build
native code, install your distribution's development toolchain.

=== "Ubuntu/Debian"

    ```bash
    sudo apt-get update
    sudo apt-get install build-essential python3-dev
    ```

=== "Fedora/RHEL"

    ```bash
    sudo dnf install gcc gcc-c++ python3-devel
    ```

=== "Arch"

    ```bash
    sudo pacman -S base-devel python
    ```

## Troubleshooting

### `uv` is not found

Restart your terminal. On macOS or Linux, you can also source uv's environment:

```bash
source "$HOME/.cargo/env"
```

### Permission errors during install

Do not use `sudo` with `uv tool install`. Fix ownership of the uv install
location instead:

```bash
chown -R "$USER:$USER" "$HOME/.cargo"
```

### Python is too old

Install Python 3.10 or newer, then reinstall ComfyGit:

```bash
uv tool install comfygit --upgrade
```

## Next Steps

- [Read the core concepts](../concepts/what-comfygit-manages.md)
- [Create your first environment](quickstart.md)
- [Learn workspace layout](../user-guide/workspaces.md)
