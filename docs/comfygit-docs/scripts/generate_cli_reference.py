#!/usr/bin/env python3
"""Generate CLI reference documentation from argparse parser.

This script extracts command structure from the CLI and generates markdown
documentation for each command category defined in mkdocs.yml.
"""
import sys
from pathlib import Path
from typing import Any

# Add CLI package to path
cli_path = Path(__file__).parent.parent.parent.parent / "packages" / "cli"
sys.path.insert(0, str(cli_path))

from comfygit_cli.cli import create_parser


def get_subcommand_help(parser, command_name: str) -> dict[str, Any]:
    """Extract help information for a subcommand."""
    # Find the subparser
    for action in parser._actions:
        if hasattr(action, 'choices') and action.choices and command_name in action.choices:
            subparser = action.choices[command_name]

            result = {
                'name': command_name,
                'description': subparser.description or '',
                'usage': subparser.format_usage().replace('usage: ', ''),
                'arguments': [],
                'options': [],
                'subcommands': {}
            }

            # Extract arguments and options
            for sub_action in subparser._actions:
                if sub_action.dest == 'help':
                    continue

                option_strings = sub_action.option_strings
                if option_strings:
                    # This is an option
                    result['options'].append({
                        'flags': ', '.join(option_strings),
                        'dest': sub_action.dest,
                        'help': sub_action.help or '',
                        'default': sub_action.default if sub_action.default != '==SUPPRESS==' else None,
                        'choices': sub_action.choices if hasattr(sub_action, 'choices') and not isinstance(sub_action.choices, dict) else None,
                        'required': getattr(sub_action, 'required', False),
                    })
                elif sub_action.dest not in ['command', 'func'] and hasattr(sub_action, 'choices') and isinstance(sub_action.choices, dict):
                    # This is a subcommand group
                    result['subcommands'] = {
                        name: get_subcommand_help(subparser, name)
                        for name in sub_action.choices.keys()
                    }
                else:
                    # This is a positional argument
                    if sub_action.dest not in ['command', 'func']:
                        result['arguments'].append({
                            'name': sub_action.dest,
                            'help': sub_action.help or '',
                            'nargs': sub_action.nargs,
                            'default': sub_action.default if sub_action.default != '==SUPPRESS==' else None,
                        })

            return result

    return {}


def format_option(opt: dict[str, Any]) -> str:
    """Format an option for markdown."""
    parts = [f"- `{opt['flags']}`"]

    if opt['help']:
        parts.append(f" - {opt['help']}")

    if opt['choices']:
        parts.append(f" (choices: {', '.join(f'`{c}`' for c in opt['choices'])})")

    if opt['required']:
        parts.append(" **[required]**")

    if opt['default'] is not None:
        parts.append(f" (default: `{opt['default']}`)")

    return ''.join(parts)


def format_argument(arg: dict[str, Any]) -> str:
    """Format an argument for markdown."""
    parts = [f"- `{arg['name']}`"]

    if arg['help']:
        parts.append(f" - {arg['help']}")

    if arg['nargs'] in ['*', '+']:
        parts.append(" (multiple values allowed)")
    elif arg['nargs'] == '?':
        parts.append(" (optional)")

    if arg['default'] is not None:
        parts.append(f" (default: `{arg['default']}`)")

    return ''.join(parts)


def generate_command_section(cmd_info: dict[str, Any], level: int = 2) -> list[str]:
    """Generate markdown for a command section."""
    lines = []
    heading = '#' * level

    # Command heading
    lines.append(f"\n{heading} `{cmd_info['name']}`\n")

    # Description
    if cmd_info['description']:
        lines.append(f"{cmd_info['description']}\n")

    # Usage
    lines.append("**Usage:**\n")
    lines.append("```bash")
    lines.append(cmd_info['usage'].strip())
    lines.append("```\n")

    # Arguments
    if cmd_info['arguments']:
        lines.append("**Arguments:**\n")
        for arg in cmd_info['arguments']:
            lines.append(format_argument(arg))
        lines.append("")

    # Options
    if cmd_info['options']:
        lines.append("**Options:**\n")
        for opt in cmd_info['options']:
            lines.append(format_option(opt))
        lines.append("")

    # Subcommands
    if cmd_info['subcommands']:
        lines.append(f"{heading}# Subcommands\n")
        for subcmd_name, subcmd_info in cmd_info['subcommands'].items():
            lines.extend(generate_command_section(subcmd_info, level + 1))

    return lines


def categorize_commands(parser) -> dict[str, list[str]]:
    """Categorize commands into documentation sections."""
    categories = {
        'global-commands': ['init', 'list', 'import', 'export', 'model', 'registry', 'config', 'debug'],
        'environment-commands': ['create', 'use', 'delete', 'run', 'status', 'manifest', 'sync', 'repair', 'log', 'commit', 'rollback', 'pull', 'push', 'remote', 'env-config', 'py', 'constraint'],
        'node-commands': ['node'],
        'workflow-commands': ['workflow'],
        'model-commands': ['model'],
    }

    return categories


def generate_category_page(category_name: str, commands: list[str], parser) -> str:
    """Generate a complete markdown page for a command category."""
    lines = []

    # Page title
    title = category_name.replace('-', ' ').title()
    lines.append(f"# {title}\n")

    # Category description
    descriptions = {
        'global-commands': 'Workspace-level commands that operate on the entire ComfyGit workspace.',
        'environment-commands': 'Commands for managing and operating within ComfyUI environments.',
        'node-commands': 'Commands for managing custom nodes within an environment.',
        'workflow-commands': 'Commands for managing and resolving workflow dependencies.',
        'model-commands': 'Commands for managing the global model index and downloading models.',
    }

    if category_name in descriptions:
        lines.append(f"> {descriptions[category_name]}\n")

    # Generate documentation for each command
    for cmd_name in commands:
        cmd_info = get_subcommand_help(parser, cmd_name)
        if cmd_info:
            lines.extend(generate_command_section(cmd_info, level=2))

    return '\n'.join(lines)


def main():
    """Generate CLI reference documentation."""
    # Create output directory
    output_dir = Path(__file__).parent.parent / "docs" / "cli-reference"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get parser
    parser = create_parser()

    # Categorize commands
    categories = categorize_commands(parser)

    # Generate pages
    for category_name, commands in categories.items():
        # Skip duplicate model commands category (already in global)
        if category_name == 'model-commands':
            continue

        output_file = output_dir / f"{category_name}.md"
        content = generate_category_page(category_name, commands, parser)

        print(f"Generating {output_file.name}...")
        output_file.write_text(content)

    # Generate shell completion page (manual content)
    completion_file = output_dir / "shell-completion.md"
    if not completion_file.exists():
        completion_content = """# Shell Completion

> Enable tab completion for ComfyGit CLI commands in your shell.

## Overview

ComfyGit supports tab completion for bash, zsh, and fish shells. Tab completion helps you:

- Autocomplete command names
- Autocomplete environment names
- Autocomplete node names
- Autocomplete workflow names

## Installation

Install tab completion for your current shell:

```bash
cg completion install
```

This will detect your shell automatically and install the appropriate completion script.

## Check Status

Check if tab completion is installed:

```bash
cg completion status
```

## Uninstall

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
"""
        print(f"Generating {completion_file.name}...")
        completion_file.write_text(completion_content)

    print("\n✓ CLI reference documentation generated successfully!")
    print(f"  Output: {output_dir}")


if __name__ == '__main__':
    main()
