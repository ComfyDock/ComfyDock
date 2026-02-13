# GitHub Actions Workflows

This directory contains workflows for publishing ComfyGit packages and documentation.

## Workflows

### Package Publishing

- **`publish-core.yml`** - Publishes `comfygit-core` to PyPI
- **`publish-cli.yml`** - Publishes `comfygit-cli` to PyPI

Both use manual triggers (`workflow_dispatch`) and trusted publishing via PyPI.

### Documentation Publishing

- **`publish-docs.yml`** - Deploys documentation to https://comfygit.com

**Trigger:** Manual via GitHub Actions UI

**What it does:**
1. Builds MkDocs site from `docs/comfygit-docs/`
2. Pushes built site to `ComfyGit/ComfyGit.github.io:main`
3. GitHub Pages serves the site at `comfygit.com`

**Setup required:**
See "Required Secrets" section below.

## Required Secrets

### For Package Publishing
No secrets needed - uses PyPI trusted publishing with OIDC.

### For Documentation Publishing

**`DOCS_PUBLISH_TOKEN`** - Personal Access Token with write access to `ComfyGit/ComfyGit.github.io`

**To create:**
1. Go to https://github.com/settings/tokens
2. Create new token (classic)
3. Select scopes: `repo` (full control)
4. Copy token
5. Add to repository secrets at https://github.com/ComfyGit/comfygit/settings/secrets/actions
6. Name: `DOCS_PUBLISH_TOKEN`
7. Value: (paste token)

**Note:** Token must belong to a user with write access to the `ComfyGit.github.io` repository.

## Running Workflows

### Via GitHub UI
1. Go to **Actions** tab in repository
2. Select workflow from left sidebar
3. Click **Run workflow** button
4. Select branch (usually `dev` or `main`)
5. Click **Run workflow**

### Via GitHub CLI
```bash
# Publish core package
gh workflow run publish-core.yml

# Publish CLI package
gh workflow run publish-cli.yml

# Publish documentation
gh workflow run publish-docs.yml
```

## Workflow Status

Check workflow runs:
```bash
gh run list --workflow=publish-docs.yml
gh run view <run-id>
```

## Troubleshooting

### Documentation deployment fails with "Permission denied"
- Check that `DOCS_PUBLISH_TOKEN` secret exists
- Verify token hasn't expired
- Ensure token has `repo` scope
- Confirm token owner has write access to `ComfyGit.github.io`

### Package publishing fails
- Check PyPI trusted publishing is configured for the package
- Verify package version hasn't been published already
- Check workflow logs for specific error

### Documentation not updating on comfygit.com
- Wait 1-2 minutes for GitHub Pages to rebuild
- Check `ComfyGit.github.io` repository for new commits
- Verify CNAME file exists in deployed site
- Check GitHub Pages settings in `ComfyGit.github.io` repository
