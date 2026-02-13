# PyPI Publishing Setup Guide

## Package Naming

Your packages are now consistently named with underscores to match your existing PyPI package:

- `comfygit_core` (was: comfygit-core)
- `comfygit_cli` (new)

**Note:** PyPI normalizes names, so `comfygit_core` and `comfygit-core` are treated as the same package. Users can install with either:
```bash
pip install comfygit_core  # Matches package name
pip install comfygit-core  # Also works (normalized)
```

## Before First Publish

### 1. Create GitHub Environment (Optional but Recommended)

Add a `pypi` environment to your repository for approval gates:

1. Go to https://github.com/comfygit-ai/comfygit/settings/environments
2. Click **New environment**
3. Name: `pypi`
4. Configure protection rules (optional):
   - **Required reviewers**: Add yourself for manual approval before publishing
   - **Wait timer**: Add a delay (e.g., 5 minutes) for sanity checks
   - **Deployment branches**: Restrict to `main` branch only

This adds an approval step before packages are published to PyPI, preventing accidental releases.

### 2. Configure PyPI Trusted Publishing

For **comfygit_core**:
1. Go to https://pypi.org/manage/project/comfygit_core/settings/publishing/
2. Add publisher:
   - **Owner**: comfygit-ai
   - **Repository name**: comfygit
   - **Workflow name**: publish-core.yml
   - **Environment name**: pypi

For **comfygit_cli** (new project):
1. Go to https://pypi.org/manage/account/publishing/
2. Click "Add a new pending publisher"
3. Fill in:
   - **PyPI Project Name**: comfygit_cli
   - **Owner**: comfygit-ai
   - **Repository name**: comfygit
   - **Workflow name**: publish-cli.yml
   - **Environment name**: pypi

### 3. Test Locally

```bash
# Test building both packages
make build-all

# Inspect artifacts
ls -lh dist/

# Should see:
# comfygit_core-1.0.0-py3-none-any.whl
# comfygit_core-1.0.0.tar.gz
# comfygit_cli-1.0.0-py3-none-any.whl
# comfygit_cli-1.0.0.tar.gz
```

## Publishing Workflow

### Option 1: Publish Core Only

```bash
# 1. Bump version
make bump-package PACKAGE=core VERSION=1.0.1

# 2. Test build
make build-core

# 3. Commit and push
git add packages/core/pyproject.toml
git commit -m "bump: core v1.0.1"
git push

# 4. Go to GitHub Actions and trigger "Publish Core Package"
```

### Option 2: Publish CLI Only

```bash
# 1. Bump version
make bump-package PACKAGE=cli VERSION=1.0.1

# 2. Test build
make build-cli

# 3. Commit and push
git add packages/cli/pyproject.toml
git commit -m "bump: cli v1.0.1"
git push

# 4. Go to GitHub Actions and trigger "Publish CLI Package"
```

### Option 3: Publish Both (Major Release)

**Important:** Publish core first, wait, then publish CLI.

```bash
# 1. Bump both versions
make bump-package PACKAGE=core VERSION=1.1.0
make bump-package PACKAGE=cli VERSION=1.1.0

# 2. Test builds
make build-all

# 3. Commit and push
git add packages/*/pyproject.toml
git commit -m "bump: v1.1.0 release"
git push

# 4. Publish core first
#    Go to Actions → "Publish Core Package" → Run workflow

# 5. Wait 2-3 minutes for PyPI to index

# 6. Publish CLI
#    Go to Actions → "Publish CLI Package" → Run workflow
```

## Troubleshooting

### CLI Build Fails: "comfygit_core not found"

The CLI depends on core from PyPI. Make sure:
1. Core has been published to PyPI first
2. The version matches (or CLI allows the core version range)
3. Wait 2-3 minutes after publishing core for PyPI to index

### Workflow Fails: "Trusted publishing exchange failure"

Make sure you've configured the trusted publisher on PyPI correctly:
- Correct repository owner and name
- Exact workflow filename (publish-core.yml or publish-cli.yml)
- Environment name left blank

### Permission Denied

The workflows use `id-token: write` permission for trusted publishing. This is automatically provided by GitHub Actions when OIDC is enabled.
