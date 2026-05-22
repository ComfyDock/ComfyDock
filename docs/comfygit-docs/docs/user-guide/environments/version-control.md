# Environment History

Each ComfyGit environment is a Git repository. Commits are environment
snapshots: manifest changes, workflow files, model metadata, node metadata, and
workflow contract artifacts.

Model bytes and runtime directories are not committed.

## Check Status

```bash
cg status
```

Use verbose status for more detail:

```bash
cg status --verbose
```

## Commit Changes

```bash
cg commit -m "Add image upscale workflow"
```

Before committing, ComfyGit checks the environment for unresolved workflow,
model, and reproducibility issues.

If you deliberately need to commit with issues:

```bash
cg commit -m "Save work in progress" --allow-issues
```

## View History

```bash
cg log
cg log -n 5 --verbose
```

## Branch And Switch

```bash
cg branch experiment
cg switch experiment
```

Create and switch in one command:

```bash
cg switch new-idea -c
```

After switching, ComfyGit reconciles the runtime toward the checked-out
manifest.

## Explore Older State

```bash
cg checkout <commit>
```

Return to a branch:

```bash
cg switch main
```

## Undo Changes

Create a new commit that undoes an older commit:

```bash
cg revert <commit>
```

Move the current branch pointer while keeping changes in the working tree:

```bash
cg reset HEAD~1 --mixed
```

Discard local changes only when you really mean it:

```bash
cg reset HEAD --hard --yes
```

## Merge

Preview a merge:

```bash
cg merge feature-branch --preview
```

Merge a branch:

```bash
cg merge feature-branch
```

## Push And Pull

Remote collaboration is covered in [Git remotes](../collaboration/git-remotes.md).

Quick example:

```bash
cg remote add origin git@github.com:team/my-env.git
cg push
cg pull -r origin --models required
```

## Repairing Environments

If a branch switch, pull, reset, or manual filesystem edit leaves the runtime in
an inconsistent state, repair the environment from the tracked manifest:

```bash
cg repair
```

For more detail, see [Sync and repair](sync-and-repair.md).

## What Git Tracks

Git tracks portable environment truth:

- `pyproject.toml`
- workflow JSON files
- workflow API prompt artifacts
- shared overlays
- metadata needed to reinstall nodes and dependencies

Git does not track:

- model bytes
- `.venv`
- ComfyUI runtime checkout state
- local overlays
- caches
- logs

!!! note "Media placeholder"
    Add a before/after diff screenshot showing a workflow model dependency and a
    source URL added to the manifest.
