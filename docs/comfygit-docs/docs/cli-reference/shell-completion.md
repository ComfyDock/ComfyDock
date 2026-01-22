# Shell Completion

> Enable tab completion for ComfyGit CLI commands in your shell.

## Overview

ComfyGit supports tab completion for bash, zsh, and fish shells. Tab completion helps you:

- Autocomplete command names
- Autocomplete environment names
- Autocomplete node names
- Autocomplete workflow names

## Command Reference

### `completion`

Manage shell tab completion.

**Usage:**

```bash
cg completion [-h] {install,uninstall,status} ...
```

#### Subcommands

#### `install`

Install tab completion for your shell.

**Usage:**

```bash
cg completion install [-h]
```

Automatically detects your shell (bash or zsh) and installs the appropriate completion script to your shell configuration file. If argcomplete is not available, it will be installed automatically using `uv tool install`.

#### `uninstall`

Remove tab completion from your shell.

**Usage:**

```bash
cg completion uninstall [-h]
```

Removes the completion configuration from your shell configuration file.

#### `status`

Show tab completion installation status.

**Usage:**

```bash
cg completion status [-h]
```

Displays the current shell, configuration file location, argcomplete availability, and installation status.

## Quick Start

### Installation

Install tab completion for your current shell:

```bash
cg completion install
```

This will detect your shell automatically and install the appropriate completion script.

### Check Status

Check if tab completion is installed:

```bash
cg completion status
```

### Uninstall

Remove tab completion:

```bash
cg completion uninstall
```

## Supported Shells

- **Bash** - Requires bash-completion package
- **Zsh** - Works with default zsh completion system
- **Fish** - Works with fish's built-in completion

## Manual Setup

If automatic installation doesn't work, you can set up completion manually:

### Bash

Add to `~/.bashrc`:

```bash
eval "$(register-python-argcomplete cg)"
```

### Zsh

Add to `~/.zshrc`:

```bash
eval "$(register-python-argcomplete cg)"
```

### Fish

Run:

```bash
register-python-argcomplete --shell fish cg > ~/.config/fish/completions/cg.fish
```

## Troubleshooting

If tab completion isn't working:

1. Restart your shell or run `source ~/.bashrc` (or equivalent)
2. Verify argcomplete is installed: `pip show argcomplete`
3. Check completion status: `cg completion status`
4. Try manual setup if automatic installation fails
