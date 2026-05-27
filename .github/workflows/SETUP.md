# PyPI Publishing Setup Guide

## Package Naming

ComfyGit publishes three lockstep Python packages:

- `comfygit-core`: reusable core library.
- `comfygit-studio`: shared Studio/contract API runtime and bundled Studio SPA.
- `comfygit`: CLI package.

**Note:** PyPI normalizes names, so underscores and hyphens are treated as the
same package separator. Users can install with either normalized form:
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
   - **Workflow name**: publish.yml
   - **Environment name**: pypi

For **comfygit_studio**:
1. Go to https://pypi.org/manage/account/publishing/
2. Click "Add a new pending publisher"
3. Fill in:
   - **PyPI Project Name**: comfygit_studio
   - **Owner**: comfygit-ai
   - **Repository name**: comfygit
   - **Workflow name**: publish.yml
   - **Environment name**: pypi

For **comfygit**:
1. Go to https://pypi.org/manage/account/publishing/
2. Click "Add a new pending publisher"
3. Fill in:
   - **PyPI Project Name**: comfygit
   - **Owner**: comfygit-ai
   - **Repository name**: comfygit
   - **Workflow name**: publish.yml
   - **Environment name**: pypi

### 3. Test Locally

```bash
# Test building all release packages
make build-all

# Inspect artifacts
ls -lh dist/

# Should see:
# comfygit_core-1.0.0-py3-none-any.whl
# comfygit_core-1.0.0.tar.gz
# comfygit_studio-1.0.0-py3-none-any.whl
# comfygit_studio-1.0.0.tar.gz
# comfygit-1.0.0-py3-none-any.whl
# comfygit-1.0.0.tar.gz
```

## Publishing Workflow

### Publish Lockstep Release

```bash
# 1. Bump version
make bump-version VERSION=1.0.1

# 2. Test builds
make build-all

# 3. Commit and push
git add packages/core/pyproject.toml packages/studio-runtime/pyproject.toml packages/cli/pyproject.toml packages/studio/package.json uv.lock
git commit -m "bump: v1.0.1 release"
git push

# 4. Go to Actions → "Publish Packages" → Run workflow
```

## Troubleshooting

### CLI Build Fails: "comfygit_core" or "comfygit_studio" not found

The CLI depends on core and Studio runtime from PyPI. Make sure:
1. Core has been published to PyPI first
2. Studio runtime has been published to PyPI after core
3. All package versions match exactly
4. Wait 2-3 minutes after publishing each dependency for PyPI to index

### Workflow Fails: "Trusted publishing exchange failure"

Make sure you've configured the trusted publisher on PyPI correctly:
- Correct repository owner and name
- Exact workflow filename (`publish.yml`)
- Environment name `pypi`

### Permission Denied

The workflows use `id-token: write` permission for trusted publishing. This is automatically provided by GitHub Actions when OIDC is enabled.
