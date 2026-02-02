"""Commands for managing shell completion setup."""
import os
import shutil
import subprocess
import sys
from pathlib import Path


class CompletionCommands:
    """Handle shell completion installation and management."""

    COMMANDS = ['comfygit', 'cg']
    COMPLETION_COMMENT = "# ComfyGit tab completion"
    ZSH_INIT_CHECK = 'if ! command -v compdef &> /dev/null; then'

    @classmethod
    def _completion_lines(cls):
        """Generate completion lines for all command aliases."""
        return [f'eval "$(register-python-argcomplete {cmd})"' for cmd in cls.COMMANDS]

    @staticmethod
    def _zsh_compinit_block():
        """Generate zsh compinit initialization block."""
        return [
            "# Initialize zsh completion system if not already loaded",
            "if ! command -v compdef &> /dev/null; then",
            "    autoload -Uz compinit",
            "    compinit",
            "fi",
        ]

    @classmethod
    def _get_manual_install_snippet(cls, shell: str) -> str:
        """Generate copy-paste ready completion snippet for manual installation."""
        lines = [cls.COMPLETION_COMMENT]

        if shell == 'zsh':
            lines.extend(cls._zsh_compinit_block())
            lines.append('')

        lines.extend(cls._completion_lines())
        return '\n'.join(lines)

    @staticmethod
    def _is_config_writable(config_file: Path) -> tuple[bool, str | None]:
        """Check if config file is writable, returning (writable, reason_if_not)."""
        # Check if it's a symlink to a read-only location
        if config_file.is_symlink():
            resolved = config_file.resolve()
            if not os.access(resolved, os.W_OK):
                return False, f"symlink to read-only location:\n  {config_file} -> {resolved}"

        # Check general write permission (handles non-symlink cases)
        if config_file.exists() and not os.access(config_file, os.W_OK):
            return False, "file is not writable (check permissions)"

        # Check parent dir writability for new files
        if not config_file.exists():
            parent = config_file.parent
            if not os.access(parent, os.W_OK):
                return False, f"parent directory is not writable: {parent}"

        return True, None

    @classmethod
    def _print_manual_install_instructions(cls, shell: str, config_file: Path, reason: str):
        """Print helpful instructions when config file cannot be modified."""
        print(f"✗ Cannot modify {config_file}")
        print(f"\nReason: {reason}")
        print("\nThis is common with Home Manager, dotfile managers, and similar tools.")
        print("\nTo enable completions, add this to your shell configuration:")
        print()
        print("─" * 50)
        print(cls._get_manual_install_snippet(shell))
        print("─" * 50)

        # Shell-specific Home Manager hints
        if shell == 'bash':
            print("\nFor Home Manager users, add to your home.nix:")
            print()
            print("  programs.bash.initExtra = ''")
            for line in cls._get_manual_install_snippet(shell).split('\n'):
                print(f"    {line}")
            print("  '';")
        elif shell == 'zsh':
            print("\nFor Home Manager users, add to your home.nix:")
            print()
            print("  programs.zsh.initExtra = ''")
            for line in cls._get_manual_install_snippet(shell).split('\n'):
                print(f"    {line}")
            print("  '';")

    @staticmethod
    def _detect_shell():
        """Detect the user's shell and return shell name and config file path."""
        shell = os.environ.get('SHELL', '')

        if 'bash' in shell:
            config_file = Path.home() / '.bashrc'
            return 'bash', config_file
        elif 'zsh' in shell:
            config_file = Path.home() / '.zshrc'
            return 'zsh', config_file
        else:
            return None, None

    @staticmethod
    def _check_argcomplete_available():
        """Check if register-python-argcomplete is available in PATH."""
        return shutil.which('register-python-argcomplete') is not None

    @staticmethod
    def _install_argcomplete():
        """Install argcomplete globally using uv tool."""
        try:
            print("📦 Installing argcomplete globally...")
            subprocess.run(
                ['uv', 'tool', 'install', 'argcomplete'],
                capture_output=True,
                text=True,
                check=True
            )
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to install argcomplete: {e.stderr}")
            return False
        except FileNotFoundError:
            print("✗ 'uv' command not found. Please install uv first.")
            return False

    @classmethod
    def _is_completion_installed(cls, config_file):
        """Check if completion is already installed in config file."""
        if not config_file.exists():
            return False

        content = config_file.read_text()
        return cls.COMPLETION_COMMENT in content and all(line in content for line in cls._completion_lines())

    @classmethod
    def _add_completion_to_config(cls, shell, config_file):
        """Add completion lines to shell config file."""
        # Ensure file exists
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.touch(exist_ok=True)

        # Read current content
        content = config_file.read_text()

        # Add completion lines at the end
        if content and not content.endswith('\n'):
            content += '\n'

        content += f'\n{cls.COMPLETION_COMMENT}\n'

        # Add zsh compinit initialization if needed
        if shell == 'zsh':
            for line in cls._zsh_compinit_block():
                content += f'{line}\n'
            content += '\n'

        for line in cls._completion_lines():
            content += f'{line}\n'

        # Write back
        config_file.write_text(content)

    @classmethod
    def _remove_completion_from_config(cls, config_file):
        """Remove completion lines from shell config file."""
        if not config_file.exists():
            return False

        lines = config_file.read_text().splitlines(keepends=True)
        new_lines = []
        in_block = False

        for line in lines:
            # Start of completion block
            if cls.COMPLETION_COMMENT in line:
                in_block = True
                continue

            # Inside block - skip all lines until we find a non-completion line
            if in_block:
                # Check if this is part of our block (init, completion, or empty lines)
                stripped = line.strip()
                is_our_line = (
                    not stripped  # empty line
                    or '# Initialize zsh completion system' in line  # our specific comment
                    or cls.ZSH_INIT_CHECK in line  # zsh init check
                    or 'autoload -Uz compinit' in line
                    or stripped == 'compinit'
                    or stripped == 'fi'
                    or any(comp in line for comp in cls._completion_lines())
                )
                if is_our_line:
                    continue
                else:
                    # Non-completion line found, exit block
                    in_block = False

            new_lines.append(line)

        config_file.write_text(''.join(new_lines))
        return True

    def install(self, args):
        """Install shell completion for the current user."""
        shell, config_file = self._detect_shell()

        if not shell:
            print("✗ Could not detect shell (bash or zsh)")
            print("  Your SHELL environment variable is:", os.environ.get('SHELL', 'not set'))
            print("\nManual setup:")
            print("  Add these lines to your shell config file:")
            for line in self._completion_lines():
                print(f"  {line}")
            sys.exit(1)

        # Check if already installed
        if self._is_completion_installed(config_file):
            print(f"✓ Tab completion is already installed in {config_file}")
            print("\nTo activate in current shell, run:")
            print(f"  source {config_file}")
            return

        # Check if config file is writable before proceeding
        writable, reason = self._is_config_writable(config_file)
        if not writable:
            self._print_manual_install_instructions(shell, config_file, reason)
            sys.exit(1)

        # Check if argcomplete is available
        if not self._check_argcomplete_available():
            print("argcomplete not found in PATH")
            print("   Installing argcomplete as a uv tool...")
            if not self._install_argcomplete():
                print("\n✗ Could not install argcomplete automatically")
                print("\nManual installation:")
                print("  uv tool install argcomplete")
                print("\nThen run:")
                print("  cg completion install")
                sys.exit(1)
            print("✓ argcomplete installed")

        # Install completion
        try:
            self._add_completion_to_config(shell, config_file)
            print("\n✓ Tab completion installed successfully!")
            print(f"\nAdded to: {config_file}")
            print("\nTo activate in current shell, run:")
            print(f"  source {config_file}")
            print("\nOr start a new terminal session.")
            print("\nTry it out:")
            print("  cg stat<TAB>")
            print("  cg use <TAB>")
            print("  cg workflow resolve <TAB>")
        except Exception as e:
            print(f"✗ Failed to install completion: {e}")
            sys.exit(1)

    def uninstall(self, args):
        """Remove shell completion from config."""
        shell, config_file = self._detect_shell()

        if not shell:
            print("✗ Could not detect shell (bash or zsh)")
            sys.exit(1)

        if not self._is_completion_installed(config_file):
            print("✓ Tab completion is not installed")
            return

        try:
            self._remove_completion_from_config(config_file)
            print("✓ Tab completion uninstalled")
            print(f"\nRemoved from: {config_file}")
            print("\nRestart your shell for changes to take effect.")
        except Exception as e:
            print(f"✗ Failed to uninstall completion: {e}")
            sys.exit(1)

    def status(self, args):
        """Show completion installation status."""
        shell, config_file = self._detect_shell()

        print("Shell Completion Status")
        print("=" * 40)

        if not shell:
            print("Shell: Unknown")
            print("Status: ✗ Not supported")
            print(f"\nYour SHELL: {os.environ.get('SHELL', 'not set')}")
            print("Supported shells: bash, zsh")
            return

        print(f"Shell: {shell}")
        print(f"Config: {config_file}")

        # Check argcomplete availability
        argcomplete_available = self._check_argcomplete_available()
        print(f"Argcomplete: {'✓ Available' if argcomplete_available else '✗ Not found'}")

        if self._is_completion_installed(config_file):
            print("Status: ✓ Installed")
            if not argcomplete_available:
                print("\n⚠️  Warning: Completion is configured but argcomplete is not in PATH")
                print("   Install with: uv tool install argcomplete")
            print("\nTo uninstall: cg completion uninstall")
        else:
            print("Status: ✗ Not installed")
            print("\nTo install: cg completion install")
