# Contributing to ComfyGit

Thanks for your interest in contributing! ComfyGit is currently a single-developer MVP project, but contributions are welcome.

## Getting Started

### Prerequisites

- Python 3.10+
- [UV](https://github.com/astral-sh/uv) for package management
- Git

### Development Setup

```bash
# Clone the repository
git clone https://github.com/ComfyGit/ComfyGit.git
cd ComfyGit

# Install all packages in development mode
make install

# Or manually with uv
uv sync --all-packages
```

### Project Structure

ComfyGit is a Python monorepo with two main packages:

- **`packages/core/`** - Core library (`comfygit_core`) for programmatic access
- **`packages/cli/`** - CLI wrapper (`comfygit_cli`) providing the `cfd` command

See the codebase maps for detailed architecture:
- [Root codebase map](docs/codebase-map.md)
- [Core codebase map](packages/core/docs/codebase-map.md)
- [CLI codebase map](packages/cli/docs/codebase-map.md)

## Development Workflow

### Running Tests

```bash
# All tests
make test

# Core tests only
uv run pytest packages/core/tests/ -v

# CLI tests only
uv run pytest packages/cli/tests/ -v

# Specific test file
uv run pytest packages/core/tests/integration/test_environment_basic.py -v
```

### Code Quality

```bash
# Lint code
make lint

# Format code
make format

# Both
uv run ruff check --fix && uv run ruff format
```

### Making Changes

1. **Fork and branch** - Create a feature branch from `dev`
2. **Make focused changes** - Keep PRs small and focused on a single feature/fix
3. **Write tests** - Add tests for new functionality (happy path coverage is sufficient for MVP)
4. **Follow existing patterns** - Match the style and architecture of existing code
5. **Update docs** - Update relevant README/docs if changing public APIs

### Core Package Guidelines

The core library (`packages/core/`) is designed as a pure library:

- ❌ **No `print()` or `input()` statements** - Use logging and callback patterns
- ✅ **Use callback protocols** - See `models/protocols.py` for strategy patterns
- ✅ **Raise exceptions** - Don't suppress errors, use custom exception hierarchy
- ✅ **Type hints** - All public APIs should be typed

Example:
```python
# ❌ Bad - print in core library
def add_node(name: str):
    print(f"Installing {name}")
    # ...

# ✅ Good - callback pattern
def add_node(name: str, callback: NodeInstallCallback | None = None):
    if callback:
        callback.on_install_start(name)
    # ...
```

### Testing Philosophy

This is an MVP project - test coverage should focus on:

- **Happy path** - Main use cases work correctly
- **Critical errors** - Major error cases are handled
- **Regression tests** - Fix a bug? Add a test to prevent it returning

We don't need:
- 100% coverage on every edge case
- Exhaustive mocking of every external call
- Tests for every possible input combination

Quality over quantity. See existing tests for examples.

## Submitting Changes

### Before Submitting

1. Run tests: `make test`
2. Run linting: `make lint`
3. Update relevant documentation
4. Ensure your branch is up to date with `dev`

### Pull Request Process

1. **Open an issue first** for significant changes to discuss the approach
2. **Target the `dev` branch** - All PRs should target `dev`, not `main`
3. **Write a clear description** - Explain what and why, not just how
4. **Keep it focused** - One feature/fix per PR
5. **Be patient** - This is a single-developer project, reviews may take time

### PR Title Format

Use conventional commits style:

- `feat: Add workflow auto-resolution`
- `fix: Handle missing model directory`
- `docs: Update installation guide`
- `refactor: Simplify node lookup logic`
- `test: Add tests for environment rollback`

### What to Expect

- **Discussion** - I may ask questions or request changes
- **Iteration** - Be prepared to make adjustments
- **Decisions** - As the maintainer, I have final say on architectural decisions
- **Learning** - I'm open to better approaches and new ideas

## Areas for Contribution

### High-Value Contributions

- **Bug fixes** - Especially with reproduction steps and tests
- **Documentation improvements** - Clarifications, examples, guides
- **Performance optimizations** - With benchmarks showing improvement
- **Platform compatibility** - Windows/Linux/macOS edge cases
- **Test coverage** - For critical paths

### Ideas Welcome

- Feature proposals (open an issue first!)
- UX improvements for CLI
- Better error messages
- Performance improvements

### Not Currently Accepting

- Major architectural refactors (discuss first in an issue)
- New dependencies without strong justification
- Backward compatibility for deprecated features (pre-customer MVP)

## Development Tips

### Using Test Workspaces

For CLI testing, use a dedicated test workspace:

```bash
export COMFYGIT_HOME=/path/to/test/workspace
cfd init
# ... test commands ...
```

Or use the existing one in core:
```bash
export COMFYGIT_HOME=/home/user/ComfyGit/packages/core/.comfygit_workspace
```

### Debugging

- Use `--verbose` flag: `cfd --verbose node add ...`
- Check logs: `cfd logs --level ERROR`

### Common Tasks

```bash
# Run CLI locally
uv run cfd --help

# Run specific module
uv run python -m comfygit_core

# Check version compatibility
make check-versions

# Build packages for testing
make build-all
```

## Version Management

When changing code that affects versions:

```bash
# Show current versions
make show-versions

# Bump a package version
make bump-package PACKAGE=core VERSION=1.0.2

# Check compatibility
make check-versions
```

## Code Style

- Follow existing patterns in the codebase
- Use type hints for public APIs
- Keep functions focused and small
- Prefer explicit over implicit
- Document why, not what (code shows what)

**Imports:**
```python
# Standard library
from pathlib import Path
import json

# Third-party
import requests
from pydantic import BaseModel

# Local
from comfygit_core.models.exceptions import ComfyDockError
from comfygit_core.utils.git import parse_git_url
```

## Questions?

- **Bugs/Features**: [Open an issue](https://github.com/ComfyGit/ComfyGit/issues)
- **Discussions**: [GitHub Discussions](https://github.com/ComfyGit/ComfyGit/discussions)
- **Documentation**: Check the codebase maps and package READMEs

## Contributor License Agreement (CLA)

### Why We Need a CLA

ComfyGit is dual-licensed:
- **AGPL-3.0** for open-source use (free forever)
- **Commercial licenses** for businesses requiring proprietary use

To make this work legally, we need contributors to sign a Contributor License Agreement (CLA). This grants us permission to distribute your contributions under both licensing models.

### What the CLA Means for You

- ✅ **You retain copyright** - You still own your code
- ✅ **Your code stays open-source** - Always available under AGPL-3.0
- ✅ **Enables sustainable funding** - Commercial licenses fund development
- ✅ **One-time signature** - Sign once, contribute forever
- ✅ **Automatic process** - Handled via CLA Assistant on your first PR

### How to Sign

When you submit your first pull request, [CLA Assistant](https://cla-assistant.io/) will automatically prompt you to sign our CLA. Simply:

1. Review the [CLA text](CLA.md)
2. Click the link in the PR comment
3. Sign with your GitHub account
4. That's it! You can now contribute

### View the CLA

Read the full agreement: [CLA.md](CLA.md)

### Questions About the CLA?

**Q: Do I lose rights to my code?**
A: No. You retain full copyright ownership. You're just granting us a license to use it.

**Q: Can I still use my contributions elsewhere?**
A: Yes! You can use your code in any project you want.

**Q: Why do you need this for dual-licensing?**
A: Without a CLA, we can only distribute contributions under AGPL-3.0. The CLA grants us the legal right to also offer commercial licenses, which funds continued development.

**Q: What if I don't want to sign?**
A: We understand! We can't accept contributions without a CLA due to our dual-licensing model. However, you can still:
- Open issues with suggestions
- Discuss ideas in GitHub Discussions
- Fork the project for your own use under AGPL-3.0

### Corporate Contributors

If you're contributing on behalf of your employer, they may need to sign a Corporate CLA. Please contact us to discuss.
